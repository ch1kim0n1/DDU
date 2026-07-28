from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from ddu_common.lineage import Event, LineageEmitter
from ddu_common.version import ServiceVersion


class LineagePayloadTest(unittest.TestCase):
    def test_producer_is_openlineage_uri(self) -> None:
        with patch.dict(
            os.environ,
            {"OPENLINEAGE_URL": "http://lineage"},
            clear=False,
        ):
            emitter = LineageEmitter(ServiceVersion(
                service="ddu-test",
                service_version="1.2.3",
            ))
        payload = emitter._build_payload(Event(
            event_type="COMPLETE",
            run_id="run-1",
            job_name="ddu-test:run",
        ))
        self.assertEqual(
            payload["producer"],
            "https://ddu.local/ddu-test/1.2.3",
        )


if __name__ == "__main__":
    unittest.main()
