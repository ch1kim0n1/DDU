from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

import app as osint


class OsintServiceTest(unittest.TestCase):
    def test_enrich_returns_metadata_observations_in_stub_mode(self) -> None:
        osint.enricher = osint.DevelopmentEnricher()
        response = TestClient(osint.app).post(
            "/v1/enrich",
            json={
                "target": "example.com",
                "investigation_id": "case-1",
                "modules": ["sfp_email"],
            },
        )
        self.assertEqual(response.status_code, 200)
        observations = response.json()
        self.assertEqual(len(observations), 3)
        observation = observations[0]
        self.assertEqual(observation["type"], "OBSERVATION_TYPE_METADATA")
        self.assertEqual(
            observation["attributes"]["epistemic_class"],
            "EPISTEMIC_CLASS_OBSERVATION",
        )
        self.assertEqual(observation["provenance"]["tool"], "spiderfoot")
        self.assertEqual(observation["provenance"]["tool_version"], "4.0")
        self.assertTrue(observation["evidence_id"].startswith("sha256:"))
        self.assertEqual(observation["investigation_id"], "case-1")

    def test_enrich_uses_all_modules_when_omitted(self) -> None:
        osint.enricher = osint.DevelopmentEnricher()
        response = TestClient(osint.app).post(
            "/v1/enrich",
            json={"target": "example.com", "investigation_id": "case-1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["provenance"]["parameters"]["modules"], "all")


if __name__ == "__main__":
    unittest.main()
