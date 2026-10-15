#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV="${1:?usage: install_build_tools.sh VENV [requirements-file]}"
REQUIREMENTS="${2:-$ROOT/requirements-build.txt}"

if [[ -z "${PIP_INDEX_URL:-}" ]]; then
  echo "PIP_INDEX_URL must point to the approved internal package feed" >&2
  exit 2
fi

PYTHON="${PYTHON:-python3}"
"$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install \
  --isolated \
  --index-url "$PIP_INDEX_URL" \
  --only-binary=:all: \
  --require-hashes \
  -r "$REQUIREMENTS"
