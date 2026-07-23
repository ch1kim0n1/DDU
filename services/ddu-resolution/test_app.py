from __future__ import annotations

import json
import unittest

import httpx
from fastapi.testclient import TestClient

import app as resolution


class ResolutionServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.entities = [
            {
                "id": "entity-1",
                "investigation_id": "case-1",
                "type": "ENTITY_TYPE_PERSON",
                "attributes": {"name": "alice", "email": "alice@example.com"},
                "evidence_ids": ["sha256:ev-1"],
            },
            {
                "id": "entity-2",
                "investigation_id": "case-1",
                "type": "ENTITY_TYPE_PERSON",
                "attributes": {"name": "alice", "email": "alice@example.com"},
                "evidence_ids": ["sha256:ev-2"],
            },
            {
                "id": "entity-3",
                "investigation_id": "case-1",
                "type": "ENTITY_TYPE_PERSON",
                "attributes": {"name": "bob"},
                "evidence_ids": [],
            },
        ]

        def graph_store(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"entities": self.entities})

        resolution.graph_client = httpx.AsyncClient(
            transport=httpx.MockTransport(graph_store),
            base_url="http://graph-store",
        )
        resolution.resolver = resolution.DevelopmentResolver()
        self.client = TestClient(resolution.app)

    def test_resolve_returns_pending_candidate_relationships(self) -> None:
        response = self.client.post(
            "/v1/resolve",
            json={"investigation_id": "case-1", "threshold": 0.5},
        )
        self.assertEqual(response.status_code, 200)
        candidates = response.json()
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["relationship_type"], "POSSIBLY_SAME_AS")
        self.assertEqual(
            candidate["verification_state"],
            "VERIFICATION_STATE_PENDING",
        )
        self.assertEqual(candidate["source_entity_id"], "entity-1")
        self.assertEqual(candidate["target_entity_id"], "entity-2")
        self.assertGreater(candidate["confidence"]["value"], 0.5)
        self.assertIn("sha256:ev-1", candidate["supporting_evidence_ids"])
        self.assertIn("sha256:ev-2", candidate["supporting_evidence_ids"])
        self.assertEqual(candidate["provenance"]["tool"], "splink")
        self.assertEqual(candidate["provenance"]["model_version"], "4.0.0")
        self.assertTrue(candidate["signals"])

    def test_resolve_filters_to_requested_entity_ids(self) -> None:
        response = self.client.post(
            "/v1/resolve",
            json={
                "investigation_id": "case-1",
                "entity_ids": ["entity-1", "entity-3"],
                "threshold": 0.0,
            },
        )
        self.assertEqual(response.status_code, 200)
        candidates = response.json()
        for candidate in candidates:
            ids = {candidate["source_entity_id"], candidate["target_entity_id"]}
            self.assertTrue(ids.issubset({"entity-1", "entity-3"}))


if __name__ == "__main__":
    unittest.main()
