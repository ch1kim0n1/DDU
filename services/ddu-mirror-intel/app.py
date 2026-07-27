"""ddu-mirror-intel — standalone service entry point.

Engineer A owns the DDU Mirror app skeleton and mounts ``mirror_intel.api.router``
into it. This module wraps the same router in its own app so B's slice runs and
demos independently — nobody on this team should be blocked waiting for
somebody else's server to boot.

Follows the DDU service contract from AGENTS.md: ``/healthz``, ``/versionz``,
and OpenLineage emission on invocation.
"""
from __future__ import annotations

import logging
import os

import uvicorn

from ddu_common.app import build_scaffold_app
from ddu_common.version import ServiceVersion, from_env

from mirror_intel import __version__
from mirror_intel.api import router
from mirror_intel.llm import get_llm
from mirror_intel.schema import CONTRACT_VERSION
from mirror_intel.session import store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ddu-mirror-intel")

VERSION = from_env(
    ServiceVersion(
        service="ddu-mirror-intel",
        service_version=__version__,
        tool="ddu-mirror-findings-contract",
        tool_version=CONTRACT_VERSION,
    )
)

PORT = int(os.environ.get("MIRROR_INTEL_PORT", "8120"))

app = build_scaffold_app(VERSION)
app.include_router(router)


@app.get("/readyz")
async def readyz() -> dict:
    """Boot-time posture, in the order it matters for a demo.

    ``llm_provider == "offline"`` is the one to watch: the service is fully
    functional there, but remediation copy is canned and the UI must say so.
    """
    return {
        "state": "READY",
        "contract_version": CONTRACT_VERSION,
        "llm_provider": get_llm().provider.name,
        "hibp_key_configured": bool(os.environ.get("HIBP_API_KEY")),
        "sessions": store.stats(),
        "design_rules_enforced": [
            "1 — no verified control, no scan (guardrails.assert_self)",
            "2 — no third-party traversal (guardrails.suppress_third_party)",
            "4 — redact at the boundary (redaction.assert_no_raw_pii)",
            "6 — untrusted text never reaches a tool-enabled model (quarantine)",
            "7 — nothing irreversible is claimed reversible (schema validator)",
        ],
    }


if __name__ == "__main__":
    log.info(
        "ddu-mirror-intel %s (contract %s) on :%d — provider=%s",
        __version__,
        CONTRACT_VERSION,
        PORT,
        get_llm().provider.name,
    )
    uvicorn.run(app, host="0.0.0.0", port=PORT)
