import os

os.environ["MODEL_MODE"] = "stub"

from fastapi.testclient import TestClient

import app


def test_healthz():
    client = TestClient(app.app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["state"] in {"HEALTHY", "DEGRADED"}


def test_transcribe_validation():
    client = TestClient(app.app)
    response = client.post("/v1/transcribe", json={"evidence_id": "", "investigation_id": "case"})
    assert response.status_code == 422
