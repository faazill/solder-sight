"""Joint quality inspection. Swap in a trained model by implementing `Inspector`."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import cv2
import numpy as np

from config import InspectionCfg


class Outcome(StrEnum):
    GOOD = "good"      # accept, go to the next joint
    RETRY = "retry"    # another soldering pass can fix this (e.g. too little solder)
    HUMAN = "human"    # do NOT re-solder (excess, bridge) or retries exhausted


@dataclass
class InspectionResult:
    outcome: Outcome
    score: float
    reason: str


class Inspector(Protocol):
    def inspect(self, before, after) -> InspectionResult: ...


class HeuristicInspector:
    """Baseline using shiny-pixel coverage. A PLACEHOLDER: tune the thresholds on your
    own photos, then replace with a trained classifier once you have labelled data."""

    def __init__(self, cfg: InspectionCfg):
        self.cfg = cfg

    def inspect(self, before, after) -> InspectionResult:
        c = self.cfg
        if before is not None and before.shape == after.shape:
            diff = cv2.absdiff(cv2.cvtColor(before, cv2.COLOR_BGR2GRAY),
                               cv2.cvtColor(after, cv2.COLOR_BGR2GRAY))
            change = float(np.mean(diff))
            if change < c.min_change:
                return InspectionResult(Outcome.RETRY, change, f"no visible change ({change:.1f})")

        hsv = cv2.cvtColor(after, cv2.COLOR_BGR2HSV)
        h, w = hsv.shape[:2]
        yy, xx = np.ogrid[:h, :w]
        mask = ((xx - w / 2) ** 2 + (yy - h / 2) ** 2) <= (min(h, w) * 0.45) ** 2
        shiny = (hsv[..., 2] >= c.bright_v) & (hsv[..., 1] <= c.max_sat) & mask
        ratio = float(shiny.sum() / max(1, mask.sum()))

        if ratio < c.solder_ratio_min:
            return InspectionResult(Outcome.RETRY, ratio, f"too little solder (coverage {ratio:.2f})")
        if ratio > c.solder_ratio_max:
            return InspectionResult(Outcome.HUMAN, ratio, f"excess solder or bridge (coverage {ratio:.2f})")
        return InspectionResult(Outcome.GOOD, ratio, f"coverage {ratio:.2f}")
