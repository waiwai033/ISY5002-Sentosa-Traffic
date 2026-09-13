#!/usr/bin/env python3
"""Collect selected Singapore traffic cameras with an auditable CSV manifest."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import math
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SG = ZoneInfo("Asia/Singapore")
UTC = timezone.utc
ENDPOINTS = {
    "data-gov-sg": "https://api.data.gov.sg/v1/transport/traffic-images",
    "lta": "https://datamall2.mytransport.sg/ltaodataservice/Traffic-Imagesv2",
}
OLD_RESEARCH_CAMERAS = {"2701", "2702", "2704", "2706", "4703", "4707", "4712", "4713"}
FIELDS = ["collected_at_utc", "collected_at_sgt", "camera_id", "road_segment",
          "direction", "source", "captured_at_utc", "captured_at_sgt", "timestamp_basis",
          "status", "image_path", "sha256", "bytes", "source_url", "error"]


def iso(dt):
    return dt.isoformat(timespec="seconds")


def parse_timestamp(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Source timestamp must include timezone")
    return dt.astimezone(UTC)


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Must be a finite positive number")
    return number


def parse_clock(value):
    if value == "24:00":
        return 86400
    if not re.fullmatch(r"\d{2}:\d{2}", value):
        raise argparse.ArgumentTypeError("Expected HH:MM")
    h, m = map(int, value.split(":"))
    if h > 23 or m > 59:
        raise argparse.ArgumentTypeError("Invalid time")
    return h * 3600 + m * 60


def active(seconds, start, end):
    return start <= seconds < end if start < end else seconds >= start or seconds < end


def load_cameras(path):
    with path.open(newline="", encoding="utf-8") as stream:
        cameras = list(csv.DictReader(stream))
    if not cameras:
        raise ValueError("Camera CSV is empty")
    seen = set()
    for camera in cameras:
        cid = camera["CameraID"]
        if not re.fullmatch(r"\d+", cid) or cid in seen:
            raise ValueError("Camera IDs must be unique numeric strings")
        if cid in OLD_RESEARCH_CAMERAS:
            raise ValueError(f"Camera {cid} overlaps with the original research dataset")
        for column in ("RoadSegment", "Direction", "Latitude", "Longitude"):
            if not camera.get(column):
                raise ValueError(f"Missing {column} for {cid}")
        seen.add(cid)
    return cameras


def fetch_bytes(url, headers=None):
    """Retry temporary failures only; never expose credentials or signed URLs in logs."""
    if urlsplit(url).scheme != "https":
        raise ValueError("Only HTTPS data sources are accepted")
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": "ISY5002-Traffic-Research/1.0", **(headers or {})})
            with urlopen(request, timeout=30) as response:
                return response.read()
        except HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise RuntimeError(f"HTTP {error.code}") from None
            try:
                delay = min(60, max(1, int(error.headers.get("Retry-After", "5"))))
            except ValueError:
                delay = 5
        except (URLError, TimeoutError, OSError):
            if attempt == 2:
                raise RuntimeError("Network request failed after 3 attempts") from None
            delay = 2 ** (attempt + 1)
        time.sleep(delay)


def normalize(payload, source):
    if source == "data-gov-sg":
        items = payload.get("items")
        if not items or not isinstance(items[0].get("cameras"), list):
            raise ValueError("Unexpected data.gov.sg metadata schema")
        return {str(c["camera_id"]): {"url": c["image"], "captured": c["timestamp"]}
                for c in items[0]["cameras"]}
    if not isinstance(payload.get("value"), list):
        raise ValueError("Unexpected LTA metadata schema")
    # LTA ImageLink does not document a capture timestamp. Do not guess from filenames.
    return {str(c["CameraID"]): {"url": c.get("ImageLink"), "captured": None}
            for c in payload["value"]}


def atomic_bytes(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_bytes(content)
    temporary.replace(path)


def collect_cycle(cameras, output, source, headers, max_age_minutes=15, now=None):
    now = now or datetime.now(UTC)
    run_id = now.strftime("%Y%m%dT%H%M%S%fZ")
    output.mkdir(parents=True, exist_ok=True)
    state_path = output / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    metadata_error = None
    try:
        raw = fetch_bytes(ENDPOINTS[source], headers)
        payload = json.loads(raw)
        # Public API response is preserved verbatim. LTA responses contain short-lived
        # signed links, so retain query-free links in the metadata archive.
        if source == "lta":
            for entry in payload.get("value", []):
                if entry.get("ImageLink"):
                    entry["ImageLink"] = entry["ImageLink"].split("?", 1)[0]
            archived = json.dumps(payload).encode()
            metadata = normalize(json.loads(raw), source)
        else:
            archived = raw
            metadata = normalize(payload, source)
        atomic_bytes(output / "metadata" / f"{run_id}.json", archived)
    except (RuntimeError, ValueError, KeyError, TypeError) as error:
        metadata, metadata_error = {}, f"Metadata unavailable ({type(error).__name__})"
    rows = []
    for camera in cameras:
        cid = camera["CameraID"]
        row = dict.fromkeys(FIELDS, "")
        row.update(collected_at_utc=iso(now), collected_at_sgt=iso(now.astimezone(SG)),
                   camera_id=cid, road_segment=camera["RoadSegment"],
                   direction=camera["Direction"], source=source)
        try:
            if metadata_error:
                raise RuntimeError(metadata_error)
            if cid not in metadata or not metadata[cid].get("url"):
                row["status"] = "missing"
            else:
                entry = metadata[cid]
                captured = parse_timestamp(entry["captured"]) if entry["captured"] else now
                row.update(captured_at_utc=iso(captured), captured_at_sgt=iso(captured.astimezone(SG)),
                           timestamp_basis="source" if entry["captured"] else "collection_time_proxy",
                           source_url=entry["url"].split("?", 1)[0])
                age = (now - captured).total_seconds()
                if entry["captured"] and (age > max_age_minutes * 60 or age < -300):
                    row.update(status="stale", error=f"Source timestamp age {age:.0f} seconds")
                else:
                    content = fetch_bytes(entry["url"])
                    if not content.startswith(b"\xff\xd8\xff") or not content.rstrip().endswith(b"\xff\xd9"):
                        raise ValueError("Response is not a complete JPEG")
                    digest = hashlib.sha256(content).hexdigest()
                    previous = state.get(f"{source}:{cid}", {})
                    row.update(sha256=digest, bytes=len(content))
                    if previous.get("sha256") == digest and (output / previous["image_path"]).exists():
                        row.update(status="duplicate", image_path=previous["image_path"])
                    else:
                        # All filename time tokens use UTC. Prefer manifest timestamps in analysis.
                        filename = f"{captured:%Y%m%dT%H%M%SZ}_{cid}_{captured:%H%M}_{digest[:12]}.jpg"
                        relative = Path("images") / cid / filename
                        destination = output / relative
                        row.update(status="duplicate" if destination.exists() else "downloaded",
                                   image_path=relative.as_posix())
                        if not destination.exists():
                            atomic_bytes(destination, content)
                        state[f"{source}:{cid}"] = {"sha256": digest, "image_path": relative.as_posix()}
        except (RuntimeError, ValueError, KeyError, TypeError) as error:
            row.update(status="error", error=f"{type(error).__name__}: {error}")
        rows.append(row)
        logging.info("camera=%s status=%s", cid, row["status"])
    manifest = output / "manifest.csv"
    needs_header = not manifest.exists() or manifest.stat().st_size == 0
    with manifest.open("a", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        if needs_header:
            writer.writeheader()
        writer.writerows(rows)
    atomic_bytes(state_path, json.dumps(state, indent=2).encode())
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera-csv", type=Path, default=ROOT / "reference/camera_info.csv")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/lta_images")
    parser.add_argument("--source", choices=ENDPOINTS, default="data-gov-sg")
    parser.add_argument("--interval-minutes", type=positive, default=5)
    parser.add_argument("--duration-days", type=positive, default=7)
    parser.add_argument("--active-start", type=parse_clock, default=parse_clock("05:00"))
    parser.add_argument("--active-end", type=parse_clock, default=parse_clock("24:00"))
    parser.add_argument("--max-age-minutes", type=positive, default=15)
    parser.add_argument("--once", action="store_true", help="Run one cycle now, ignoring active hours")
    args = parser.parse_args(argv)
    if args.active_start == 86400 or args.active_start == args.active_end:
        parser.error("Invalid active window; use 00:00 to 24:00 for all day")
    key_name = "LTA_API_KEY" if args.source == "lta" else "DATA_GOV_SG_API_KEY"
    key = os.environ.get(key_name)
    if args.source == "lta" and not key:
        parser.error("Set LTA_API_KEY in the environment for the LTA source")
    headers = {("AccountKey" if args.source == "lta" else "X-Api-Key"): key} if key else {}
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cameras = load_cameras(args.camera_csv)
    deadline = time.monotonic() + args.duration_days * 86400
    interval = args.interval_minutes * 60
    cycles, successes, last_success = 0, 0, False
    # A process-level lock prevents accidental concurrent writes on macOS/Linux.
    import fcntl
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / ".collector.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logging.error("Another collector is already using this output directory")
            return 1
        while time.monotonic() < deadline:
            started = time.monotonic()
            local = datetime.now(SG)
            seconds = local.hour * 3600 + local.minute * 60 + local.second
            if args.once or active(seconds, args.active_start, args.active_end):
                rows = collect_cycle(cameras, args.output_dir, args.source, headers, args.max_age_minutes)
                cycles += 1
                last_success = all(r["status"] in ("downloaded", "duplicate") for r in rows)
                successes += int(last_success)
                if args.once:
                    return 0 if last_success else 1
                delay = max(0, started + interval - time.monotonic())
            else:
                delay = 60
            time.sleep(max(0, min(delay, deadline - time.monotonic())))
    logging.info("Finished: %d cycles, %d complete cycles", cycles, successes)
    return 0 if successes and last_success else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logging.info("Stopped by user")
        sys.exit(130)
