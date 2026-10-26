"""Camera sources."""

from __future__ import annotations

import cv2


class Camera:
    def __init__(self, index: int = 0, flush: int = 4):
        self.cap = cv2.VideoCapture(index)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open camera {index}")
        self.flush = flush

    def capture(self):
        for _ in range(self.flush):  # discard stale buffered frames
            self.cap.read()
        ok, frame = self.cap.read()
        if not ok:
            raise RuntimeError("Camera returned no frame")
        return frame

    def release(self) -> None:
        self.cap.release()


class StaticImageCamera:
    """Returns the same image every time. Useful for dry runs and tests."""

    def __init__(self, path: str):
        self.frame = cv2.imread(path)
        if self.frame is None:
            raise RuntimeError(f"Could not read image {path}")

    def capture(self):
        return self.frame.copy()

    def release(self) -> None:
        pass
