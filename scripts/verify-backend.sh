#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export MIRROR_RATE_LIMIT=0
export MIRROR_ENV=development

pip install -e libs/ddu-py-common
pip install -e services/ddu-mirror-intel
python -c "import sys; sys.path.insert(0, 'services/ddu-mirror-intel'); import app; print(app.VERSION.service)"
python -m pytest services/ddu-mirror-intel -q
if command -v ruff >/dev/null 2>&1; then
  ruff check services/ddu-mirror-intel
else
  echo "ruff not installed; skipping lint (install ruff for full gate)"
fi
echo "verify-backend ok"
