from __future__ import annotations

import json
import unittest

import httpx
from fastapi.testclient import TestClient

import app as ontology


class OntologyServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.forwarded: dict[str, object] | None = None
        ontology._custom_types.clear()
        ontology._loaded_investigations.clear()

        def graph_store(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(200, json={"entities": []})
            self.forwarded = json.loads(request.content)
            return httpx.Response(201, json={**self.forwarded, "id": "entity-1"})

        ontology.graph_client = httpx.AsyncClient(
            transport=httpx.MockTransport(graph_store),
            base_url="http://graph-store",
        )
        self.client = TestClient(ontology.app)

    def test_lists_proto_entity_types(self) -> None:
        response = self.client.get("/v1/entity-types")
        self.assertEqual(response.status_code, 200)
        values = {item["name"]: item["number"] for item in response.json()["entity_types"]}
        self.assertEqual(values["ENTITY_TYPE_OBSERVATION"], 14)

    def test_validates_and_forwards_entity(self) -> None:
        entity = {
            "investigation_id": "case-1",
            "type": "ENTITY_TYPE_OBSERVATION",
            "attributes": {"label": "vehicle"},
            "evidence_ids": ["sha256:test"],
            "provenance": {"produced_by_service": "ddu-vision"},
        }
        response = self.client.post("/v1/entities", json=entity)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["id"], "entity-1")
        self.assertEqual(self.forwarded, entity)

    def test_rejects_unknown_entity_type(self) -> None:
        response = self.client.post(
            "/v1/entities",
            json={"investigation_id": "case-1", "type": "NOT_A_TYPE"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIsNone(self.forwarded)

    def test_custom_type_builder(self) -> None:
        created = self.client.post("/v1/entity-types", json={
            "investigation_id": "case-1",
            "name": "drone",
            "description": "UAV sighting",
            "parent_type": "ENTITY_TYPE_OBJECT",
            "attributes": ["make", "model"],
        })
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["name"], "ENTITY_TYPE_DRONE")

        listed = self.client.get("/v1/entity-types", params={"investigation_id": "case-1"})
        names = [item["name"] for item in listed.json()["entity_types"]]
        self.assertIn("ENTITY_TYPE_DRONE", names)

        entity = self.client.post("/v1/entities", json={
            "investigation_id": "case-1",
            "type": "ENTITY_TYPE_DRONE",
            "attributes": {"label": "quadcopter"},
            "evidence_ids": [],
            "provenance": {"produced_by_service": "test"},
        })
        self.assertEqual(entity.status_code, 201)


if __name__ == "__main__":
    unittest.main()
