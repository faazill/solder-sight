"""Coordinate maths. Origin = bottom-left of the reference box, X right, Y up."""

from __future__ import annotations

Box = tuple[float, float, float, float]  # x1, y1, x2, y2 in image pixels (y down)


def px_to_mm(point, box: Box, width_mm: float, height_mm: float):
    x1, y1, x2, y2 = box
    return (
        (point[0] - x1) / (x2 - x1) * width_mm,
        (y2 - point[1]) / (y2 - y1) * height_mm,
    )


def mm_to_px(point_mm, box: Box, width_mm: float, height_mm: float):
    x1, y1, x2, y2 = box
    return (
        x1 + point_mm[0] / width_mm * (x2 - x1),
        y2 - point_mm[1] / height_mm * (y2 - y1),
    )


def crop_window(cx: float, cy: float, size: int, img_w: int, img_h: int):
    """Square window of `size` px around (cx, cy), shifted to stay inside the image."""
    size = max(8, min(int(size), img_w, img_h))
    left = min(max(int(round(cx - size / 2)), 0), img_w - size)
    top = min(max(int(round(cy - size / 2)), 0), img_h - size)
    return left, top, left + size, top + size


def merge_points(existing, new, min_dist: float = 8.0):
    """Add new points, skipping any within min_dist px of an existing one."""
    merged = list(existing)
    added = 0
    for p in new:
        if all((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 >= min_dist**2 for q in merged):
            merged.append(p)
            added += 1
    return merged, added


def order_points(points, start):
    """Greedy nearest-neighbour order starting from `start`."""
    remaining, ordered, cur = list(points), [], start
    while remaining:
        nxt = min(remaining, key=lambda p: (p[0] - cur[0]) ** 2 + (p[1] - cur[1]) ** 2)
        ordered.append(nxt)
        remaining.remove(nxt)
        cur = nxt
    return ordered
