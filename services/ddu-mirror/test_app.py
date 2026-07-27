from fastapi.testclient import TestClient

import app as service


def client() -> TestClient:
    return TestClient(service.app)


def verified_session(test_client: TestClient) -> str:
    started = test_client.post("/v1/onboarding/start", json={"email": "owner@example.com", "adult_confirmed": True, "persona": "stalker", "guess_first": "just my public profile"})
    assert started.status_code == 200
    verified = test_client.post("/v1/onboarding/verify", json={"challenge_id": started.json()["challenge_id"], "code": started.json()["development_code"]})
    assert verified.status_code == 200
    return verified.json()["session_id"]


def test_unverified_identity_cannot_authorize_a_scan():
    test_client = client()
    response = test_client.post("/v1/scans/authorize", json={"session_id": "not-verified"})
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "unknown_session"


def test_adult_gate_and_code_attempt_limit():
    test_client = client()
    assert test_client.post("/v1/onboarding/start", json={"email": "a@example.com", "adult_confirmed": False}).status_code == 403
    started = test_client.post("/v1/onboarding/start", json={"email": "a@example.com", "adult_confirmed": True}).json()
    for _ in range(3):
        assert test_client.post("/v1/onboarding/verify", json={"challenge_id": started["challenge_id"], "code": "000000"}).status_code == 403
    assert test_client.post("/v1/onboarding/verify", json={"challenge_id": started["challenge_id"], "code": started["development_code"]}).status_code == 403


def test_consent_skip_findings_audit_receipt_and_wipe():
    test_client = client()
    session_id = verified_session(test_client)
    assert test_client.post("/v1/scans/authorize", json={"session_id": session_id}).json()["authorized"] is True
    skipped = test_client.post("/v1/consent/biometric", json={"session_id": session_id, "accepted": False})
    assert skipped.status_code == 200 and skipped.json()["biometric"]["consented"] is False
    accepted = test_client.post("/v1/consent/biometric", json={"session_id": session_id, "accepted": True})
    assert accepted.json()["biometric"]["destruction_countdown_seconds"] > 0
    ingested = test_client.post("/v1/findings", json={"session_id": session_id, "findings": [{"id": "f_1", "type": "gps_exposure", "email": "must-not-pass@example.com"}]})
    assert ingested.json()["accepted"] == 1
    audit = test_client.get(f"/v1/sessions/{session_id}/audit").json()["events"]
    assert any(item["action"] == "findings_ingested" for item in audit)
    assert "owner@example.com" not in str(audit)
    receipt = test_client.post(f"/v1/sessions/{session_id}/receipt").json()
    assert receipt["signature"]["algorithm"] == "Ed25519"
    wiped = test_client.delete(f"/v1/sessions/{session_id}")
    assert wiped.status_code == 200 and wiped.json()["destroyed"]["findings"] == 1
    assert test_client.get(f"/v1/sessions/{session_id}").status_code == 404


def test_step_up_reverification_is_bound_to_its_session():
    test_client = client()
    session_id = verified_session(test_client)
    started = test_client.post("/v1/reverify/start", json={"session_id": session_id}).json()
    confirmed = test_client.post("/v1/reverify/confirm", json={"challenge_id": started["challenge_id"], "code": started["development_code"]})
    assert confirmed.status_code == 200
    assert confirmed.json()["step_up_verified"] is True


def test_no_free_text_target_exists_in_openapi():
    schema = client().get("/openapi.json").json()
    assert '"target"' not in str(schema).lower()
