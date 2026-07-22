"""ddu-resolution — DDU scaffold.

Implements:
- GET /healthz
- GET /versionz
- Lineage emitter wiring (best-effort)
"""
from __future__ import annotations

import logging
import os

import uvicorn

from ddu_common.app import build_scaffold_app
from ddu_common.version import ServiceVersion, from_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ddu-resolution")

VERSION = from_env(ServiceVersion(
    service="ddu-resolution",
    service_version="0.0.1-dev",
    tool="splink",
    tool_version="4.0.0",
))

app = build_scaffold_app(VERSION)


def main() -> None:
    port = int(os.environ.get("PORT", 8106))
    log.info("ddu-resolution listening on :%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
