#!/usr/bin/env bash
# Quick test script for air-gap mirror functionality (without actually pulling images).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$ROOT/docker-compose.yml"

echo "=== Air-Gap Mirror Quick Test ==="
echo "Compose file: $COMPOSE_FILE"

# Test 1: Verify compose file exists
if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "FAIL: Compose file not found at $COMPOSE_FILE"
  exit 1
fi
echo "PASS: Compose file exists"

# Test 2: Verify compose config is valid
if ! docker compose -f "$COMPOSE_FILE" config --quiet; then
  echo "FAIL: Compose config validation failed"
  exit 1
fi
echo "PASS: Compose config is valid"

# Test 3: Verify images can be extracted
images="$(docker compose -f "$COMPOSE_FILE" config --images | sort -u)"
if [[ -z "$images" ]]; then
  echo "FAIL: No images discovered from compose config"
  exit 1
fi
echo "PASS: Images discovered from compose config"

# Test 4: Count images
count="$(printf '%s\n' "$images" | wc -l | tr -d ' ')"
echo "INFO: Found $count unique images"
if [[ "$count" -lt 1 ]]; then
  echo "FAIL: Expected at least 1 image, found $count"
  exit 1
fi
echo "PASS: Image count is valid ($count images)"

# Test 5: Verify image format (more lenient pattern for various tag formats)
while IFS= read -r image; do
  [[ -z "$image" ]] && continue
  if ! [[ "$image" =~ ^[a-z0-9]+(\.[a-z0-9]+)*(/[a-z0-9]+([-_.][a-z0-9]+)*)*(:[a-zA-Z0-9]+([-_.:+][a-zA-Z0-9]+)*)?$ ]]; then
    echo "FAIL: Invalid image format: $image"
    exit 1
  fi
done <<< "$images"
echo "PASS: All image formats are valid"

# Test 6: Display discovered images
echo "INFO: Discovered images:"
while IFS= read -r image; do
  [[ -z "$image" ]] && continue
  echo "  - $image"
done <<< "$images"

# Test 7: Verify mirror script exists
mirror_script="$SCRIPT_DIR/airgap-mirror.sh"
if [[ ! -f "$mirror_script" ]]; then
  echo "FAIL: Mirror script not found at $mirror_script"
  exit 1
fi
echo "PASS: Mirror script exists"

# Test 8: Verify mirror script is executable
if [[ ! -x "$mirror_script" ]]; then
  echo "FAIL: Mirror script is not executable"
  exit 1
fi
echo "PASS: Mirror script is executable"

# Test 9: Verify mirror script syntax
if ! bash -n "$mirror_script"; then
  echo "FAIL: Mirror script has syntax errors"
  exit 1
fi
echo "PASS: Mirror script syntax is valid"

echo ""
echo "=== All Air-Gap Mirror Quick Tests Passed ==="
echo "Note: Run test-airgap-mirror.sh for full integration test (pulls images)"