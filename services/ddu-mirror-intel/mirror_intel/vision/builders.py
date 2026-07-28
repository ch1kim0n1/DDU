"""Build schema-valid Finding objects from EXIF + cache hits."""

from __future__ import annotations

import secrets
from typing import Any

from ..redaction import mint_reveal_token
from ..reversibility import classify
from ..schema import (
    EvidenceItem,
    Finding,
    FindingType,
    Origin,
    VerificationState,
)
from .cache import GEO_METHOD, OBJECT_METHOD
from .exif import METHOD as EXIF_METHOD, ExifResult


def _fid(prefix: str) -> str:
    return f"f_{prefix}_{secrets.token_hex(3)}"


def build_exif_findings(
    *,
    session_id: str,
    subject_ref: str,
    parent_id: str | None,
    hop_depth: int,
    exif: ExifResult,
    platform: str | None = "upload",
) -> tuple[list[Finding], dict[str, str]]:
    findings: list[Finding] = []
    vault: dict[str, str] = {}

    if exif.has_gps and exif.latitude is not None and exif.longitude is not None:
        finding_id = _fid("gps")
        reversible, remediation = classify(FindingType.GPS_EXPOSURE, exif.datetime_original)
        raw_coord = f"{exif.latitude:.6f},{exif.longitude:.6f}"
        token = mint_reveal_token(session_id, finding_id, "lat/lon")
        vault[token] = raw_coord
        evidence = [
            EvidenceItem(
                kind="kv",
                k="lat/lon",
                v="REDACTED",
                reveal_token=token,
                redacted=True,
            )
        ]
        if exif.datetime_original:
            evidence.append(
                EvidenceItem(kind="kv", k="captured_at", v=exif.datetime_original, redacted=False)
            )
        findings.append(
            Finding(
                id=finding_id,
                parent_id=parent_id,
                hop_depth=hop_depth,
                type=FindingType.GPS_EXPOSURE,
                label="Home GPS in uploaded photo",
                detail=(
                    "This image still carries EXIF GPS coordinates. Anyone who "
                    "downloads the original file can recover the capture location."
                ),
                verification_state=VerificationState.CONFIRMED,
                confidence=0.95,
                severity_base=0.9,
                reversible=reversible,
                remediation=remediation,
                platform=platform,
                source="exif:GPSInfo",
                method=EXIF_METHOD,
                evidence=evidence,
                subject_ref=subject_ref,
                origin=Origin.SYSTEM,
            )
        )

    if exif.has_device:
        finding_id = _fid("device")
        reversible, remediation = classify(FindingType.DEVICE_FINGERPRINT, exif.datetime_original)
        device = " ".join(p for p in (exif.make, exif.model) if p)
        token = mint_reveal_token(session_id, finding_id, "device")
        vault[token] = device
        findings.append(
            Finding(
                id=finding_id,
                parent_id=parent_id,
                hop_depth=hop_depth,
                type=FindingType.DEVICE_FINGERPRINT,
                label="Camera make/model in image metadata",
                detail=(
                    "Device fingerprint metadata links uploads across accounts "
                    "even when handles differ."
                ),
                verification_state=VerificationState.CONFIRMED,
                confidence=0.9,
                severity_base=0.45,
                reversible=reversible,
                remediation=remediation,
                platform=platform,
                source="exif:Make/Model",
                method=EXIF_METHOD,
                evidence=[
                    EvidenceItem(
                        kind="kv",
                        k="device",
                        v="REDACTED",
                        reveal_token=token,
                        redacted=True,
                    )
                ],
                subject_ref=subject_ref,
                origin=Origin.SYSTEM,
            )
        )

    return findings, vault


