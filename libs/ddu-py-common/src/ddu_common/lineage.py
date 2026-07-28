"""OpenLineage event emitter for Python services.

Sends RunEvents to an OpenLineage backend (Marquez in dev) via HTTP.
Best-effort: failures are logged, never raised. One retry on transient failure.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import httpx

from ddu_common.version import ServiceVersion

log = logging.getLogger("ddu.lineage")

_DEFAULT_TIMEOUT = 5.0
_RETRY_BACKOFF = 0.5


@dataclass
class Input:
    namespace: str
    name: str
    type: str
    facets: dict[str, Any] = field(default_factory=dict)


@dataclass
class Output:
    namespace: str
    name: str
    type: str
    facets: dict[str, Any] = field(default_factory=dict)


@dataclass
class Event:
    event_type: str  # START, RUNNING, COMPLETE, FAIL, ABORT
    run_id: str = ""
    job_name: str = ""
    inputs: list[Input] = field(default_factory=list)
    outputs: list[Output] = field(default_factory=list)
    facets: dict[str, Any] = field(default_factory=dict)


class LineageEmitter:
    def __init__(self, producer: ServiceVersion) -> None:
        url = os.environ.get("OPENLINEAGE_URL", "").rstrip("/")
        if not url:
            self._disabled = True
            log.warning("OPENLINEAGE_URL not set; lineage events will be dropped")
            return
        self._disabled = False
        self._url = f"{url}/api/v1/lineage"
        self._namespace = os.environ.get("OPENLINEAGE_NAMESPACE", "ddu.dev")
        self._producer = producer
        self._client = httpx.Client(timeout=_DEFAULT_TIMEOUT)

    def new_run_id(self) -> str:
        return str(uuid4())

    def emit(self, event: Event) -> None:
        if self._disabled:
            return
        if not event.run_id:
            event.run_id = self.new_run_id()
        payload = self._build_payload(event)
        try:
            self._send(payload)
        except Exception as e:
            log.warning("lineage emit failed (will retry once): %s", e)
            time.sleep(_RETRY_BACKOFF)
            try:
                self._send(payload)
            except Exception as e2:
                log.error("lineage emit retry failed: %s (first: %s)", e2, e)

    def _send(self, payload: dict) -> None:
        resp = self._client.post(self._url, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"openlineage returned {resp.status_code}: {resp.text[:512]}"
            )

    def _build_payload(self, event: Event) -> dict:
        return {
            "eventType": event.event_type.upper(),
            "eventTime": time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime()),
            "run": {
                "runId": event.run_id,
                "facets": event.facets,
            },
            "job": {
                "namespace": self._namespace,
                "name": event.job_name,
                "facets": {"dduProducer": self._producer.as_dict()},
            },
            "inputs": [
                {"namespace": i.namespace, "name": i.name, "facets": {"dataType": i.type}}
                for i in event.inputs
            ],
            "outputs": [
                {"namespace": o.namespace, "name": o.name, "facets": {"dataType": o.type}}
                for o in event.outputs
            ],
            "producer": (
                f"https://ddu.local/{self._producer.service}/"
                f"{self._producer.service_version}"
            ),
        }
