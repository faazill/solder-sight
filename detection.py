"""Solder-joint detection backends. Currently: Gemini (cloud)."""

from __future__ import annotations

import json
import os
import re

DEFAULT_PROMPT = (
    "Point to every solder joint on this PCB image. A solder joint is the "
    "shiny or matte metal fillet where a component lead or pin meets a pad, "
    "including through-hole pins and soldered SMD pads. Place each point at "
    "the center of the joint. Do not point to bare unsoldered pads, vias, "
    "silkscreen text, or component bodies."
)


def resolve_api_key(typed: str | None = None, secret: str | None = None):
    if typed and typed.strip():
        return typed.strip()
    return secret or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def parse_points(text: str, width: int, height: int, max_points: int):
    """Parse Gemini's JSON ([y, x] normalised 0-1000) into (x, y) pixels."""
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.MULTILINE).strip()
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("points") or data.get("items") or []
    points = []
    for item in data:
        p = item.get("point") if isinstance(item, dict) else item
        if not (isinstance(p, (list, tuple)) and len(p) == 2):
            continue
        y, x = float(p[0]), float(p[1])
        if 0 <= x <= 1000 and 0 <= y <= 1000:
            points.append((x / 1000 * width, y / 1000 * height))
    return points[:max_points]


def detect_joints(crop, api_key: str, model: str, prompt: str, max_points: int):
    """Ask Gemini for solder-joint points. Returns (x, y) in crop pixels."""
    from google import genai
    from google.genai import types

    img = crop.copy()
    img.thumbnail((1600, 1600))
    full_prompt = (
        f"{prompt}\n\nReturn at most {max_points} points. Answer ONLY with a "
        'JSON list like [{"point": [y, x], "label": "short name"}] where y and '
        "x are normalized to the range 0-1000 relative to this image."
    )
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=[img, full_prompt],
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1),
    )
    return parse_points(response.text, crop.width, crop.height, max_points)
