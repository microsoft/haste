#!/bin/bash

set -euo pipefail

# Helpful diagnostics to match imagery prep behavior
echo "[TRAINING-ENTRYPOINT] Starting container execution"
echo "[TRAINING-ENTRYPOINT] Working directory: $(pwd)"
echo "[TRAINING-ENTRYPOINT] PYTHONPATH: ${PYTHONPATH:-}"
echo "[TRAINING-ENTRYPOINT] Args: $*"

# Ensure haste source is importable
export PYTHONPATH="/app:${PYTHONPATH:-}"
echo "[TRAINING-ENTRYPOINT] Updated PYTHONPATH: $PYTHONPATH"

TASK_DIR=$(pwd)
echo "[TRAINING-ENTRYPOINT] Task directory: $TASK_DIR"

cd /app

echo "[TRAINING-ENTRYPOINT] Contents of /app:"
ls -la /app

echo "[TRAINING-ENTRYPOINT] Contents of /app/hastegeo:"
ls -la /app/hastegeo || echo "[TRAINING-ENTRYPOINT] hastegeo package missing"

echo "[TRAINING-ENTRYPOINT] Python version:"
python --version

echo "[TRAINING-ENTRYPOINT] Verifying training workflow import"
python -c "import hastegeo" 2>&1 || echo "[TRAINING-ENTRYPOINT] Failed to import base hastegeo package"

# When no command is provided (e.g. compose build helper), drop into bash to avoid exiting with an error
if [ $# -eq 0 ]; then
    echo "[TRAINING-ENTRYPOINT] No command supplied; starting interactive shell"
    exec /bin/bash
fi

FULL_COMMAND="$*"
echo "[TRAINING-ENTRYPOINT] Executing command via /bin/bash -c: $FULL_COMMAND"

exec /bin/bash -c "$FULL_COMMAND"
