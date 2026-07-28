#!/usr/bin/env bash
# Generate a Python service scaffold.
# Usage: ./gen.sh <service_name> <default_port> <tool> <tool_version>
set -euo pipefail

SERVICE="$1"
PORT="$2"
TOOL="${3:-}"
TOOL_VERSION="${4:-}"

if [[ -z "$SERVICE" || -z "$PORT" ]]; then
  echo "usage: $0 <service_name> <default_port> [tool] [tool_version]" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEST="$ROOT/services/$SERVICE"

if [[ -e "$DEST/app.py" ]]; then
  echo "refusing to overwrite $DEST/app.py" >&2
  exit 1
fi

mkdir -p "$DEST"

cat > "$DEST/app.py" <<EOF
"""$SERVICE — DDU scaffold.

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
log = logging.getLogger("$SERVICE")

VERSION = from_env(ServiceVersion(
    service="$SERVICE",
    service_version="0.0.1-dev",
    tool="$TOOL",
    tool_version="$TOOL_VERSION",
))

app = build_scaffold_app(VERSION)


def main() -> None:
    port = int(os.environ.get("PORT", $PORT))
    log.info("$SERVICE listening on :%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
EOF

cat > "$DEST/pyproject.toml" <<EOF
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "$SERVICE"
version = "0.0.1"
description = "DDU $SERVICE service"
requires-python = ">=3.11"
dependencies = [
    "ddu-py-common",
    "fastapi>=0.110",
    "uvicorn[standard]>=0.30",
]

[tool.setuptools]
py-modules = ["app"]
EOF

cat > "$DEST/Dockerfile" <<EOF
FROM python:3.11-slim AS base
WORKDIR /app

# Install ddu-py-common from the libs directory.
COPY libs/ddu-py-common /opt/ddu-py-common
RUN pip install --no-cache-dir /opt/ddu-py-common

COPY services/$SERVICE /app
RUN pip install --no-cache-dir /app

ENV PORT=$PORT
EXPOSE $PORT
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "$PORT"]
EOF

cat > "$DEST/README.md" <<EOF
# $SERVICE

Scaffold. Implements:
- \`GET /healthz\`
- \`GET /versionz\`
- Lineage emitter wiring (best-effort)

## Run

\`\`\`bash
pip install -e ../../libs/ddu-py-common
pip install -e .
python app.py
\`\`\`

Environment:
- \`PORT\` — listen port (default $PORT)
- \`OPENLINEAGE_URL\` — OpenLineage backend URL
- \`OPENLINEAGE_NAMESPACE\` — job namespace (default \`ddu.dev\`)
- \`DDU_*\` — version overrides
EOF

echo "created $DEST"
