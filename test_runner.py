import numpy as np
import pytest

from config import Config
from inspection import HeuristicInspector, InspectionResult, Outcome
from job import Job
from machine import DryRunTransport, LimitError, Machine
from runner import JobRunner


class FakeCamera:
    def capture(self):
        return np.zeros((480, 640, 3), dtype=np.uint8)


class Scripted:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)

    def inspect(self, before, after):
        return InspectionResult(self.outcomes.pop(0), 0.5, "scripted")


def make(outcomes, **overrides):
    cfg = Config()
    for k, v in overrides.items():
        setattr(cfg.motion, k, v)
    transport = DryRunTransport()
    machine = Machine(cfg, transport, sleep=lambda s: None)
    runner = JobRunner(cfg, machine, FakeCamera(), Scripted(outcomes), log=lambda *_: None,
                       sleep=lambda s: None)
    return runner, transport


def job(points=((10.0, 10.0),)):
    return Job.from_points(points, 100, 60, (0, 0, 640, 480))


def test_good_joint_one_attempt():
    runner, t = make([Outcome.GOOD])
    res = runner.run(job())
    assert res[0].outcome is Outcome.GOOD and res[0].attempts == 1
    assert "M3 S1000" in t.lines and t.lines[-1].startswith("G1 Z")


def test_retry_then_good():
    runner, _ = make([Outcome.RETRY, Outcome.GOOD])
    res = runner.run(job())
    assert res[0].outcome is Outcome.GOOD and res[0].attempts == 2


def test_retries_exhausted_goes_to_human():
    runner, _ = make([Outcome.RETRY] * 3)  # 1 try + 2 retries
    res = runner.run(job())
    assert res[0].outcome is Outcome.HUMAN and res[0].attempts == 3


def test_human_outcome_is_never_retried():
    runner, _ = make([Outcome.HUMAN])
    res = runner.run(job())
    assert res[0].attempts == 1


def test_z_is_raised_before_xy_travel():
    runner, t = make([Outcome.GOOD, Outcome.GOOD])
    runner.run(job(((10.0, 10.0), (50.0, 30.0))))
    xy_idx = [i for i, ln in enumerate(t.lines) if ln.startswith("G1 X")]
    for i in xy_idx:
        prev_z = [ln for ln in t.lines[:i] if ln.startswith("G1 Z")][-1]
        assert prev_z.startswith("G1 Z20.000")  # z_safe


def test_solder_off_even_if_machine_fails_midway():
    runner, t = make([Outcome.GOOD], box_origin_x=500.0)  # beyond X limit
    with pytest.raises(LimitError):
        runner.run(job())
    assert "M5" in t.lines  # safe_stop ran
    assert "M3 S1000" not in t.lines  # never triggered


def test_job_rejects_points_outside_box():
    with pytest.raises(ValueError):
        Job.from_points([(150.0, 10.0)], 100, 60, (0, 0, 640, 480))


def test_job_json_roundtrip():
    j = job(((1.5, 2.5), (3.0, 4.0)))
    j2 = Job.from_json(j.to_json())
    assert [(p.x_mm, p.y_mm) for p in j2.points] == [(1.5, 2.5), (3.0, 4.0)]


def test_heuristic_inspector_classes():
    cfg = Config().inspection
    insp = HeuristicInspector(cfg)
    dark = np.zeros((64, 64, 3), dtype=np.uint8)
    white = np.full((64, 64, 3), 255, dtype=np.uint8)
    blob = dark.copy()
    yy, xx = np.ogrid[:64, :64]
    blob[((xx - 32) ** 2 + (yy - 32) ** 2) <= 10**2] = 255  # ~15% coverage

    assert insp.inspect(dark, blob).outcome is Outcome.GOOD
    assert insp.inspect(dark, dark).outcome is Outcome.RETRY       # nothing changed
    assert insp.inspect(blob, dark).outcome is Outcome.RETRY       # too little solder
    assert insp.inspect(dark, white).outcome is Outcome.HUMAN      # excess
