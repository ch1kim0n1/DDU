from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

import app as ocr


class FakeEvidenceClient:
    async def fetch(self, evidence_id: str, investigation_id: str) -> tuple[bytes, dict]:
        return b"image", {"id": evidence_id, "investigation_id": investigation_id}


class OCRServiceTest(unittest.TestCase):
    def test_ocr_returns_text_observation_with_provenance(self) -> None:
        ocr.evidence_client = FakeEvidenceClient()
        ocr.ocr_adapter = ocr.DevelopmentOCR()
        response = TestClient(ocr.app).post(
            "/v1/ocr",
            json={
                "evidence_id": "sha256:test",
                "investigation_id": "case-1",
            },
        )
        self.assertEqual(response.status_code, 200)
        observation = response.json()[0]
        self.assertEqual(observation["type"], "OBSERVATION_TYPE_TEXT")
        self.assertEqual(observation["text"]["language"], "en")
        self.assertEqual(observation["provenance"]["model_version"], "4.0")
        self.assertEqual(
            observation["attributes"]["epistemic_class"],
            "EPISTEMIC_CLASS_OBSERVATION",
        )


if __name__ == "__main__":
    unittest.main()
