from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

import app as geo


class FakeEvidenceClient:
    async def fetch(self, evidence_id: str, investigation_id: str) -> tuple[bytes, dict]:
        return b"image", {"id": evidence_id, "investigation_id": investigation_id}


class GeoServiceTest(unittest.TestCase):
    def test_locate_returns_ranked_location_observation(self) -> None:
        geo.evidence_client = FakeEvidenceClient()
        geo.geo_adapter = geo.DevelopmentGeoAdapter()
        response = TestClient(geo.app).post(
            "/v1/locate",
            json={
                "evidence_id": "sha256:test",
                "investigation_id": "case-1",
                "top_k": 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        observation = response.json()[0]
        self.assertEqual(observation["type"], "OBSERVATION_TYPE_LOCATION")
        self.assertEqual(observation["label"], "Austin, Texas")
        self.assertEqual(observation["attributes"]["rank"], "1")
        self.assertEqual(observation["provenance"]["model_version"], "1.2.0")
        self.assertEqual(observation["geo"]["latitude"], 30.2672)


if __name__ == "__main__":
    unittest.main()
