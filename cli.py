"""Command line runner.

Dry run (default, nothing moves):  python cli.py job.json -c machine.yaml
Real machine:                      python cli.py job.json -c machine.yaml --live
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

from camera import Camera, StaticImageCamera
from config import load_config
from inspection import HeuristicInspector, Outcome
from job import Job
from machine import DryRunTransport, Machine, SerialTransport
from runner import JobRunner


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run a Solder Sight job.")
    ap.add_argument("job", help="job.json exported from the app")
    ap.add_argument("-c", "--config", required=True, help="machine YAML config")
    ap.add_argument("--live", action="store_true", help="send commands to the real machine")
    ap.add_argument("--image", help="use this image instead of a camera (testing)")
    ap.add_argument("--runs-dir", default="runs")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    job = Job.load(args.job)
    run_dir = Path(args.runs_dir) / time.strftime("%Y%m%d-%H%M%S")

    if args.live:
        print(f"LIVE MODE on {cfg.serial.port}. The tip will move and solder will be triggered.")
        print("Check: emergency stop within reach, board clamped, Z limits verified.")
        if input("Type START to continue: ").strip() != "START":
            print("Cancelled.")
            return 1
        transport = SerialTransport(cfg.serial.port, cfg.serial.baud, cfg.serial.timeout_s)
        machine = Machine(cfg, transport)
    else:
        print("DRY RUN: no hardware is contacted.")
        transport = DryRunTransport()
        machine = Machine(cfg, transport, sleep=lambda s: None)

    camera = StaticImageCamera(args.image) if args.image else Camera(cfg.inspection.camera_index)
    runner = JobRunner(cfg, machine, camera, HeuristicInspector(cfg.inspection), run_dir=run_dir,
                       sleep=(time.sleep if args.live else (lambda s: None)))
    try:
        results = runner.run(job)
    finally:
        camera.release()
        transport.close()

    counts = Counter(r.outcome for r in results)
    print(f"\nDone: {counts[Outcome.GOOD]} good, {counts[Outcome.HUMAN]} need a human. "
          f"Results saved in {run_dir}")
    if not args.live:
        print(f"Dry run produced {len(transport.lines)} G-code lines (first 12):")
        print("\n".join(transport.lines[:12]))
    return 0 if counts[Outcome.HUMAN] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
