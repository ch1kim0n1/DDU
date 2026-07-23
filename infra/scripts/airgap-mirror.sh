#!/usr/bin/env bash
# Phase 3: export/import pinned Tier 1 images for air-gapped installs.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/airgap-images}"
COMPOSE_FILE="$ROOT/docker-compose.yml"

mkdir -p "$OUT"
images="$(docker compose -f "$COMPOSE_FILE" config --images | sort -u)"
if [[ -z "$images" ]]; then
  echo "No images discovered from compose config" >&2
  exit 1
fi

count="$(printf '%s\n' "$images" | wc -l | tr -d ' ')"
echo "Mirroring $count images into $OUT"
while IFS= read -r image; do
  [[ -z "$image" ]] && continue
  safe="$(printf '%s' "$image" | tr '/:' '__')"
  echo "-> $image"
  docker pull "$image"
  docker save "$image" -o "$OUT/${safe}.tar"
done <<< "$images"

cat >"$OUT/load.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
for tar in "$DIR"/*.tar; do
  echo "Loading $tar"
  docker load -i "$tar"
done
EOF
chmod +x "$OUT/load.sh"
echo "Done. Transfer $OUT and run ./load.sh on the air-gapped host."
