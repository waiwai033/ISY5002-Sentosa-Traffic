import csv
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "scripts/fetch_lta_camera_images.py"
SPEC = importlib.util.spec_from_file_location("collector", MODULE)
c = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(c)


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name)
        self.cameras = c.load_cameras(c.ROOT / "reference/camera_info.csv")
        self.now = datetime(2026, 9, 13, 6, 20, tzinfo=timezone.utc)

    def payload(self, timestamp=None):
        return json.dumps({"items": [{"cameras": [
            {"camera_id": row["CameraID"], "timestamp": timestamp or c.iso(self.now),
             "image": "https://example.test/image.jpg"} for row in self.cameras]}]}).encode()

    def collect(self, metadata=None, content=b"\xff\xd8\xfftest\xff\xd9", now=None):
        with patch.object(c, "fetch_bytes", side_effect=lambda url, headers=None:
                          metadata if url == c.ENDPOINTS["data-gov-sg"] else content):
            return c.collect_cycle(self.cameras, self.output, "data-gov-sg", {}, now=now or self.now)

    def test_real_configuration_excludes_original_research(self):
        self.assertEqual({x["CameraID"] for x in self.cameras}, {"4798", "4799"})
        self.assertTrue(c.OLD_RESEARCH_CAMERAS.isdisjoint(x["CameraID"] for x in self.cameras))

    def test_restart_dedup_and_timezone_rollover(self):
        now = self.now.replace(hour=18)
        metadata = self.payload(c.iso(now))
        first = self.collect(metadata, now=now)
        self.assertEqual([r["status"] for r in first], ["downloaded"] * 2)
        self.assertTrue(first[0]["captured_at_sgt"].startswith("2026-09-14T02:20"))
        second = self.collect(metadata, now=now + timedelta(minutes=5))
        self.assertEqual([r["status"] for r in second], ["duplicate"] * 2)
        self.assertEqual(len(list(self.output.rglob("*.jpg"))), 2)
        with (self.output / "manifest.csv").open() as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 4)

    def test_stale_frames_are_not_training_samples(self):
        metadata = self.payload(c.iso(self.now - timedelta(hours=1)))
        self.assertEqual([r["status"] for r in self.collect(metadata)], ["stale"] * 2)
        self.assertFalse(list(self.output.rglob("*.jpg")))

    def test_missing_and_corrupt_images(self):
        empty = json.dumps({"items": [{"cameras": []}]}).encode()
        self.assertEqual([r["status"] for r in self.collect(empty)], ["missing"] * 2)
        self.assertEqual([r["status"] for r in self.collect(self.payload(), b"<html>error</html>")], ["error"] * 2)

    def test_network_failure_is_audited(self):
        with patch.object(c, "fetch_bytes", side_effect=RuntimeError("Network unavailable")):
            rows = c.collect_cycle(self.cameras, self.output, "data-gov-sg", {}, now=self.now)
        self.assertEqual([r["status"] for r in rows], ["error"] * 2)
        self.assertTrue((self.output / "manifest.csv").exists())

    def test_lta_signed_urls_are_not_archived(self):
        signed = "https://example.test/image.jpg?secret=ephemeral"
        payload = json.dumps({"value": [{"CameraID": "4798", "ImageLink": signed}]}).encode()
        with patch.object(c, "fetch_bytes", side_effect=lambda url, headers=None:
                          payload if url == c.ENDPOINTS["lta"] else b"\xff\xd8\xfftest\xff\xd9"):
            rows = c.collect_cycle(self.cameras, self.output, "lta", {"AccountKey": "test"}, now=self.now)
        self.assertEqual(rows[0]["timestamp_basis"], "collection_time_proxy")
        self.assertEqual(rows[1]["status"], "missing")
        for path in self.output.rglob("*"):
            if path.suffix in (".json", ".csv"):
                self.assertNotIn("ephemeral", path.read_text())

    def test_windows_and_invalid_intervals(self):
        self.assertTrue(c.active(23 * 3600, 22 * 3600, 5 * 3600))
        self.assertTrue(c.active(3600, 22 * 3600, 5 * 3600))
        self.assertFalse(c.active(5 * 3600, 22 * 3600, 5 * 3600))
        for value in ("nan", "inf", "0", "-1"):
            with self.assertRaises(c.argparse.ArgumentTypeError):
                c.positive(value)


if __name__ == "__main__":
    unittest.main()
