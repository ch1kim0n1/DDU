"""SpiderFoot OSINT enrichment service."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import logging
import os
from typing import Protocol
from uuid import uuid4

import httpx
import uvicorn
from fastapi import HTTPException
from pydantic import BaseModel, Field

from ddu_common.app import build_scaffold_app
from ddu_common.lineage import Event, Input, LineageEmitter, Output
from ddu_common.runtime import model_mode_is_stub
from ddu_common.version import ServiceVersion, from_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ddu-osint")

VERSION = from_env(ServiceVersion(
    service="ddu-osint",
    service_version="0.0.1-dev",
    tool="spiderfoot",
    tool_version="4.0",
))

SPIDERFOOT_URL = os.environ.get("SPIDERFOOT_URL", "http://localhost:5001").rstrip("/")
spiderfoot_client = httpx.AsyncClient(base_url=SPIDERFOOT_URL, timeout=60.0)


class EnrichRequest(BaseModel):
    target: str = Field(min_length=1)
    investigation_id: str = Field(min_length=1)
    modules: list[str] | None = None


@dataclass(frozen=True)
class EnrichmentResult:
    data_type: str
    value: str
    source_module: str
    confidence: float


class EnrichmentAdapter(Protocol):
    async def enrich(self, target: str, modules: list[str]) -> list[EnrichmentResult]: ...


class DevelopmentEnricher:
    async def enrich(self, target: str, modules: list[str]) -> list[EnrichmentResult]:
        del modules
        return [
            EnrichmentResult("EMAIL_ADDRESS", f"admin@{target}", "sfp_email", 0.5),
            EnrichmentResult("IP_ADDRESS", "203.0.113.10", "sfp_dnsresolve", 0.5),
            EnrichmentResult("DOMAIN_NAME", target, "sfp_whois", 0.5),
        ]


class SpiderFootEnricher:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def enrich(self, target: str, modules: list[str]) -> list[EnrichmentResult]:
        payload = {
            "target": target,
            "type": "internet",
            "modules": ",".join(modules) if modules else "all",
        }
        scan_response = await self._client.post("/api/v1/scan", json=payload)
        scan_response.raise_for_status()
        scan_body = scan_response.json()
        scan_id = _extract_scan_id(scan_body)
        results = await self._poll_results(scan_id)
        return results

    async def _poll_results(self, scan_id: str) -> list[EnrichmentResult]:
        deadline = asyncio.get_event_loop().time() + float(
            os.environ.get("SPIDERFOOT_POLL_TIMEOUT", "120"),
        )
        while asyncio.get_event_loop().time() < deadline:
            status_response = await self._client.get(f"/api/v1/scan/{scan_id}")
            status_response.raise_for_status()
            body = status_response.json()
            status = str(body.get("status", body.get("state", ""))).upper()
            if status in {"FINISHED", "COMPLETE", "ABORTED", "FAILED"}:
                if status not in {"FINISHED", "COMPLETE"}:
                    raise RuntimeError(f"spiderfoot scan {scan_id} ended with status {status}")
                return _parse_results(body)
            await asyncio.sleep(float(os.environ.get("SPIDERFOOT_POLL_INTERVAL", "2")))
        raise RuntimeError(f"spiderfoot scan {scan_id} timed out")


def _extract_scan_id(body: object) -> str:
    if isinstance(body, dict):
        for key in ("scan_id", "id", "scanId"):
            value = body.get(key)
            if value:
                return str(value)
    if isinstance(body, list) and len(body) >= 2 and body[0] == "SUCCESS":
        return str(body[1])
    if isinstance(body, list) and len(body) >= 1:
        return str(body[-1])
    raise RuntimeError(f"spiderfoot scan response did not include a scan id: {body!r}")


def _parse_results(body: dict) -> list[EnrichmentResult]:
    results: list[EnrichmentResult] = []
    raw = body.get("results") or body.get("data") or []
    if isinstance(raw, dict):
        raw = raw.get("results") or raw.get("events") or []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        results.append(EnrichmentResult(
            str(item.get("type", item.get("data_type", "METADATA"))),
            str(item.get("data", item.get("value", ""))),
            str(item.get("module", item.get("source_module", "spiderfoot"))),
            float(item.get("confidence", 0.5)),
        ))
    return results


app = build_scaffold_app(VERSION)
lineage = LineageEmitter(VERSION)
enricher: EnrichmentAdapter = (
    DevelopmentEnricher()
    if model_mode_is_stub()
    else SpiderFootEnricher(spiderfoot_client)
)


@app.post("/v1/enrich")
async def enrich(request: EnrichRequest) -> list[dict]:
    run_id = lineage.new_run_id()
    evidence_id = f"sha256:{hashlib.sha256(request.target.encode()).hexdigest()}"
    facets = {"dduInvestigation": {"investigation_id": request.investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-osint:enrich",
        inputs=[Input(
            namespace=request.investigation_id,
            name=evidence_id,
            type="DDU.EVIDENCE",
        )],
        facets=facets,
    ))
    try:
        results = await enricher.enrich(request.target, request.modules or [])
    except (httpx.HTTPError, RuntimeError, ValueError, OSError) as exc:
        lineage.emit(Event(
            event_type="FAIL",
            run_id=run_id,
            job_name="ddu-osint:enrich",
            facets=facets,
        ))
        log.exception("OSINT enrichment failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    observed_at = datetime.now(timezone.utc).isoformat()
    method = "development-stub" if isinstance(enricher, DevelopmentEnricher) else "spiderfoot"
    modules = request.modules or []
    parameters = {"target": request.target, "modules": ",".join(modules) if modules else "all"}
    observations = [
        {
            "id": str(uuid4()),
            "investigation_id": request.investigation_id,
            "evidence_id": evidence_id,
            "type": "OBSERVATION_TYPE_METADATA",
            "label": item.value,
            "detector_confidence": item.confidence,
            "attributes": {
                "data_type": item.data_type,
                "source_module": item.source_module,
                "epistemic_class": "EPISTEMIC_CLASS_OBSERVATION",
            },
            "metadata": {
                "data_type": item.data_type,
                "value": item.value,
                "source_module": item.source_module,
            },
            "provenance": {
                "investigation_id": request.investigation_id,
                "produced_by_service": VERSION.service,
                "producer_version": VERSION.as_dict(),
                "tool": VERSION.tool,
                "tool_version": VERSION.tool_version,
                "model": VERSION.model,
                "model_version": VERSION.model_version,
                "produced_at": observed_at,
                "run_id": run_id,
                "job_name": "ddu-osint:enrich",
                "input_evidence_ids": [evidence_id],
                "extraction_method": method,
                "parameters": parameters,
            },
            "observed_at": observed_at,
        }
        for item in results
    ]
    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-osint:enrich",
        inputs=[Input(
            namespace=request.investigation_id,
            name=evidence_id,
            type="DDU.EVIDENCE",
        )],
        outputs=[
            Output(
                namespace=request.investigation_id,
                name=item["id"],
                type="DDU.OBSERVATION",
            )
            for item in observations
        ],
        facets=facets,
    ))
    return observations


def main() -> None:
    port = int(os.environ.get("PORT", 8110))
    log.info("ddu-osint listening on :%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
