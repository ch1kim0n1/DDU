import os

os.environ["MODEL_MODE"] = "stub"

from fastapi.testclient import TestClient

import app


def test_event_and_timeline():
    client = TestClient(app.app)
    created = client.post("/v1/events", json={
        "investigation_id": "case-1",
        "entity_id": "entity-1",
        "event_type": "OBSERVED",
        "label": "sighting",
        "timestamp": "2026-01-01T00:00:00Z",
    })
    assert created.status_code == 200
    timeline = client.get("/v1/timeline", params={"investigation_id": "case-1"})
    assert timeline.status_code == 200
    events = timeline.json()["events"]
    assert any(item["label"] == "sighting" for item in events)
