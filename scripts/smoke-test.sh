#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export MIRROR_RATE_LIMIT=0
export MIRROR_ENV=development

python services/ddu-mirror-intel/app.py &
PID=$!
trap 'kill $PID 2>/dev/null || true' EXIT

for _ in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8120/healthz >/dev/null; then break; fi
  sleep 1
done
curl -sf http://127.0.0.1:8120/healthz | grep -E 'HEALTHY|DEGRADED'

SESSION=$(curl -sf -X POST http://127.0.0.1:8120/intel/session \
  -H 'content-type: application/json' \
  -d '{"session_id":"smoke_test","emails":["test@ddu.local"],"handles":["test"],"persona":"scammer","seed_mock_findings":true}')
SID=$(python -c 'import json,sys; print(json.load(sys.stdin)["session_id"])' <<<"$SESSION")
test -n "$SID"
echo "$SESSION" | grep -q findings

curl -sf -X POST http://127.0.0.1:8120/intel/scan/plan \
  -H 'content-type: application/json' \
  -d "{\"session_id\":\"$SID\",\"state\":\"TX\",\"county\":\"Travis\"}" | grep -q proposals

curl -sf -X DELETE "http://127.0.0.1:8120/intel/session/$SID" >/dev/null
CODE=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:8120/intel/session/$SID" || true)
test "$CODE" = "404"

echo "smoke-test ok"
