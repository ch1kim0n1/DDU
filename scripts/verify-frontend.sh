#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../ui/ddu-ui"
npx tsc --noEmit
npm run build
npm test
test -f dist/index.html
ls dist/assets/*.js >/dev/null
ls dist/assets/*.css >/dev/null
echo "verify-frontend ok"
