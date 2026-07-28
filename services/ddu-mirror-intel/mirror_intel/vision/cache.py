"""Pre-computed Grounded-SAM-2 + GeoCLIP results keyed by content hash.

Spec rule: heavy models run offline on curated demo photos; demo upload hits
cache instantly. Results disclose ``method`` so the pitch stays honest.
"""

from __future__ import annotations

import hashlib
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger("mirror-intel.vision.cache")

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "vision_cache"
INDEX_PATH = CACHE_DIR / "index.json"

OBJECT_METHOD = "grounded-sam-2 (precomputed cache)"
GEO_METHOD = "geoclip (precomputed cache)"


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@lru_cache(maxsize=1)
def _load_index() -> dict[str, Any]:
    if not INDEX_PATH.is_file():
        log.warning("vision cache index missing at %s", INDEX_PATH)
        return {"version": 1, "entries": {}}
    with INDEX_PATH.open(encoding="utf-8") as fh:
        payload = json.load(fh)
    entries = payload.get("entries") or {}
    # Normalize keys to bare hex (accept sha256: prefix).
    normalized = {}
    for key, value in entries.items():
        bare = key.removeprefix("sha256:")
        normalized[bare] = value
    return {"version": payload.get("version", 1), "entries": normalized}


def lookup(data: bytes) -> dict[str, Any] | None:
    """Return the cache entry for these bytes, or None on miss."""
    digest = content_hash(data)
    entry = _load_index()["entries"].get(digest)
    if entry is None:
        return None
    return {"sha256": digest, **entry}


def lookup_by_hash(digest: str) -> dict[str, Any] | None:
    bare = digest.removeprefix("sha256:")
    entry = _load_index()["entries"].get(bare)
    if entry is None:
        return None
    return {"sha256": bare, **entry}


def list_demo_assets() -> list[dict[str, Any]]:
    """Metadata for the curated demo photos (no binary payloads)."""
    assets: list[dict[str, Any]] = []
    for digest, entry in _load_index()["entries"].items():
        assets.append(
            {
                "sha256": digest,
                "slug": entry.get("slug"),
                "filename": entry.get("filename"),
                "label": entry.get("label"),
                "description": entry.get("description"),
                "platform": entry.get("platform"),
                "has_objects": bool(entry.get("objects")),
                "has_geo": bool(entry.get("geo")),
                "face_boxes": len(entry.get("face_boxes") or []),
            }
        )
    return assets


def demo_image_path(slug: str) -> Path | None:
    for entry in _load_index()["entries"].values():
        if entry.get("slug") == slug and entry.get("filename"):
            path = CACHE_DIR / entry["filename"]
            if path.is_file():
                return path
    return None


def reload_cache() -> None:
    _load_index.cache_clear()
