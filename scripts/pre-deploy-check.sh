#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() { echo "pre-deploy-check FAILED: $*" >&2; exit 1; }

[[ "${MIRROR_ENV:-}" == "production" ]] || fail "MIRROR_ENV must be production"
[[ "${MIRROR_IDENTITY_REQUIRED:-}" == "1" || "${MIRROR_IDENTITY_REQUIRED:-}" == "true" ]] || fail "MIRROR_IDENTITY_REQUIRED must be true"
[[ -n "${MIRROR_REDIS_URL:-}" ]] || fail "MIRROR_REDIS_URL is required"
[[ -n "${MIRROR_SESSION_ENCRYPTION_KEY:-}" ]] || fail "MIRROR_SESSION_ENCRYPTION_KEY is required"
[[ "${#MIRROR_SESSION_ENCRYPTION_KEY}" -ge 32 ]] || fail "MIRROR_SESSION_ENCRYPTION_KEY must be at least 32 characters"
[[ -n "${MIRROR_UI_ORIGIN_REGEX:-}" ]] || fail "MIRROR_UI_ORIGIN_REGEX is required"
[[ "${MIRROR_UI_ORIGIN_REGEX}" != *localhost* ]] || fail "MIRROR_UI_ORIGIN_REGEX must not contain localhost in production"
[[ -f infra/Caddyfile ]] || fail "infra/Caddyfile missing"
if command -v caddy >/dev/null 2>&1; then
  caddy validate --config infra/Caddyfile || fail "Caddyfile invalid"
else
  echo "caddy not installed locally; skipping caddy validate"
fi
docker compose -f infra/docker-compose.prod.yml config --quiet || fail "compose config invalid"
docker images | grep -q ddu-ui || echo "WARN: ddu-ui image not found locally (build before deploy)"
docker images | grep -q ddu-mirror-intel || echo "WARN: ddu-mirror-intel image not found locally (build before deploy)"
echo "pre-deploy-check ok"
