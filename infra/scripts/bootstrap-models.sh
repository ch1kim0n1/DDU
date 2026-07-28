#!/usr/bin/env bash
# Bootstrap pinned model manifests into MinIO ddu-models.
# Full weight downloads are opt-in (--download) because they are multi-GB.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://localhost:9000}"
MINIO_ACCESS_KEY="${MINIO_ACCESS_KEY:-dduadmin}"
MINIO_SECRET_KEY="${MINIO_SECRET_KEY:-ddudevpass}"
DOWNLOAD=0
for arg in "$@"; do
  [[ "$arg" == "--download" ]] && DOWNLOAD=1
done

if ! command -v mc >/dev/null 2>&1; then
  echo "mc (MinIO client) required" >&2
  exit 1
fi

mc alias set ddu "$MINIO_ENDPOINT" "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" >/dev/null
mc mb -p ddu/ddu-models >/dev/null || true

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

write_manifest() {
  local service="$1" model="$2" version="$3" source_url="$4" license="$5"
  local dir="$workdir/$service/$model/$version"
  mkdir -p "$dir"
  cat >"$dir/manifest.json" <<EOF
{
  "service": "$service",
  "model_name": "$model",
  "model_version": "$version",
  "files": [],
  "source_url": "$source_url",
  "license": "$license",
  "downloaded_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "downloaded_by": "infra/scripts/bootstrap-models.sh",
  "status": "$([ "$DOWNLOAD" -eq 1 ] && echo downloaded || echo manifest-only)"
}
EOF
  mc cp "$dir/manifest.json" "ddu/ddu-models/$service/$model/$version/manifest.json" >/dev/null
  echo "ok $service/$model/$version"
}

write_manifest ddu-vision grounded-sam-2 0.4.0 \
  "https://huggingface.co/IDEA-Research/grounded-sam-2" "Apache-2.0"
write_manifest ddu-ocr pp-ocrv4 2.7.0 \
  "https://github.com/PaddlePaddle/PaddleOCR" "Apache-2.0"
write_manifest ddu-audio whisper-large-v3 3.0.0 \
  "https://huggingface.co/openai/whisper-large-v3" "MIT"
write_manifest ddu-geo geoclip 1.0.0 \
  "https://github.com/VicenteVivan/geo-clip" "MIT"
write_manifest ddu-face compreface-arcface 1.2.0 \
  "https://github.com/exadel-inc/CompreFace" "Apache-2.0"

if [[ "$DOWNLOAD" -eq 1 ]]; then
  echo "Weight download not automated in this environment (multi-GB)."
  echo "Place files under s3://ddu-models/<service>/<model>/<version>/ and update manifest files[]."
else
  echo "Wrote manifests only. Re-run with --download after wiring source fetchers."
fi

echo "bootstrap-models complete"
