"""Face detection / redaction preview + optional CompreFace bridge.

Closed-corpus matching lives in ``corpus.py``. This module adds:
- redaction preview boxes (cache-first, then stub / live detect)
- optional HTTP client for CompreFace when configured
"""

from __future__ import annotations

import logging
import os
from typing import Any

from .cache import lookup

log = logging.getLogger("mirror-intel.vision.face")

COMPREFACE_URL = os.environ.get("COMPREFACE_URL", "").rstrip("/")
COMPREFACE_API_KEY = os.environ.get("COMPREFACE_API_KEY", "")


def redaction_preview(data: bytes) -> dict[str, Any]:
    """Return face boxes for 'blur before posting' UI.

    Cache hit preferred (demo photos). Otherwise a conservative stub that
    reports zero faces rather than inventing third-party faces (Rule 2).
    """
    cached = lookup(data)
    if cached and cached.get("face_boxes") is not None:
        boxes = list(cached["face_boxes"])
        return {
            "face_count": len(boxes),
            "boxes": boxes,
            "source": "vision_cache",
            "advice": (
                f"{len(boxes)} face(s) detected — blur or crop before posting."
                if boxes
                else "No faces detected in this frame."
            ),
            "method": "cache:face_boxes",
        }

    live = _compreface_detect(data)
    if live is not None:
        return live

    return {
        "face_count": 0,
        "boxes": [],
        "source": "stub",
        "advice": (
            "No live face detector configured. Demo photos with cached boxes "
            "still produce a redaction preview."
        ),
        "method": "stub:no-detector",
    }


def _compreface_detect(data: bytes) -> dict[str, Any] | None:
    if not COMPREFACE_URL or not COMPREFACE_API_KEY:
        return None
    try:
        import httpx
    except ImportError:
        return None
    try:
        response = httpx.post(
            f"{COMPREFACE_URL}/api/v1/detection/detect",
            headers={"x-api-key": COMPREFACE_API_KEY},
            files={"file": ("probe.jpg", data, "application/octet-stream")},
            timeout=5.0,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("CompreFace detect failed: %s", exc)
        return None

    boxes = []
    for result in payload.get("result") or []:
        box = result.get("box") or {}
        boxes.append(
            {
                "x": box.get("x_min", 0),
                "y": box.get("y_min", 0),
                "w": max(0, (box.get("x_max", 0) - box.get("x_min", 0))),
                "h": max(0, (box.get("y_max", 0) - box.get("y_min", 0))),
                "confidence": result.get("box", {}).get("probability")
                or result.get("probability")
                or 0.0,
            }
        )
    return {
        "face_count": len(boxes),
        "boxes": boxes,
        "source": "compreface",
        "advice": (
            f"{len(boxes)} face(s) detected — blur or crop before posting."
            if boxes
            else "No faces detected in this frame."
        ),
        "method": "compreface:detect",
    }
