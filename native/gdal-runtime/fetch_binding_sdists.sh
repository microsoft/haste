#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEST="${1:?usage: fetch_binding_sdists.sh DESTINATION}"

PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"

mkdir -p "$DEST"
"${PYTHON:-python3}" -m pip download \
  --isolated \
  --index-url "$PIP_INDEX_URL" \
  --no-build-isolation \
  --no-deps \
  --no-binary=:all: \
  --require-hashes \
  --dest "$DEST" \
  -r "$ROOT/requirements-sdists.txt"
