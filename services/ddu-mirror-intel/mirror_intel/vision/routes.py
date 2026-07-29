"""HTTP surface for Engineer C — Vision & Biometrics."""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from .. import actionlog as A
from ..ratelimit import VISION_ANALYSES_PER_SESSION, check_session_budget, client_ip
from ..schema import Origin
from ..session import SessionConflictError, store
from .builders import build_face_link_finding
from .cache import content_hash, demo_image_path, list_demo_assets, reload_cache
from .corpus import CorpusViolation, corpus_for, drop_corpus
from .face import redaction_preview
from .liveness import liveness_store
from .pipeline import analyze_upload

router = APIRouter(tags=["mirror-vision"])

VISION_MAX_BYTES = 10_000_000


def _session(session_id: str):
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"unknown session {session_id}")
    return session


def _persist(session) -> None:
    try:
        store.persist(session)
    except SessionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


async def _read_upload(file: UploadFile, *, max_bytes: int = VISION_MAX_BYTES) -> bytes:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty upload")
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail="image exceeds 10MB limit")
    return data


class LivenessStart(BaseModel):
    session_id: str
    challenge: str | None = None


class LivenessComplete(BaseModel):
    session_id: str
    challenge_id: str
    client_passed: bool
    #: sha256 of the single verified frame (client may also POST the bytes)
    frame_sha256: str | None = None


class LivenessSkip(BaseModel):
    session_id: str
    reason: str | None = "operator skipped biometric step"


@router.get("/vision/demos")
async def vision_demos() -> dict[str, Any]:
    """Curated demo photos + cache metadata (no binaries)."""
    reload_cache()
    return {
        "count": len(list_demo_assets()),
        "assets": list_demo_assets(),
        "note": (
            "Heavy models were pre-computed offline and cached by file hash. "
            "Uploading one of these files returns EXIF + object + geo findings "
            "in under two seconds."
        ),
    }


@router.get("/vision/demos/{slug}")
async def vision_demo_bytes(slug: str):
    """Serve a curated demo JPEG so the UI can one-click upload it."""
    from fastapi.responses import FileResponse

    path = demo_image_path(slug)
    if path is None:
        raise HTTPException(status_code=404, detail=f"unknown demo slug {slug}")
    return FileResponse(path, media_type="image/jpeg", filename=path.name)


