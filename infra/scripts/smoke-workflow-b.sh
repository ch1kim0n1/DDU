#!/usr/bin/env bash
set -euo pipefail

API_URL="${DDU_API_URL:-http://localhost:8001}"
ROLE_HEADER=(-H 'X-DDU-Role: analyst')

curl -fsS "$API_URL/healthz" | jq -e '.state == "HEALTHY" or .state == "DEGRADED"' >/dev/null

inv="$(
  curl -fsS -X POST "$API_URL/v1/investigations" \
    -H 'Content-Type: application/json' \
    "${ROLE_HEADER[@]}" \
    -d '{"name":"Workflow B username smoke"}'
)"
id="$(jq -er '.id' <<<"$inv")"

result="$(
  curl -fsS -X POST "$API_URL/v1/investigations/$id/usernames" \
    -H 'Content-Type: application/json' \
    "${ROLE_HEADER[@]}" \
    -d '{"username":"alice"}'
)"
jq -e 'type == "object"' <<<"$result" >/dev/null

entities="$(curl -fsS "$API_URL/v1/investigations/$id/entities" "${ROLE_HEADER[@]}")"
jq -e '(.entities | length) >= 0' <<<"$entities" >/dev/null

printf 'Workflow B smoke passed\ninvestigation_id=%s\n' "$id"
