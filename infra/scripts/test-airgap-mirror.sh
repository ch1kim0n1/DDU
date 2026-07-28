#!/usr/bin/env bash
# Test script for air-gap mirror functionality.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEST_DIR="$ROOT/airgap-test"
COMPOSE_FILE="$ROOT/docker-compose.yml"

cleanup() {
  echo "Cleaning up test directory: $TEST_DIR"
  rm -rf "$TEST_DIR"
}
trap cleanup EXIT

echo "=== Air-Gap Mirror Test ==="
echo "Test directory: $TEST_DIR"
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

# Test 5: Verify image format
while IFS= read -r image; do
  [[ -z "$image" ]] && continue
  if ! [[ "$image" =~ ^[a-z0-9]+(\.[a-z0-9]+)*(/[a-z0-9]+([-_.][a-z0-9]+)*)*(:[a-z0-9]+([-_.][a-z0-9]+)*)?$ ]]; then
    echo "FAIL: Invalid image format: $image"
    exit 1
  fi
done <<< "$images"
echo "PASS: All image formats are valid"

# Test 6: Verify mirror script creates expected output
mkdir -p "$TEST_DIR"
if ! bash "$ROOT/infra/scripts/airgap-mirror.sh" "$TEST_DIR" 2>&1 | head -10; then
  echo "FAIL: Mirror script execution failed"
  exit 1
fi
echo "PASS: Mirror script executed successfully"

# Test 7: Verify tar files were created
tar_count=$(find "$TEST_DIR" -name "*.tar" | wc -l | tr -d ' ')
if [[ "$tar_count" -ne "$count" ]]; then
  echo "FAIL: Expected $count tar files, found $tar_count"
  exit 1
fi
echo "PASS: Correct number of tar files created ($tar_count)"

# Test 8: Verify load script was created
if [[ ! -f "$TEST_DIR/load.sh" ]]; then
  echo "FAIL: load.sh script not created"
  exit 1
fi
echo "PASS: load.sh script created"

# Test 9: Verify load script is executable
if [[ ! -x "$TEST_DIR/load.sh" ]]; then
  echo "FAIL: load.sh script is not executable"
  exit 1
fi
echo "PASS: load.sh script is executable"

# Test 10: Verify load script content
if ! grep -q "docker load" "$TEST_DIR/load.sh"; then
  echo "FAIL: load.sh script does not contain expected docker load command"
  exit 1
fi
echo "PASS: load.sh script contains expected commands"

# Test 11: Verify tar file naming
while IFS= read -r image; do
  [[ -z "$image" ]] && continue
  safe="$(printf '%s' "$image" | tr '/:' '__')"
  if [[ ! -f "$TEST_DIR/${safe}.tar" ]]; then
    echo "FAIL: Expected tar file not found: ${safe}.tar"
    exit 1
  fi
done <<< "$images"
echo "PASS: All tar files have correct naming"

# Test 12: Verify tar file integrity (check if they're valid tar files)
while IFS= read -r tar; do
  [[ -z "$tar" ]] && continue
  if ! tar -tf "$tar" > /dev/null 2>&1; then
    echo "FAIL: Invalid tar file: $tar"
    exit 1
  fi
done < <(find "$TEST_DIR" -name "*.tar")
echo "PASS: All tar files are valid"

echo ""
echo "=== All Air-Gap Mirror Tests Passed ==="
echo "Test directory: $TEST_DIR (will be cleaned up on exit)"