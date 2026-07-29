"""EXIF extraction — GPS, device, timestamp.

Best ROI in the build (spec §6.5). Uses exifread when available, with a
Pillow fallback so CPU-only CI still works. Raw coordinates never leave
this module as display text — callers mint reveal tokens.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("mirror-intel.vision.exif")

METHOD = "exifread v3.0"


@dataclass(frozen=True)
class ExifResult:
    latitude: float | None = None
    longitude: float | None = None
    altitude_m: float | None = None
    make: str | None = None
    model: str | None = None
    datetime_original: str | None = None
    has_gps: bool = False
    has_device: bool = False
    raw_tags: dict[str, str] | None = None


def _ratio_to_float(value: Any) -> float | None:
    try:
        if hasattr(value, "num") and hasattr(value, "den"):
            den = float(value.den) or 1.0
            return float(value.num) / den
        if isinstance(value, tuple) and len(value) == 2:
            den = float(value[1]) or 1.0
            return float(value[0]) / den
        if isinstance(value, (list, tuple)) and value:
            # DMS: ((d_num,d_den),(m_num,m_den),(s_num,s_den))
            parts: list[float] = []
            for part in value:
                converted = _ratio_to_float(part)
                if converted is None:
                    return None
                parts.append(converted)
            if len(parts) >= 3:
                return parts[0] + parts[1] / 60.0 + parts[2] / 3600.0
            return parts[0]
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _dms_to_decimal(values: Any, ref: str | None) -> float | None:
    decimal = _ratio_to_float(values)
    if decimal is None:
        return None
    ref_s = str(ref or "").upper()
    if ref_s in {"S", "W"}:
        decimal = -abs(decimal)
    return decimal


def _tag_values(tag: Any) -> Any:
    """Unwrap exifread IfdTag / Pillow values to something ``_ratio_to_float`` can read."""
    if tag is None:
        return None
    if hasattr(tag, "values"):
        return tag.values
    return tag


def _tag_ref(tag: Any) -> str | None:
    if tag is None:
        return None
    if hasattr(tag, "printable"):
        return str(tag.printable).strip()
    return str(tag).strip()


def extract_exif(data: bytes) -> ExifResult:
    """Parse EXIF from raw image bytes. Never raises on malformed metadata."""
    try:
        import exifread  # type: ignore
    except ImportError:
        return _extract_with_pillow(data)

    try:
        tags = exifread.process_file(io.BytesIO(data), details=False)
    except Exception as exc:  # noqa: BLE001 — corrupt EXIF must not crash ingest
        log.warning("exifread failed: %s", exc)
        return _extract_with_pillow(data)

    lat = _dms_to_decimal(
        _tag_values(tags.get("GPS GPSLatitude")),
        _tag_ref(tags.get("GPS GPSLatitudeRef")),
    )
    lon = _dms_to_decimal(
        _tag_values(tags.get("GPS GPSLongitude")),
        _tag_ref(tags.get("GPS GPSLongitudeRef")),
    )
    alt_tag = tags.get("GPS GPSAltitude")
    alt = _ratio_to_float(_tag_values(alt_tag)[0] if hasattr(alt_tag, "values") else alt_tag) if alt_tag else None
    make = _tag_ref(tags.get("Image Make"))
    model = _tag_ref(tags.get("Image Model"))
    dt = None
    for key in ("EXIF DateTimeOriginal", "Image DateTime"):
        if key in tags:
            dt = _tag_ref(tags[key])
            break

    return ExifResult(
        latitude=lat,
        longitude=lon,
        altitude_m=alt,
        make=make or None,
        model=model or None,
        datetime_original=dt,
        has_gps=lat is not None and lon is not None,
        has_device=bool(make or model),
        raw_tags={k: str(v) for k, v in list(tags.items())[:40]},
    )


def _extract_with_pillow(data: bytes) -> ExifResult:
    try:
        from PIL import Image
        from PIL.ExifTags import GPSTAGS, TAGS
    except ImportError:
        return ExifResult()

    try:
        image = Image.open(io.BytesIO(data))
        exif = image.getexif()
        if not exif:
            return ExifResult()
    except Exception as exc:  # noqa: BLE001
        log.warning("Pillow EXIF failed: %s", exc)
        return ExifResult()

    tagged = {TAGS.get(k, k): v for k, v in exif.items()}
    make = tagged.get("Make")
    model = tagged.get("Model")
    dt = tagged.get("DateTimeOriginal") or tagged.get("DateTime")

    gps_ifd = {}
    try:
        raw_gps = exif.get_ifd(0x8825)
        gps_ifd = {GPSTAGS.get(k, k): v for k, v in raw_gps.items()}
    except Exception:  # noqa: BLE001
        gps_ifd = {}

    lat = _dms_to_decimal(gps_ifd.get("GPSLatitude"), gps_ifd.get("GPSLatitudeRef"))
    lon = _dms_to_decimal(gps_ifd.get("GPSLongitude"), gps_ifd.get("GPSLongitudeRef"))
    alt = _ratio_to_float(gps_ifd.get("GPSAltitude")) if gps_ifd.get("GPSAltitude") else None

    return ExifResult(
        latitude=lat,
        longitude=lon,
        altitude_m=alt,
        make=str(make).strip() if make else None,
        model=str(model).strip() if model else None,
        datetime_original=str(dt).strip() if dt else None,
        has_gps=lat is not None and lon is not None,
        has_device=bool(make or model),
    )
