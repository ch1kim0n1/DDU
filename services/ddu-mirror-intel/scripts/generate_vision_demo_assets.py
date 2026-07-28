"""Generate curated demo JPEGs with GPS EXIF + vision_cache index."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import piexif
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "mirror_intel" / "data" / "vision_cache"
OUT.mkdir(parents=True, exist_ok=True)

DEMOS = [
    {
        "slug": "vacation_plate",
        "filename": "demo_vacation_plate.jpg",
        "label": "Vacation driveway photo",
        "description": "Residential GPS + visible license plate — the visceral EXIF + object hit.",
        "lat": 30.2672,
        "lon": -97.7431,
        "make": "Apple",
        "model": "iPhone 14 Pro",
        "datetime": "2026-06-12 18:42:11",
        "color": (42, 78, 110),
        "overlay": "DRIVEWAY / TX PLATE",
        "objects": [
            {
                "prompt": "license plate",
                "label": "License plate visible in vacation photo",
                "detail": "Grounded-SAM-2 text prompt 'license plate' matched a rear plate in frame.",
                "confidence": 0.91,
                "severity_base": 0.85,
                "bbox": [0.62, 0.71, 0.18, 0.08],
            },
            {
                "prompt": "house number",
                "label": "House number readable on facade",
                "detail": "Street-facing house number is legible at full resolution.",
                "confidence": 0.84,
                "severity_base": 0.7,
                "bbox": [0.22, 0.38, 0.12, 0.06],
            },
        ],
        "geo": [
            {
                "rank": 1,
                "label": "Central East Austin residential block",
                "confidence": 0.61,
                "severity_base": 0.72,
            },
            {
                "rank": 2,
                "label": "South Congress corridor (Austin, TX)",
                "confidence": 0.44,
                "severity_base": 0.55,
            },
        ],
        "face_boxes": [{"x": 0.40, "y": 0.18, "w": 0.16, "h": 0.20, "confidence": 0.93}],
        "platform": "instagram",
    },
    {
        "slug": "badge_selfie",
        "filename": "demo_badge_selfie.jpg",
        "label": "Office badge selfie",
        "description": "Workplace GPS + employee badge object exposure.",
        "lat": 37.7749,
        "lon": -122.4194,
        "make": "Google",
        "model": "Pixel 8",
        "datetime": "2026-05-03 09:15:02",
        "color": (68, 52, 48),
        "overlay": "BADGE / LOBBY",
        "objects": [
            {
                "prompt": "badge",
                "label": "Employee badge readable in selfie",
                "detail": "Text-prompt detection for 'badge' matched an ID card in the lower frame.",
                "confidence": 0.88,
                "severity_base": 0.8,
                "bbox": [0.55, 0.62, 0.22, 0.18],
            }
        ],
        "geo": [
            {
                "rank": 1,
                "label": "SoMa office cluster, San Francisco",
                "confidence": 0.58,
                "severity_base": 0.68,
            }
        ],
        "face_boxes": [
            {"x": 0.35, "y": 0.12, "w": 0.28, "h": 0.34, "confidence": 0.97},
            {"x": 0.70, "y": 0.40, "w": 0.12, "h": 0.14, "confidence": 0.71},
        ],
        "platform": "linkedin",
    },
    {
        "slug": "stripped_street",
        "filename": "demo_stripped_street.jpg",
        "label": "EXIF-stripped street scene",
        "description": "No GPS in file — GeoCLIP hypotheses still fire (platform-stripped complement).",
        "lat": None,
        "lon": None,
        "make": None,
        "model": None,
        "datetime": None,
        "color": (30, 90, 70),
        "overlay": "NO EXIF / STREET SIGN",
        "objects": [
            {
                "prompt": "street sign",
                "label": "Street sign text visible",
                "detail": "Signage narrows the block even without metadata.",
                "confidence": 0.86,
                "severity_base": 0.65,
                "bbox": [0.48, 0.20, 0.25, 0.12],
            }
        ],
        "geo": [
            {
                "rank": 1,
                "label": "Brooklyn brownstone streetscape",
                "confidence": 0.57,
                "severity_base": 0.7,
            },
            {
                "rank": 2,
                "label": "Park Slope / Prospect Heights area",
                "confidence": 0.41,
                "severity_base": 0.55,
            },
        ],
        "face_boxes": [],
        "platform": "x",
        "strip_exif": True,
    },
    {
        "slug": "home_backyard",
        "filename": "demo_home_backyard.jpg",
        "label": "Backyard evening photo",
        "description": "Home GPS + mailbox object — stalker-persona critical.",
        "lat": 33.4484,
        "lon": -112.0740,
        "make": "samsung",
        "model": "SM-S918U",
        "datetime": "2026-04-19 19:05:44",
        "color": (55, 40, 70),
        "overlay": "BACKYARD / HOME",
        "objects": [
            {
                "prompt": "mailbox",
                "label": "Residential mailbox in frame",
                "detail": "Property-adjacent objects help confirm a home address when combined with GPS.",
                "confidence": 0.8,
                "severity_base": 0.7,
                "bbox": [0.10, 0.55, 0.15, 0.2],
            }
        ],
        "geo": [
            {
                "rank": 1,
                "label": "Central Phoenix residential tract",
                "confidence": 0.52,
                "severity_base": 0.75,
            }
        ],
        "face_boxes": [{"x": 0.60, "y": 0.25, "w": 0.14, "h": 0.18, "confidence": 0.9}],
        "platform": "facebook",
    },
]


def _deg_to_dms_rational(deg: float):
    sign = 1 if deg >= 0 else -1
    deg = abs(deg)
    d = int(deg)
    m_float = (deg - d) * 60
    m = int(m_float)
    s = round((m_float - m) * 60 * 10000)
    return ((d, 1), (m, 1), (s, 10000)), sign


def write_demo(spec: dict) -> tuple[str, dict]:
    img = Image.new("RGB", (960, 640), spec["color"])
    draw = ImageDraw.Draw(img)
    draw.rectangle((40, 40, 920, 600), outline=(240, 240, 240), width=3)
    draw.text((60, 60), spec["overlay"], fill=(245, 245, 245))
    draw.text((60, 110), spec["label"], fill=(220, 220, 220))
    if "PLATE" in spec["overlay"]:
        draw.rectangle((580, 460, 820, 530), fill=(240, 240, 240))
        draw.text((600, 480), "TX · 7ABC123", fill=(20, 20, 20))
    if "BADGE" in spec["overlay"]:
        draw.rectangle((520, 380, 760, 560), fill=(230, 230, 200))
        draw.text((540, 420), "EMPLOYEE", fill=(30, 30, 30))
        draw.text((540, 460), "ID 48219", fill=(30, 30, 30))

    path = OUT / spec["filename"]
    if spec.get("strip_exif") or spec["lat"] is None:
        img.save(path, format="JPEG", quality=90)
    else:
        lat_dms, lat_sign = _deg_to_dms_rational(spec["lat"])
        lon_dms, lon_sign = _deg_to_dms_rational(spec["lon"])
        gps_ifd = {
            piexif.GPSIFD.GPSLatitudeRef: b"N" if lat_sign >= 0 else b"S",
            piexif.GPSIFD.GPSLatitude: lat_dms,
            piexif.GPSIFD.GPSLongitudeRef: b"E" if lon_sign >= 0 else b"W",
            piexif.GPSIFD.GPSLongitude: lon_dms,
        }
        zeroth = {
            piexif.ImageIFD.Make: (spec["make"] or "").encode(),
            piexif.ImageIFD.Model: (spec["model"] or "").encode(),
            piexif.ImageIFD.DateTime: (spec["datetime"] or "").encode(),
        }
        exif_ifd = {}
        if spec.get("datetime"):
            exif_ifd[piexif.ExifIFD.DateTimeOriginal] = spec["datetime"].encode()
        exif_bytes = piexif.dump({"0th": zeroth, "Exif": exif_ifd, "GPS": gps_ifd})
        img.save(path, format="JPEG", quality=90, exif=exif_bytes)

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    entry = {
        "slug": spec["slug"],
        "filename": spec["filename"],
        "label": spec["label"],
        "description": spec["description"],
        "platform": spec["platform"],
        "objects": spec["objects"],
        "geo": spec["geo"],
        "face_boxes": spec["face_boxes"],
        "notes": "Pre-computed offline. Demo upload must hit this hash.",
    }
    return digest, entry


def main() -> None:
    entries = {}
    for demo in DEMOS:
        digest, entry = write_demo(demo)
        entries[digest] = entry
        print(demo["slug"], digest[:16], entry["filename"])

    index = {
        "version": 1,
        "description": (
            "Engineer C pre-computed Grounded-SAM-2 + GeoCLIP results keyed by "
            "sha256 of curated demo JPEGs. Disclose on stage."
        ),
        "entries": entries,
    }
    (OUT / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    print("wrote", OUT / "index.json", "entries", len(entries))


if __name__ == "__main__":
    main()
