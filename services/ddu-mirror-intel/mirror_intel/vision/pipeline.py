"""Photo analyze pipeline — EXIF + hash cache → findings."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..session import SEED_FINDING_ID, Session
from . import builders
from .cache import content_hash, lookup
from .exif import extract_exif
from .face import redaction_preview


@dataclass
class VisionAnalyzeResult:
    sha256: str
    cache_hit: bool
    elapsed_ms: float
    findings: list[Any] = field(default_factory=list)
    raw_values: dict[str, str] = field(default_factory=dict)
    redaction_preview: dict[str, Any] = field(default_factory=dict)
    disclosures: list[str] = field(default_factory=list)
    exif_summary: dict[str, Any] = field(default_factory=dict)


def analyze_upload(
    session: Session,
    data: bytes,
    *,
    filename: str | None = None,
    parent_id: str | None = None,
    hop_depth: int = 1,
    platform: str | None = "upload",
) -> VisionAnalyzeResult:
    """Run the Engineer C photo path.

    Cache hits for Grounded-SAM-2 / GeoCLIP are disclosed in ``method`` and
    ``disclosures``. EXIF is always extracted live from the bytes.
    """
    started = time.perf_counter()
    digest = content_hash(data)
    parent = parent_id or SEED_FINDING_ID
    subject = session.identity.subject_ref

    exif = extract_exif(data)
    findings, vault = builders.build_exif_findings(
        session_id=session.session_id,
        subject_ref=subject,
        parent_id=parent,
        hop_depth=hop_depth,
        exif=exif,
        platform=platform,
    )

    cached = lookup(data)
    disclosures: list[str] = []
    cache_hit = cached is not None

    if cached:
        disclosures.append(
            "Object and geo results served from pre-computed cache keyed by "
            f"sha256:{digest[:12]}… — Grounded-SAM-2 / GeoCLIP were not run live."
        )
        objects = list(cached.get("objects") or [])
        findings.extend(
            builders.build_object_findings(
                session_id=session.session_id,
                subject_ref=subject,
                parent_id=parent,
                hop_depth=hop_depth,
                objects=objects,
                platform=platform or cached.get("platform") or "upload",
                cache_disclosed=True,
            )
        )
        geo = list(cached.get("geo") or [])
        findings.extend(
            builders.build_geo_findings(
                subject_ref=subject,
                parent_id=parent,
                hop_depth=hop_depth,
                geo_candidates=geo,
                platform=platform or cached.get("platform") or "upload",
                cache_disclosed=True,
            )
        )
    else:
        disclosures.append(
            "No pre-computed vision cache entry for this file hash. "
            "EXIF was still extracted; object/geo models were not run live "
            "(demo path is cache-only)."
        )

    preview = redaction_preview(data)
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    return VisionAnalyzeResult(
        sha256=digest,
        cache_hit=cache_hit,
        elapsed_ms=round(elapsed_ms, 2),
        findings=findings,
        raw_values=vault,
        redaction_preview=preview,
        disclosures=disclosures,
        exif_summary={
            "has_gps": exif.has_gps,
            "has_device": exif.has_device,
            "datetime_original": exif.datetime_original,
            "filename": filename,
        },
    )