def build_object_findings(
    *,
    session_id: str,
    subject_ref: str,
    parent_id: str | None,
    hop_depth: int,
    objects: list[dict[str, Any]],
    platform: str | None = "upload",
    cache_disclosed: bool = True,
) -> list[Finding]:
    findings: list[Finding] = []
    for obj in objects:
        finding_id = _fid("obj")
        reversible, remediation = classify(FindingType.OBJECT_EXPOSURE)
        label = str(obj.get("label") or "Sensitive object in frame")
        prompt = str(obj.get("prompt") or "object")
        confidence = float(obj.get("confidence", 0.8))
        method = OBJECT_METHOD if cache_disclosed else "grounded-sam-2"
        findings.append(
            Finding(
                id=finding_id,
                parent_id=parent_id,
                hop_depth=hop_depth,
                type=FindingType.OBJECT_EXPOSURE,
                label=label,
                detail=str(
                    obj.get("detail")
                    or f"Text-prompted detection for '{prompt}' matched in the uploaded frame."
                ),
                verification_state=VerificationState.LIKELY,
                confidence=confidence,
                severity_base=float(obj.get("severity_base", 0.75)),
                reversible=reversible,
                remediation=remediation,
                platform=platform,
                source=f"vision:grounded-sam-2:{prompt}",
                method=method,
                evidence=[
                    EvidenceItem(
                        kind="kv",
                        k="prompt",
                        v=prompt,
                        redacted=False,
                    ),
                    EvidenceItem(
                        kind="kv",
                        k="bbox",
                        v=str(obj.get("bbox", "REDACTED")),
                        redacted=False,
                    ),
                ],
                subject_ref=subject_ref,
                origin=Origin.SYSTEM,
            )
        )
    return findings


def build_geo_findings(
    *,
    subject_ref: str,
    parent_id: str | None,
    hop_depth: int,
    geo_candidates: list[dict[str, Any]],
    platform: str | None = "upload",
    cache_disclosed: bool = True,
) -> list[Finding]:
    """Always emit as hypothesis — never confirmed (spec §6.5)."""
    findings: list[Finding] = []
    method = GEO_METHOD if cache_disclosed else "geoclip"
    for candidate in geo_candidates:
        finding_id = _fid("geo")
        reversible, remediation = classify(FindingType.LOCATION_INFERENCE)
        place = str(candidate.get("label") or "Inferred neighbourhood")
        findings.append(
            Finding(
                id=finding_id,
                parent_id=parent_id,
                hop_depth=hop_depth,
                type=FindingType.LOCATION_INFERENCE,
                label=f"Visual geolocation hypothesis: {place}",
                detail=(
                    "GeoCLIP ranked this location from image content alone "
                    "(EXIF may already be stripped by the platform). Always a "
                    "hypothesis — never treated as a confirmed address."
                ),
                verification_state=VerificationState.HYPOTHESIS,
                confidence=float(candidate.get("confidence", 0.55)),
                severity_base=float(candidate.get("severity_base", 0.7)),
                reversible=reversible,
                remediation=remediation,
                platform=platform,
                source="vision:geoclip",
                method=method,
                evidence=[
                    EvidenceItem(
                        kind="kv",
                        k="hypothesis",
                        v=place,
                        redacted=False,
                    ),
                    EvidenceItem(
                        kind="kv",
                        k="rank",
                        v=str(candidate.get("rank", 1)),
                        redacted=False,
                    ),
                ],
                subject_ref=subject_ref,
                origin=Origin.SYSTEM,
            )
        )
    return findings


def build_face_link_finding(
    *,
    session_id: str,
    subject_ref: str,
    parent_id: str | None,
    hop_depth: int,
    account_label: str,
    similarity: float,
    platform: str | None,
) -> tuple[Finding, dict[str, str]]:
    finding_id = _fid("face")
    reversible, remediation = classify(FindingType.FACE_LINK)
    token = mint_reveal_token(session_id, finding_id, "matched_account")
    vault = {token: account_label}
    finding = Finding(
        id=finding_id,
        parent_id=parent_id,
        hop_depth=hop_depth,
        type=FindingType.FACE_LINK,
        label=f"Same face as verified account avatar ({account_label})",
        detail=(
            "Closed-corpus face match against verified-account avatars and "
            "your uploads only — no open-web face search."
        ),
        verification_state=VerificationState.LIKELY,
        confidence=min(0.99, max(0.5, similarity)),
        severity_base=0.8,
        reversible=reversible,
        remediation=remediation,
        platform=platform,
        source="face:compreface:closed_corpus",
        method="compreface closed-corpus match",
        evidence=[
            EvidenceItem(
                kind="kv",
                k="matched_account",
                v="REDACTED",
                reveal_token=token,
                redacted=True,
            ),
            EvidenceItem(
                kind="kv",
                k="similarity",
                v=f"{similarity:.2f}",
                redacted=False,
            ),
        ],
        subject_ref=subject_ref,
        origin=Origin.SYSTEM,
    )
    return finding, vault
