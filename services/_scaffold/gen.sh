#!/usr/bin/env bash
# Generate a Go service scaffold from _scaffold/main.go.tmpl.
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

if [[ -e "$DEST/main.go" ]]; then
  echo "refusing to overwrite $DEST/main.go" >&2
  exit 1
fi

mkdir -p "$DEST"

sed -e "s/__SERVICE_NAME__/$SERVICE/g" \
    -e "s/__DEFAULT_PORT__/$PORT/g" \
    "$SCRIPT_DIR/main.go.tmpl" > "$DEST/main.go"

cat > "$DEST/go.mod" <<EOF
module github.com/ddu/$SERVICE

go 1.22

require github.com/ddu/ddu-lineage-emitter v0.0.0
EOF

# Replace ddu-lineage-emitter with a relative replace for dev.
echo "" >> "$DEST/go.mod"
echo "replace github.com/ddu/ddu-lineage-emitter => ../../libs/ddu-lineage-emitter" >> "$DEST/go.mod"

cat > "$DEST/Dockerfile" <<EOF
FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /out/$SERVICE ./...

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=build /out/$SERVICE /usr/local/bin/$SERVICE
ENTRYPOINT ["/usr/local/bin/$SERVICE"]
EOF

cat > "$DEST/README.md" <<EOF
# $SERVICE

Scaffold. Implements:
- \`GET /healthz\` — health probe
- \`GET /versionz\` — service + tool + model version
- Lineage emitter wiring (best-effort)

## Run

\`\`\`bash
go run . -port $PORT
\`\`\`

Environment:
- \`PORT\` — listen port (default $PORT)
- \`OPENLINEAGE_URL\` — OpenLineage backend URL
- \`OPENLINEAGE_NAMESPACE\` — job namespace (default \`ddu.dev\`)
EOF

echo "created $DEST"
