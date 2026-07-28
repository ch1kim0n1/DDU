import os

os.environ["MODEL_MODE"] = "stub"

from fastapi.testclient import TestClient

import app


def test_match_stub():
    client = TestClient(app.app)
    # Evidence fetch will fail without storage; exercise request validation instead.
    response = client.post("/v1/match", json={
        "evidence_id": "",
        "investigation_id": "case-1",
    })
    assert response.status_code == 422


def test_healthz():
    client = TestClient(app.app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["state"] in {"HEALTHY", "DEGRADED"}
