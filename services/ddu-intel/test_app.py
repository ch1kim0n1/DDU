import os

os.environ["MODEL_MODE"] = "stub"
os.environ.pop("OPENLINEAGE_URL", None)

import httpx
from fastapi.testclient import TestClient

import app


def _mock_graph() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/entities"):
            return httpx.Response(200, json={"entities": [
                {
                    "id": "e1",
                    "type": "ENTITY_TYPE_OBSERVATION",
                    "attributes": {"label": "alice", "detector_confidence": "0.7"},
                }
            ]})
        if request.url.path.endswith("/relationships"):
            return httpx.Response(200, json={"relationships": [
                {
                    "id": "r1",
                    "source_entity_id": "e1",
                    "target_entity_id": "e2",
                    "relationship_type": "POSSIBLY_SAME_AS",
                    "confidence": {"value": 0.6},
                }
            ]})
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
