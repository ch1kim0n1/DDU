#!/usr/bin/env bash
# Start DDU services as host processes against Tier 1 compose backends.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOGDIR="${DDU_LOG_DIR:-/tmp/ddu-stack-logs}"
mkdir -p "$LOGDIR"
VENV="${DDU_PYTHON:-$ROOT/.venv/bin/python}"
export MODEL_MODE="${MODEL_MODE:-stub}"
export OPENLINEAGE_URL="${OPENLINEAGE_URL:-http://localhost:8006}"
export AUTH_MODE="${AUTH_MODE:-dev}"
export DDU_ALLOW_ROLE_HEADER="${DDU_ALLOW_ROLE_HEADER:-true}"
export MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://localhost:9000}"
export MINIO_ACCESS_KEY="${MINIO_ACCESS_KEY:-dduadmin}"
export MINIO_SECRET_KEY="${MINIO_SECRET_KEY:-ddudevpass}"

start_go() {
  local name=$1 dir=$2; shift 2
  (cd "$ROOT/services/$dir" && env "$@" go run .) >"$LOGDIR/$name.log" 2>&1 &
  echo "started $name pid=$! log=$LOGDIR/$name.log"
}
start_py() {
  local name=$1 dir=$2; shift 2
  (cd "$ROOT/services/$dir" && env "$@" "$VENV" app.py) >"$LOGDIR/$name.log" 2>&1 &
  echo "started $name pid=$! log=$LOGDIR/$name.log"
}

start_go lineage ddu-lineage OPENLINEAGE_URL=http://localhost:5002
sleep 1
start_go storage ddu-storage OPENLINEAGE_URL=$OPENLINEAGE_URL MINIO_ENDPOINT=$MINIO_ENDPOINT MINIO_ACCESS_KEY=$MINIO_ACCESS_KEY MINIO_SECRET_KEY=$MINIO_SECRET_KEY
start_go graph ddu-graph-store OPENLINEAGE_URL=$OPENLINEAGE_URL NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=${NEO4J_PASSWORD:-ddudevpass}
start_go vector ddu-vector OPENLINEAGE_URL=$OPENLINEAGE_URL QDRANT_URL=http://localhost:6333
sleep 1
start_go ingest ddu-ingest OPENLINEAGE_URL=$OPENLINEAGE_URL DDU_STORAGE_URL=http://localhost:8003
start_go webcapture ddu-webcapture OPENLINEAGE_URL=$OPENLINEAGE_URL DDU_STORAGE_URL=http://localhost:8003
start_go collector ddu-collector OPENLINEAGE_URL=$OPENLINEAGE_URL DDU_STORAGE_URL=http://localhost:8003
start_go discovery ddu-discovery OPENLINEAGE_URL=$OPENLINEAGE_URL
start_py vision ddu-vision MODEL_MODE=$MODEL_MODE OPENLINEAGE_URL=$OPENLINEAGE_URL
start_py face ddu-face MODEL_MODE=$MODEL_MODE OPENLINEAGE_URL=$OPENLINEAGE_URL
start_py ocr ddu-ocr MODEL_MODE=$MODEL_MODE OPENLINEAGE_URL=$OPENLINEAGE_URL
start_py audio ddu-audio MODEL_MODE=$MODEL_MODE OPENLINEAGE_URL=$OPENLINEAGE_URL
start_py geo ddu-geo MODEL_MODE=$MODEL_MODE OPENLINEAGE_URL=$OPENLINEAGE_URL
start_py ontology ddu-ontology OPENLINEAGE_URL=$OPENLINEAGE_URL
start_py temporal ddu-temporal OPENLINEAGE_URL=$OPENLINEAGE_URL
start_py agent ddu-agent OPENLINEAGE_URL=$OPENLINEAGE_URL
start_py osint ddu-osint OPENLINEAGE_URL=$OPENLINEAGE_URL
start_py resolution ddu-resolution OPENLINEAGE_URL=$OPENLINEAGE_URL
start_py intel ddu-intel OPENLINEAGE_URL=$OPENLINEAGE_URL
sleep 2
start_go api ddu-api OPENLINEAGE_URL=$OPENLINEAGE_URL AUTH_MODE=$AUTH_MODE DDU_ALLOW_ROLE_HEADER=$DDU_ALLOW_ROLE_HEADER
echo "dev-services launched; check $LOGDIR and curl :8001/healthz"
