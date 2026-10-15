#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEST="${1:?usage: fetch_binding_sdists.sh DESTINATION}"

if [[ -z "${PIP_INDEX_URL:-}" ]]; then
  echo "PIP_INDEX_URL must point to the approved internal package feed" >&2
  exit 2
fi

mkdir -p "$DEST"
"${PYTHON:-python3}" -m pip download \
  --isolated \
  --index-url "$PIP_INDEX_URL" \
  --no-deps \
  --no-binary=:all: \
  --require-hashes \
  --dest "$DEST" \
  -r "$ROOT/requirements-sdists.txt"
