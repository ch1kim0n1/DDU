#!/usr/bin/env bash
set -euo pipefail

API_URL="${DDU_API_URL:-http://localhost:8001}"
UI_URL="${DDU_UI_URL:-http://localhost:5173}"

for command in curl jq openssl; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "missing required command: $command" >&2
    exit 1
  fi
done

workspace="$(mktemp -d)"
trap 'rm -rf "$workspace"' EXIT
image="$workspace/smoke.png"
printf '%s' 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=' \
  | openssl base64 -d -A >"$image"

ROLE_HEADER=(-H 'X-DDU-Role: analyst')
curl -fsS "$API_URL/healthz" | jq -e '.state == "HEALTHY" or .state == "DEGRADED"' >/dev/null

investigation="$(
  curl -fsS -X POST "$API_URL/v1/investigations" \
    -H 'Content-Type: application/json' \
    "${ROLE_HEADER[@]}" \
    -d '{"name":"Workflow A smoke test"}'
)"
investigation_id="$(jq -er '.id' <<<"$investigation")"

workflow="$(
  curl -fsS -X POST \
    "$API_URL/v1/investigations/$investigation_id/images" \
    "${ROLE_HEADER[@]}" \
    -F "file=@$image;type=image/png"
)"
evidence_id="$(jq -er '.evidence_id' <<<"$workflow")"
jq -e '.entities | length > 0' <<<"$workflow" >/dev/null

entities="$(curl -fsS "$API_URL/v1/investigations/$investigation_id/entities")"
jq -e '
  (.entities | length > 0) and
  any(.entities[]; .type == "ENTITY_TYPE_OBSERVATION")
' <<<"$entities" >/dev/null

lineage="$(curl -fsS "$API_URL/v1/investigations/$investigation_id/lineage")"
jq -e '(.count > 0) and (.runs | length > 0)' <<<"$lineage" >/dev/null

curl -fsS \
  "$API_URL/v1/investigations/$investigation_id/evidence/$evidence_id" \
  | jq -e '.download_url | length > 0' >/dev/null
curl -fsS "$UI_URL" >/dev/null

printf 'Workflow A smoke passed\ninvestigation_id=%s\nevidence_id=%s\n' \
  "$investigation_id" "$evidence_id"
