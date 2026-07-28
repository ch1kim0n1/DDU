from __future__ import annotations

import time

import jwt
import pytest
from fastapi.testclient import TestClient

import app as mirror_app
from mirror_intel import api
from mirror_intel.actionlog import FINDING_ADDED
from mirror_intel.discovery import hibp
from mirror_intel.identity import IdentityVerifier
from mirror_intel.mock import demo_identity, generate
from mirror_intel.schema import Origin
from mirror_intel.session import RedisSessionStore, Session

TEST_IDENTITY_SECRET = "test-secret-not-for-production-32-bytes-minimum"


def _identity_verifier(monkeypatch: pytest.MonkeyPatch) -> IdentityVerifier:
    monkeypatch.setenv("MIRROR_IDENTITY_REQUIRED", "1")
    monkeypatch.setenv("MIRROR_IDENTITY_ISSUER", "https://identity.test/")
    monkeypatch.setenv("MIRROR_IDENTITY_AUDIENCE", "ddu-mirror")
    monkeypatch.setenv("MIRROR_IDENTITY_HS256_SECRET", TEST_IDENTITY_SECRET)
    monkeypatch.delenv("MIRROR_IDENTITY_JWKS_URL", raising=False)
    return IdentityVerifier()


def _token(*, email_verified: bool = True) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": "https://identity.test/",
            "aud": "ddu-mirror",
            "sub": "operator-123",
            "iat": now,
            "exp": now + 300,
            "email": "verified@example.test",
            "email_verified": email_verified,
            "preferred_username": "verified_handle",
        },
        TEST_IDENTITY_SECRET,
        algorithm="HS256",
    )


def test_signed_identity_claims_replace_untrusted_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = _identity_verifier(monkeypatch)
    monkeypatch.setattr(api, "verifier", verifier)
    client = TestClient(mirror_app.app)
    response = client.post(
        "/intel/session",
        headers={"Authorization": f"Bearer {_token()}"},
        json={
            "session_id": "caller-controlled",
            "emails": ["not-verified@example.test"],
            "handles": ["not_verified"],
            "seed_mock_findings": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"].startswith("sess_")
    assert body["session_id"] != "caller-controlled"
    session = api.store.require(body["session_id"])
    assert session.identity.emails == frozenset({"verified@example.test"})
    assert session.identity.handles == frozenset({"verified_handle"})


def test_unverified_email_claim_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier = _identity_verifier(monkeypatch)
    monkeypatch.setattr(api, "verifier", verifier)
    client = TestClient(mirror_app.app)
    response = client.post(
        "/intel/session",
        headers={"Authorization": f"Bearer {_token(email_verified=False)}"},
        json={},
    )
    assert response.status_code == 401
    assert "not verified" in response.json()["detail"]


def test_encrypted_session_round_trip_hides_raw_identity() -> None:
    key = RedisSessionStore.generate_encryption_key()
    backend = RedisSessionStore("redis://localhost:6379/15", key)
    identity = demo_identity("sess_encrypted")
    session = Session(session_id=identity.session_id, identity=identity)
    session.add_findings(generate(identity, count=3))
    session.vault["rv_test"] = "raw-private-value"
    session.workflow_state = {
        "pending_inputs": {"p1": {"email": "demo@ddu-mirror.local"}}
    }
    session.log.record(
        FINDING_ADDED,
        actor=Origin.SYSTEM,
        subject="test",
        detail="round trip",
    )
    encoded = backend._encode(session)
    assert "demo@ddu-mirror.local" not in encoded
    assert "raw-private-value" not in encoded
    restored = backend._decode(backend._key(session.session_id), encoded)
    assert restored.identity == session.identity
    assert restored.vault == session.vault
    assert restored.workflow_state == session.workflow_state
    assert restored.snapshot().model_dump(mode="json") == session.snapshot().model_dump(
        mode="json"
    )


def test_contract_reports_real_langgraph_runtime() -> None:
    client = TestClient(mirror_app.app)
    workflow = client.get("/intel/contract").json()["workflow"]
    assert workflow["runtime"] == "langgraph"
    assert workflow["checkpoint_backend"] in {"memory", "sqlite", "redis"}


def test_strict_provider_mode_refuses_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = demo_identity("sess_strict")
    monkeypatch.setenv("MIRROR_REQUIRE_LIVE_PROVIDERS", "1")
    monkeypatch.setattr(hibp, "_fetch_live", lambda _email: None)
    with pytest.raises(RuntimeError, match="refusing cached data"):
        hibp.breach_findings(identity, next(iter(identity.emails)))
