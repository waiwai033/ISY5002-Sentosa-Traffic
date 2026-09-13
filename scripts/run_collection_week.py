#!/usr/bin/env python3
"""Run the dated eight-camera campaign, or inspect/test it without starting it."""
import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from fetch_lta_camera_images import ROOT, load_cameras, main, parse_timestamp, positive

TRIAL_DIR = 'data/trial-eight-cameras'


def load_plan(path):
    plan = json.loads(path.read_text())
    start, end = map(parse_timestamp, (plan['start_at'], plan['end_at']))
    if start >= end:
        raise ValueError('Campaign end must follow start')
    positive(str(plan['interval_minutes']))
    cameras = load_cameras(ROOT / plan['camera_csv'])
    return plan, start, end, cameras


def run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'reference/collection_week.json')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--once', action='store_true', help='Trial now; saves outside campaign dataset')
    mode.add_argument('--sample', action='store_true',
                      help='One campaign cycle now; skipped outside the campaign window')
    parser.add_argument('--max-runtime-minutes', type=positive, help='Limit one GitHub worker batch')
    args = parser.parse_args(argv)
    plan, start, end, cameras = load_plan(args.config)
    if args.check:
        print(json.dumps({**plan, 'camera_ids': [c['CameraID'] for c in cameras],
                          'road_groups': sorted({c['RoadSegment'] for c in cameras}),
                          'start_utc': start.isoformat(), 'end_utc': end.isoformat(),
                          'planned_cycles': math.ceil((end-start).total_seconds() / (plan['interval_minutes']*60)),
                          'enabled': 'Check mode only; does not start or enable collection'}, indent=2))
        return 0
    output = TRIAL_DIR if args.once else plan['output_dir']
    command = ['--camera-csv', str(ROOT / plan['camera_csv']), '--output-dir', str(ROOT / output),
               '--source', plan['source'], '--interval-minutes', str(plan['interval_minutes']),
               '--active-start', plan['active_start'], '--active-end', plan['active_end']]
    if args.once:
        command += ['--once']
    elif args.sample:
        # One cycle per worker: a delayed or dropped cron tick costs a single sample,
        # not the whole hour, and each job bills about a minute instead of fifty-five.
        now = datetime.now(timezone.utc)
        if not start <= now < end:
            print('Campaign window is not open; no sample taken')
            return 0
        command += ['--once']
    else:
        command += ['--start-at', plan['start_at'], '--end-at', plan['end_at']]
        if args.max_runtime_minutes:
            # Scheduled jobs must be gated by the workflow; don't wait for days on a runner.
            if datetime.now(timezone.utc) < start:
                print('Campaign has not started; bounded worker skipped')
                return 0
            command += ['--duration-days', str(args.max_runtime_minutes / 1440)]
        else:
            command += ['--duration-days', str((end-start).total_seconds() / 86400)]
    return main(command)


if __name__ == '__main__':
    try:
        raise SystemExit(run())
    except KeyboardInterrupt:
        raise SystemExit(130)
