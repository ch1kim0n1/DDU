from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

import app as vision


class FakeEvidenceClient:
    async def fetch(self, evidence_id: str, investigation_id: str) -> tuple[bytes, dict]:
        return b"image", {"id": evidence_id, "investigation_id": investigation_id}


class VisionServiceTest(unittest.TestCase):
    def test_detect_returns_provenance_and_observation_class(self) -> None:
        vision.evidence_client = FakeEvidenceClient()
        vision.detector = vision.DevelopmentDetector()
        response = TestClient(vision.app).post(
            "/v1/detect",
            json={
                "evidence_id": "sha256:test",
                "investigation_id": "case-1",
                "prompts": ["vehicle"],
            },
        )
        self.assertEqual(response.status_code, 200)
        observation = response.json()[0]
        self.assertEqual(observation["type"], "OBSERVATION_TYPE_OBJECT")
        self.assertEqual(observation["label"], "vehicle")
        self.assertEqual(
            observation["attributes"]["epistemic_class"],
            "EPISTEMIC_CLASS_OBSERVATION",
        )
        self.assertEqual(
            observation["provenance"]["model_version"],
            "0.4.0",
        )
        self.assertEqual(observation["evidence_id"], "sha256:test")


if __name__ == "__main__":
    unittest.main()
