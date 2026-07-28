"""Engineer C tests — vision analyze, cache DoD, liveness, skip-face cleanup."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import app
from mirror_intel.vision.cache import reload_cache
from mirror_intel.vision.corpus import CorpusViolation, ClosedCorpus
from mirror_intel.vision.exif import extract_exif
from mirror_intel.vision.liveness import liveness_store

CACHE_DIR = (
    Path(__file__).resolve().parent
    / "mirror_intel"
    / "data"
    / "vision_cache"
)


@pytest.fixture
def client():
    reload_cache()
    with TestClient(app) as c:
        yield c


def _session(client: TestClient, sid: str = "s_vision") -> str:
    response = client.post(
        "/intel/session",
        json={"session_id": sid, "handles": ["demo_operator"], "emails": ["demo@ddu.local"]},
    )
    assert response.status_code == 200
    return response.json()["session_id"]


def test_demo_assets_exist():
    reload_cache()
    assert (CACHE_DIR / "index.json").is_file()
    jpgs = list(CACHE_DIR.glob("demo_*.jpg"))
    assert len(jpgs) >= 3


def test_exif_extracts_gps_from_demo_photo():
    path = CACHE_DIR / "demo_vacation_plate.jpg"
    assert path.is_file()
    result = extract_exif(path.read_bytes())
    assert result.has_gps
    assert result.latitude is not None
    assert result.longitude is not None


def test_analyze_demo_photo_under_two_seconds(client):
    sid = _session(client, "s_fast")
    path = CACHE_DIR / "demo_vacation_plate.jpg"
    with path.open("rb") as fh:
        response = client.post(
            "/intel/vision/analyze",
            data={"session_id": sid, "platform": "instagram"},
            files={"file": ("demo_vacation_plate.jpg", fh, "image/jpeg")},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cache_hit"] is True
    assert body["within_two_seconds"] is True
    assert body["elapsed_ms"] < 2000
    assert body["exif"]["has_gps"] is True
    types = {f["type"] for f in body["accepted"]}
    assert "gps_exposure" in types
    assert "object_exposure" in types
    # GeoCLIP always hypothesis
    geo = [f for f in body["accepted"] if f["type"] == "location_inference"]
    assert geo
    assert all(f["verification_state"] == "hypothesis" for f in geo)
    assert body["redaction_preview"]["face_count"] >= 1


def test_stripped_photo_emits_geo_hypothesis_without_gps(client):
    sid = _session(client, "s_stripped")
    path = CACHE_DIR / "demo_stripped_street.jpg"
    with path.open("rb") as fh:
        body = client.post(
            "/intel/vision/analyze",
            data={"session_id": sid},
            files={"file": ("demo_stripped_street.jpg", fh, "image/jpeg")},
        ).json()
    assert body["exif"]["has_gps"] is False
    types = {f["type"] for f in body["accepted"]}
    assert "gps_exposure" not in types
    assert "location_inference" in types
    assert "object_exposure" in types


def test_closed_corpus_rejects_open_web_source():
    corpus = ClosedCorpus()
    with pytest.raises(CorpusViolation):
        corpus.enroll(
            entry_id="x",
            source="open_web_scrape",
            account_label="stranger",
            image_bytes=b"fake",
        )


def test_face_enroll_and_match(client):
    sid = _session(client, "s_face")
    path = CACHE_DIR / "demo_badge_selfie.jpg"
    data = path.read_bytes()
    enroll = client.post(
        "/intel/vision/face/enroll",
        data={
            "session_id": sid,
            "source": "verified_avatar",
            "account_label": "demo_operator",
            "platform": "linkedin",
        },
        files={"file": ("avatar.jpg", data, "image/jpeg")},
    )
    assert enroll.status_code == 200, enroll.text

    match = client.post(
        "/intel/vision/face/match",
        data={"session_id": sid, "threshold": "0.7"},
        files={"file": ("probe.jpg", data, "image/jpeg")},
    )
    assert match.status_code == 200, match.text
    body = match.json()
    assert body["hits"]
    assert any(f["type"] == "face_link" for f in body["accepted"])


def test_liveness_pass_and_fail(client):
    sid = _session(client, "s_live")
    start = client.post(
        "/intel/vision/liveness/start",
        json={"session_id": sid, "challenge": "blink"},
    ).json()
    assert start["challenge"] == "blink"
    challenge_id = start["challenge_id"]

    fail = client.post(
        "/intel/vision/liveness/complete",
        data={
            "session_id": sid,
            "challenge_id": challenge_id,
            "client_passed": "false",
        },
    ).json()
    assert fail["passed"] is False
    assert fail["has_frame"] is False

    # Restart for pass
    start2 = client.post(
        "/intel/vision/liveness/start",
        json={"session_id": sid, "challenge": "turn_left"},
    ).json()
    path = CACHE_DIR / "demo_home_backyard.jpg"
    with path.open("rb") as fh:
        ok = client.post(
            "/intel/vision/liveness/complete",
            data={
                "session_id": sid,
                "challenge_id": start2["challenge_id"],
                "client_passed": "true",
            },
            files={"file": ("frame.jpg", fh, "image/jpeg")},
        ).json()
    assert ok["passed"] is True
    assert ok["has_frame"] is True
    assert ok["template_ttl_seconds_remaining"] is not None


def test_skip_face_clears_dangling_state(client):
    sid = _session(client, "s_skip")
    client.post("/intel/vision/liveness/start", json={"session_id": sid})
    path = CACHE_DIR / "demo_badge_selfie.jpg"
    with path.open("rb") as fh:
        client.post(
            "/intel/vision/face/enroll",
            data={
                "session_id": sid,
                "source": "user_upload",
                "account_label": "selfie",
            },
            files={"file": ("a.jpg", fh, "image/jpeg")},
        )

    skipped = client.post(
        "/intel/vision/liveness/skip",
        json={"session_id": sid},
    ).json()
    assert skipped["skipped"] is True
    assert skipped["dangling_state"] is False
    assert skipped["corpus_cleared"] >= 1
    assert liveness_store.get(sid).skipped is True

    # Match must refuse after skip
    with path.open("rb") as fh:
        refused = client.post(
            "/intel/vision/face/match",
            data={"session_id": sid},
            files={"file": ("p.jpg", fh, "image/jpeg")},
        )
    assert refused.status_code == 409


def test_wipe_clears_liveness(client):
    sid = _session(client, "s_wipe_v")
    client.post("/intel/vision/liveness/start", json={"session_id": sid})
    client.delete(f"/intel/session/{sid}")
    assert sid not in liveness_store._by_session
