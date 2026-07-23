import os

os.environ["MODEL_MODE"] = "stub"
os.environ.pop("OPENLINEAGE_URL", None)

import httpx
from fastapi.testclient import TestClient

import app


def _mock_graph() -> None:
    entities = [
        {
            "id": "e1",
            "type": "ENTITY_TYPE_USERNAME",
            "attributes": {"label": "alice", "username": "alice", "platform": "github"},
            "evidence_ids": ["sha256:ev1"],
        },
        {
            "id": "e2",
            "type": "ENTITY_TYPE_LOCATION",
            "attributes": {
                "label": "austin-office",
                "place": "Austin, TX",
                "lat": "30.27",
                "lon": "-97.74",
                "observed_at": "2026-01-02T00:00:00Z",
            },
            "evidence_ids": ["sha256:ev2"],
        },
        {
            "id": "e3",
            "type": "ENTITY_TYPE_PERSON",
            "attributes": {"label": "alice-parent", "name": "alice-parent"},
            "evidence_ids": ["sha256:ev3"],
        },
        {
            "id": "e4",
            "type": "ENTITY_TYPE_ORGANIZATION",
            "attributes": {"label": "Example Corp"},
            "evidence_ids": ["sha256:ev4"],
        },
        {
            "id": "e5",
            "type": "ENTITY_TYPE_DOCUMENT",
            "attributes": {
                "label": "alice-deed",
                "record_type": "property",
                "jurisdiction": "TX",
                "source_url": "https://example.public.records/deed/1",
            },
            "evidence_ids": ["sha256:ev5"],
        },
        {
            "id": "e6",
            "type": "ENTITY_TYPE_VEHICLE",
            "attributes": {"label": "gray sedan"},
            "evidence_ids": ["sha256:ev6"],
        },
        {
            "id": "e7",
            "type": "ENTITY_TYPE_LOCATION",
            "attributes": {
                "place": "Dallas, TX",
                "observed_at": "2025-06-01T00:00:00Z",
                "label": "dallas-trip",
            },
            "evidence_ids": ["sha256:ev7"],
        },
    ]
    relationships = [
        {
            "id": "r1",
            "source_entity_id": "e1",
            "target_entity_id": "e3",
            "relationship_type": "POSSIBLY_RELATED",
            "confidence": {"value": 0.6},
        },
        {
            "id": "r2",
            "source_entity_id": "e1",
            "target_entity_id": "e4",
            "relationship_type": "AFFILIATED_WITH",
            "confidence": {"value": 0.7},
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/entities"):
            return httpx.Response(201, json={"id": "snap-1"})
        if request.url.path.endswith("/entities"):
            return httpx.Response(200, json={"entities": entities})
        if request.url.path.endswith("/relationships"):
            return httpx.Response(200, json={"relationships": relationships})
        return httpx.Response(404, json={"error": "missing"})

    app.graph_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://graph-store",
    )


_mock_graph()
client = TestClient(app.app)


def _subject(extra: dict | None = None) -> dict:
    body = {
        "investigation_id": "case-intel",
        "subject": "alice",
        "authorization_purpose": "authorized-investigation",
        "authorized_scope": "investigation",
    }
    if extra:
        body.update(extra)
    return body


def test_capabilities():
    response = client.get("/v1/capabilities")
    assert response.status_code == 200
    assert len(response.json()["features"]) >= 17


def test_s_tier_endpoints():
    for path in [
        "/v1/location/current",
        "/v1/household",
        "/v1/property",
        "/v1/identity/resolve",
        "/v1/pattern-of-life",
        "/v1/temporal/diff",
    ]:
        response = client.post(path, json=_subject())
        assert response.status_code == 200, (path, response.text)
    loc = client.post("/v1/location/current", json=_subject()).json()
    assert loc["hypotheses"][0]["label"] in {"Austin, TX", "Dallas, TX"}
    assert loc["hypotheses"][0]["attributes"].get("source_entity_id")


def test_a_tier_endpoints():
    for path in [
        "/v1/social-circle",
        "/v1/location/history",
        "/v1/aliases",
        "/v1/records/fuse",
        "/v1/relationship/strength",
        "/v1/life-events",
    ]:
        response = client.post(path, json=_subject())
        assert response.status_code == 200, (path, response.text)


def test_b_tier_and_web_history():
    for path in ["/v1/employment", "/v1/assets", "/v1/location/fuse"]:
        response = client.post(path, json=_subject())
        assert response.status_code == 200, (path, response.text)
    response = client.post("/v1/web-history", json=_subject({"url": "https://example.com/profile"}))
    assert response.status_code == 200
    second = client.post("/v1/web-history", json=_subject({"url": "https://example.com/profile"}))
    assert second.status_code == 200
    assert second.json()["change_event"]["attributes"]["changed"] is True


def test_scene_and_playback():
    scene = client.get("/v1/scene/3d", params={"investigation_id": "case-intel"})
    assert scene.status_code == 200
    assert len(scene.json()["nodes"]) >= 1
    playback = client.get("/v1/playback", params={"investigation_id": "case-intel"})
    assert playback.status_code == 200
    assert "frames" in playback.json()
