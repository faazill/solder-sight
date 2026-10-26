"""The job file: the contract between the planning UI and the machine runner."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class JobPoint:
    id: int
    x_mm: float
    y_mm: float


@dataclass
class Job:
    width_mm: float
    height_mm: float
    box_px: tuple[float, float, float, float]  # reference box in the camera image
    points: list[JobPoint]

    def validate(self) -> None:
        if self.width_mm <= 0 or self.height_mm <= 0:
            raise ValueError("Box width and height must be positive.")
        x1, y1, x2, y2 = self.box_px
        if x2 <= x1 or y2 <= y1:
            raise ValueError("box_px must be (x1, y1, x2, y2) with x2 > x1 and y2 > y1.")
        if not self.points:
            raise ValueError("The job has no points.")
        for p in self.points:
            if not (-1e-6 <= p.x_mm <= self.width_mm + 1e-6 and -1e-6 <= p.y_mm <= self.height_mm + 1e-6):
                raise ValueError(f"Point {p.id} ({p.x_mm}, {p.y_mm}) is outside the reference box.")

    @classmethod
    def from_points(cls, points_mm, width_mm, height_mm, box_px):
        pts = [JobPoint(i, round(x, 3), round(y, 3)) for i, (x, y) in enumerate(points_mm, 1)]
        job = cls(float(width_mm), float(height_mm), tuple(float(v) for v in box_px), pts)
        job.validate()
        return job

    def to_json(self) -> str:
        return json.dumps(
            {
                "version": 1,
                "units": "mm",
                "origin": "bottom-left of reference box, X right, Y up",
                "box_mm": {"width": self.width_mm, "height": self.height_mm},
                "box_px": list(self.box_px),
                "points": [{"id": p.id, "x_mm": p.x_mm, "y_mm": p.y_mm} for p in self.points],
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, text: str):
        d = json.loads(text)
        job = cls(
            float(d["box_mm"]["width"]),
            float(d["box_mm"]["height"]),
            tuple(float(v) for v in d["box_px"]),
            [JobPoint(int(p["id"]), float(p["x_mm"]), float(p["y_mm"])) for p in d["points"]],
        )
        job.validate()
        return job

    def save(self, path) -> None:
        Path(path).write_text(self.to_json())

    @classmethod
    def load(cls, path):
        return cls.from_json(Path(path).read_text())
