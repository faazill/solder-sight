"""Closed-loop job runner: move -> solder -> raise -> look -> decide (good / retry / human)."""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path

import cv2

from config import Config
from geometry import crop_window, mm_to_px
from inspection import InspectionResult, Inspector, Outcome
from job import Job, JobPoint
from machine import Machine


@dataclass
class JointResult:
    id: int
    x_mm: float
    y_mm: float
    outcome: Outcome
    attempts: int
    score: float
    reason: str


class JobRunner:
    def __init__(self, cfg: Config, machine: Machine, camera, inspector: Inspector,
                 run_dir: Path | None = None, log=print, sleep=time.sleep):
        self.cfg, self.machine, self.camera, self.inspector = cfg, machine, camera, inspector
        self.run_dir, self.log, self.sleep = run_dir, log, sleep
        if run_dir:
            Path(run_dir).mkdir(parents=True, exist_ok=True)

    # ---- vision ---------------------------------------------------------
    def _look(self, job: Job, p: JobPoint):
        m = self.cfg.motion
        if m.park_x is not None:
            self.machine.move_z(m.z_safe)
            self.machine.move_xy(m.park_x, m.park_y)
        self.sleep(m.settle_s)
        frame = self.camera.capture()
        cx, cy = mm_to_px((p.x_mm, p.y_mm), job.box_px, job.width_mm, job.height_mm)
        px_per_mm = (job.box_px[2] - job.box_px[0]) / job.width_mm
        size = int(self.cfg.inspection.crop_mm * px_per_mm)
        left, top, right, bottom = crop_window(cx, cy, size, frame.shape[1], frame.shape[0])
        return frame[top:bottom, left:right].copy()

    def _save(self, p, attempt, before, after, res: InspectionResult):
        if not self.run_dir:
            return
        base = Path(self.run_dir) / f"joint{p.id:03d}_try{attempt}"
        if before is not None:
            cv2.imwrite(f"{base}_before.png", before)
        cv2.imwrite(f"{base}_after_{res.outcome.value}.png", after)

    # ---- one joint ------------------------------------------------------
    def _do_joint(self, job: Job, p: JobPoint) -> JointResult:
        m, c = self.cfg.motion, self.cfg.inspection
        before = self._look(job, p)
        attempts = 0
        while True:
            attempts += 1
            self.machine.move_z(m.z_safe)
            self.machine.move_xy_box(p.x_mm, p.y_mm)
            self.machine.move_z(m.z_solder)
            self.machine.pulse()
            self.machine.move_z(m.z_safe)

            after = self._look(job, p)
            res = self.inspector.inspect(before, after)
            self._save(p, attempts, before, after, res)
            self.log(f"  joint {p.id} try {attempts}: {res.outcome.value} ({res.reason})")

            if res.outcome in (Outcome.GOOD, Outcome.HUMAN):
                return JointResult(p.id, p.x_mm, p.y_mm, res.outcome, attempts, res.score, res.reason)
            if attempts > c.max_retries:
                return JointResult(p.id, p.x_mm, p.y_mm, Outcome.HUMAN, attempts, res.score,
                                   f"max retries reached ({res.reason})")
            before = after

    # ---- whole job ------------------------------------------------------
    def run(self, job: Job) -> list[JointResult]:
        job.validate()
        results: list[JointResult] = []
        try:
            self.machine.prepare()
            self.machine.home()
            self.machine.move_z(self.cfg.motion.z_safe)
            for p in job.points:
                self.log(f"Joint {p.id}/{len(job.points)} at ({p.x_mm:.2f}, {p.y_mm:.2f}) mm")
                results.append(self._do_joint(job, p))
        finally:
            self.machine.safe_stop()  # solder off, tip up, even on Ctrl+C or error
            self._write_results(results)
        return results

    def _write_results(self, results):
        if not self.run_dir or not results:
            return
        with open(Path(self.run_dir) / "results.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "x_mm", "y_mm", "outcome", "attempts", "score", "reason"])
            for r in results:
                w.writerow([r.id, r.x_mm, r.y_mm, r.outcome.value, r.attempts, f"{r.score:.3f}", r.reason])
