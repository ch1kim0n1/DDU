#!/usr/bin/env bash
set -euo pipefail

API_URL="${DDU_API_URL:-http://localhost:8001}"
ROLE_HEADER=(-H 'X-DDU-Role: analyst')
AUTH_HEADER=(-H 'X-DDU-Authorization-Purpose: authorized-investigation')

curl -fsS "$API_URL/healthz" | jq -e '.state == "HEALTHY" or .state == "DEGRADED"' >/dev/null

inv="$(
  curl -fsS -X POST "$API_URL/v1/investigations" \
    -H 'Content-Type: application/json' \
    "${ROLE_HEADER[@]}" \
    -d '{"name":"Post-MVP intel smoke"}'
)"
id="$(jq -er '.id' <<<"$inv")"

# Seed some graph state via username workflow
curl -fsS -X POST "$API_URL/v1/investigations/$id/usernames" \
  -H 'Content-Type: application/json' \
  "${ROLE_HEADER[@]}" \
  -d '{"username":"alice"}' >/dev/null

features=(
  location/current
  household
  property
  identity/resolve
  pattern-of-life
  temporal/diff
  social-circle
  location/history
  aliases
  records/fuse
  relationship/strength
  life-events
  employment
  assets
  location/fuse
)

for feature in "${features[@]}"; do
  curl -fsS -X POST "$API_URL/v1/investigations/$id/intel/$feature" \
    -H 'Content-Type: application/json' \
    "${ROLE_HEADER[@]}" \
    "${AUTH_HEADER[@]}" \
    -d '{"subject":"alice","authorization_purpose":"authorized-investigation"}' \
    | jq -e 'type == "object"' >/dev/null
  echo "ok $feature"
done

curl -fsS -X POST "$API_URL/v1/investigations/$id/intel/web-history" \
  -H 'Content-Type: application/json' \
  "${ROLE_HEADER[@]}" \
  "${AUTH_HEADER[@]}" \
  -d '{"subject":"alice","authorization_purpose":"authorized-investigation","url":"https://example.com/profile"}' \
  | jq -e '.capture.id and .change_event.id' >/dev/null
echo "ok web-history"

curl -fsS "$API_URL/v1/investigations/$id/intel/scene/3d" "${ROLE_HEADER[@]}" \
  | jq -e '.nodes != null and .edges != null' >/dev/null
echo "ok scene/3d"

curl -fsS "$API_URL/v1/investigations/$id/intel/playback" "${ROLE_HEADER[@]}" \
  | jq -e '.frames | length >= 1' >/dev/null
echo "ok playback"

# High-risk gate without purpose header must fail
code="$(
  curl -s -o /dev/null -w '%{http_code}' -X POST \
    "$API_URL/v1/investigations/$id/intel/household" \
    -H 'Content-Type: application/json' \
    "${ROLE_HEADER[@]}" \
    -d '{"subject":"alice"}'
)"
[[ "$code" == "403" ]] || { echo "expected 403 for ungated household, got $code" >&2; exit 1; }
echo "ok high-risk gate"

printf 'Post-MVP intel smoke passed\ninvestigation_id=%s\n' "$id"
