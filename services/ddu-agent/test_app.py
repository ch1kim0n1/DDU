from __future__ import annotations

import unittest

import httpx
from fastapi.testclient import TestClient

import app as agent


class AgentServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == "/v1/detect":
                return httpx.Response(200, json=[
                    {"id": "obs-vision-1", "type": "OBSERVATION_TYPE_OBJECT", "label": "vehicle"},
                ])
            if path == "/v1/ocr":
                return httpx.Response(200, json=[
                    {"id": "obs-ocr-1", "type": "OBSERVATION_TYPE_TEXT", "label": "ABC-123"},
                ])
            if path == "/v1/locate":
                return httpx.Response(200, json=[
                    {"id": "obs-geo-1", "type": "OBSERVATION_TYPE_LOCATION", "label": "Austin"},
                ])
            if path == "/v1/entities":
                return httpx.Response(201, json={
                    "id": "entity-1",
                    "type": "ENTITY_TYPE_OBSERVATION",
                    "attributes": {"label": "vehicle"},
                })
            return httpx.Response(404, json={"error": "not found"})

        transport = httpx.MockTransport(handler)
        agent.vision_client = httpx.AsyncClient(transport=transport, base_url="http://vision")
        agent.ocr_client = httpx.AsyncClient(transport=transport, base_url="http://ocr")
        agent.geo_client = httpx.AsyncClient(transport=transport, base_url="http://geo")
        agent.ontology_client = httpx.AsyncClient(transport=transport, base_url="http://ontology")
        agent.workflow_adapter = agent.DirectWorkflowAdapter()
        self.client = TestClient(agent.app)

    def test_workflow_image_orchestrates_all_steps(self) -> None:
        response = self.client.post(
            "/v1/workflow/image",
            json={
                "evidence_id": "sha256:test",
                "investigation_id": "case-1",
                "prompts": ["vehicle"],
            },
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["evidence_id"], "sha256:test")
        self.assertEqual(len(result["observations"]), 3)
        self.assertEqual(len(result["entities"]), 3)
        step_names = [step["step"] for step in result["steps"]]
        self.assertEqual(step_names, [
            "ddu-vision:detect",
            "ddu-ocr:extract",
            "ddu-geo:locate",
            "ddu-ontology:create-entities",
        ])
        for step in result["steps"]:
            self.assertEqual(step["status"], "COMPLETE")

    def test_workflow_image_without_prompts(self) -> None:
        response = self.client.post(
            "/v1/workflow/image",
            json={"evidence_id": "sha256:test", "investigation_id": "case-1"},
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(len(result["steps"]), 4)


if __name__ == "__main__":
    unittest.main()