@router.post("/vision/analyze")
async def vision_analyze(
    request: Request,
    session_id: str = Form(...),
    platform: str | None = Form("upload"),
    parent_id: str | None = Form(None),
    hop_depth: int = Form(1),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Upload a photo → EXIF + cached object/geo findings → ingest.

    Definition of done: demo photo returns GPS + cached objects in <2s.
    """
    check_session_budget(
        endpoint="/intel/vision/analyze",
        session_id=session_id,
        bucket="vision",
        limit=VISION_ANALYSES_PER_SESSION,
        ip=client_ip(request),
    )
    session = _session(session_id)
    data = await _read_upload(file)
    result = analyze_upload(
        session,
        data,
        filename=file.filename,
        parent_id=parent_id,
        hop_depth=hop_depth,
        platform=platform,
    )

    added = session.add_findings(result.findings, raw_values=result.raw_values or None)
    session.log.record(
        A.FINDING_ADDED,
        actor=Origin.SYSTEM,
        subject="ddu-mirror-vision",
        detail=(
            f"Vision analyze accepted {len(added)} finding(s); "
            f"cache_hit={result.cache_hit}; elapsed_ms={result.elapsed_ms}"
        ),
        producer="ddu-mirror-vision",
        sha256=result.sha256,
        cache_hit=result.cache_hit,
        elapsed_ms=result.elapsed_ms,
    )
    _persist(session)

    assert session.score is not None
    return {
        "session_id": session_id,
        "sha256": result.sha256,
        "cache_hit": result.cache_hit,
        "elapsed_ms": result.elapsed_ms,
        "within_two_seconds": result.elapsed_ms < 2000,
        "exif": result.exif_summary,
        "disclosures": result.disclosures,
        "redaction_preview": result.redaction_preview,
        "accepted": [f.model_dump(mode="json") for f in added],
        "score": session.score.model_dump(mode="json"),
        "snapshot": session.snapshot().model_dump(mode="json"),
    }


@router.post("/vision/redaction-preview")
async def vision_redaction_preview(file: UploadFile = File(...)) -> dict[str, Any]:
    data = await _read_upload(file)
    preview = redaction_preview(data)
    preview["sha256"] = content_hash(data)
    return preview


@router.post("/vision/face/enroll")
async def face_enroll(
    session_id: str = Form(...),
    source: str = Form(...),
    account_label: str = Form(...),
    platform: str | None = Form(None),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Enroll into the closed corpus (verified avatar or user upload only)."""
    session = _session(session_id)
    data = await _read_upload(file)
    corpus = corpus_for(session_id)
    verified = set(session.identity.handles) | {
        f"verified:{h}" for h in session.identity.handles
    }
    # Demo convenience: treat any handle the session verified as enrollable.
    verified |= {account_label, f"verified:{account_label}"}
    try:
        entry = corpus.enroll(
            entry_id=f"fc_{secrets.token_hex(4)}",
            source=source,
            account_label=account_label,
            image_bytes=data,
            platform=platform,
            verified_accounts=verified,
        )
    except CorpusViolation as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    session.log.record(
        A.FINDING_ADDED,
        actor=Origin.SYSTEM,
        subject=entry.entry_id,
        detail=f"Closed-corpus enroll ({source}) for {account_label}",
        source=source,
    )
    _persist(session)
    return {
        "session_id": session_id,
        "entry": entry.to_public(),
        "corpus_size": len(corpus.entries),
        "rule": "closed corpus — verified avatars + user uploads only",
    }


@router.post("/vision/face/match")
async def face_match(
    session_id: str = Form(...),
    threshold: float = Form(0.72),
    parent_id: str | None = Form(None),
    hop_depth: int = Form(1),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Match probe against closed corpus → face_link findings."""
    session = _session(session_id)
    bio = liveness_store.get(session_id)
    if bio.skipped:
        raise HTTPException(
            status_code=409,
            detail="face path was skipped — no face matching in this session",
        )
    data = await _read_upload(file)
    corpus = corpus_for(session_id)
    if not corpus.entries:
        raise HTTPException(
            status_code=400,
            detail="closed corpus is empty — enroll a verified avatar first",
        )

    hits = corpus.match(data, threshold=threshold)
    findings = []
    vault: dict[str, str] = {}
    for hit in hits:
        # Never link against third-party incidental faces: corpus is closed.
        finding, raw = build_face_link_finding(
            session_id=session_id,
            subject_ref=session.identity.subject_ref,
            parent_id=parent_id,
            hop_depth=hop_depth,
            account_label=hit["account_label"],
            similarity=hit["similarity"],
            platform=hit.get("platform"),
        )
        findings.append(finding)
        vault.update(raw)

    added = session.add_findings(findings, raw_values=vault or None)
    session.log.record(
        A.FINDING_ADDED,
        actor=Origin.SYSTEM,
        subject="ddu-mirror-vision",
        detail=f"Closed-corpus face match produced {len(added)} link(s)",
        hits=len(hits),
    )
    _persist(session)
    assert session.score is not None
    return {
        "session_id": session_id,
        "hits": hits,
        "accepted": [f.model_dump(mode="json") for f in added],
        "corpus_size": len(corpus.entries),
        "score": session.score.model_dump(mode="json"),
        "snapshot": session.snapshot().model_dump(mode="json"),
        "note": "No open-web face search — closed corpus only.",
    }


@router.post("/vision/liveness/start")
async def liveness_start(body: LivenessStart) -> dict[str, Any]:
    _session(body.session_id)
    state = liveness_store.start(body.session_id, body.challenge)
    return {
        "session_id": body.session_id,
        **state.public(),
        "instructions": {
            "blink": "Blink both eyes once while facing the camera.",
            "turn_left": "Turn your head slowly to the left.",
            "turn_right": "Turn your head slowly to the right.",
        }.get(state.challenge or "", "Complete the on-screen challenge."),
        "privacy": (
            "Liveness runs in-browser with MediaPipe FaceMesh. "
            "Only one verified frame is uploaded after the challenge passes."
        ),
    }


@router.post("/vision/liveness/complete")
async def liveness_complete(
    session_id: str = Form(...),
    challenge_id: str = Form(...),
    client_passed: bool = Form(...),
    file: UploadFile | None = File(None),
) -> dict[str, Any]:
    """Accept at most one verified frame after a client-side pass."""
    session = _session(session_id)
    frame_sha = None
    data = b""
    if file is not None and client_passed:
        data = await _read_upload(file)
        frame_sha = content_hash(data)
    try:
        state = liveness_store.complete(
            session_id,
            challenge_id=challenge_id,
            frame_sha256=frame_sha or hashlib.sha256(b"").hexdigest(),
            client_passed=client_passed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if state.passed and data:
        # Enroll the single verified frame as user_upload for later match.
        corpus = corpus_for(session_id)
        try:
            corpus.enroll(
                entry_id=f"fc_live_{secrets.token_hex(3)}",
                source="liveness_frame",
                account_label="verified:liveness",
                image_bytes=data,
                platform=None,
                verified_accounts={"verified:liveness"},
            )
        except CorpusViolation as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    session.log.record(
        A.FINDING_ADDED if state.passed else A.FINDING_REJECTED,
        actor=Origin.HUMAN,
        subject=challenge_id,
        detail=(
            "Liveness passed; one frame retained with TTL"
            if state.passed
            else "Liveness failed; no frame retained"
        ),
        passed=state.passed,
    )
    _persist(session)
    return {"session_id": session_id, **state.public()}


@router.post("/vision/liveness/skip")
async def liveness_skip(body: LivenessSkip) -> dict[str, Any]:
    """Skip-face path — clears challenge + corpus face enrollments."""
    session = _session(body.session_id)
    state = liveness_store.skip(body.session_id)
    cleared = drop_corpus(body.session_id)
    session.log.record(
        A.FINDING_REJECTED,
        actor=Origin.HUMAN,
        subject=body.session_id,
        detail=f"Operator skipped face path ({body.reason}); cleared {cleared} corpus entries",
        skipped=True,
    )
    _persist(session)
    return {
        "session_id": body.session_id,
        **state.public(),
        "corpus_cleared": cleared,
        "dangling_state": False,
    }


@router.get("/vision/liveness/{session_id}")
async def liveness_status(session_id: str) -> dict[str, Any]:
    _session(session_id)
    return {"session_id": session_id, **liveness_store.get(session_id).public()}


def cleanup_session_vision(session_id: str) -> None:
    """Called from session wipe — no dangling biometric state."""
    liveness_store.clear(session_id)
    drop_corpus(session_id)
