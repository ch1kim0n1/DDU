import os

os.environ["MODEL_MODE"] = "stub"
os.environ["OPENLINEAGE_URL"] = ""

import httpx
from fastapi.testclient import TestClient

import app

_store: list[dict] = []


def _graph_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "POST" and request.url.path == "/v1/entities":
        body = request.read()
        import json
        entity = json.loads(body)
        entity["id"] = entity.get("id") or f"evt-{len(_store)+1}"
        entity["created_at"] = "2026-01-01T00:00:00Z"
        _store.append(entity)
        return httpx.Response(201, json=entity)
    if request.method == "GET" and request.url.path == "/v1/entities":
        inv = request.url.params.get("investigation_id")
        etype = request.url.params.get("type")
        entities = [
            e for e in _store
            if e.get("investigation_id") == inv and (not etype or e.get("type") == etype)
        ]
        return httpx.Response(200, json={"entities": entities})
    return httpx.Response(404, json={"error": "not found"})


app.graph_client = httpx.AsyncClient(
    transport=httpx.MockTransport(_graph_handler),
    base_url="http://graph-store",
)
app.store = app.GraphStoreTemporalBackend()


def test_event_and_timeline():
    _store.clear()
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
    assert timeline.json()["backend"] == "GraphStoreTemporalBackend"
