"""Integration checks for Engineer D's WebSocket and voice surfaces."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import app
from mirror_intel.llm import LLM, OfflineProvider, set_llm
from mirror_intel.session import store


def _client() -> TestClient:
    set_llm(LLM(OfflineProvider()))
    return TestClient(app)


def _create(client: TestClient, session_id: str, *, seeded: bool = True) -> dict:
    response = client.post(
        "/intel/session",
        json={
            "session_id": session_id,
            "emails": ["demo@ddu-mirror.local"],
            "handles": ["demo_operator"],
            "persona": "scammer",
            "seed_mock_findings": seeded,
        },
    )
    assert response.status_code == 200
    return response.json()["snapshot"]


def test_voice_scrubs_pii_and_grounds_only_live_findings() -> None:
    client = _client()
    snapshot = _create(client, "s_d_voice")
    rejected_label = next(
        finding["label"] for finding in snapshot["findings"] if finding["id"] == "f_mock_reddit"
    )
    client.post(
        "/intel/findings/reject",
        json={
            "session_id": "s_d_voice",
            "finding_id": "f_mock_reddit",
            "reason": "not mine",
        },
    )

    answer = client.post(
        "/intel/voice/turn",
        json={
            "session_id": "s_d_voice",
            "transcript": "Email me at person@example.com. What should I fix first?",
        },
    )
    assert answer.status_code == 200
    payload = answer.json()
    assert payload["transcript"] == "Email me at [EMAIL]. What should I fix first?"
    assert payload["transcript_redacted"] is True
    assert rejected_label not in payload["answer"]
    assert "f_mock_reddit" not in payload["grounded_finding_ids"]


def test_narration_stops_reading_rejected_nodes() -> None:
    client = _client()
    _create(client, "s_d_narrate")
    client.post(
        "/intel/findings/reject",
        json={
            "session_id": "s_d_narrate",
            "finding_id": "f_mock_breach",
            "reason": "not mine",
        },
    )
    response = client.post(
        "/intel/voice/turn",
        json={"session_id": "s_d_narrate", "mode": "narrate"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "2019 forum breach" not in payload["answer"]
    assert "f_mock_breach" not in payload["grounded_finding_ids"]


def test_websocket_interrupt_resume_materializes_findings() -> None:
    client = _client()
    before = _create(client, "s_d_ws", seeded=False)
    assert [finding["id"] for finding in before["findings"]] == ["f_seed"]

    with client.websocket_connect("/intel/ws/s_d_ws") as websocket:
        initial = websocket.receive_json()
        assert initial["event"] == "session.snapshot"

        websocket.send_json(
            {"request_id": "plan-1", "action": "agent.expand", "state": "TX"}
        )
        planned = websocket.receive_json()
        assert planned["event"] == "agent.awaiting_approval"
        proposal = planned["snapshot"]["pending_proposals"][0]

        websocket.send_json(
            {
                "request_id": "approve-1",
                "action": "proposal.approve",
                "proposal_id": proposal["id"],
            }
        )
        approved = websocket.receive_json()
        assert approved["event"] == "finding.new"
        assert len(approved["snapshot"]["findings"]) > 1

    store.drop("s_d_ws")
