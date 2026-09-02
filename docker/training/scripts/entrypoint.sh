#!/bin/bash

set -euo pipefail

# Ensure files written by training (checkpoints, logs, etc.) are readable
# by the queue-worker process (different UID) that uploads them to blob storage.
umask 0022

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

/bin/bash -c "$FULL_COMMAND"
EXIT_CODE=$?

# Ensure all output files (especially checkpoints) are world-readable so the
# queue-worker process (different UID) can upload them to blob storage.
# PyTorch Lightning may write checkpoint files with restrictive permissions
# before chmod-ing them, creating a brief window where they're unreadable.
#
# HASTE_JOB_WORKDIR is the provider-neutral canonical working-directory
# variable; AZ_BATCH_TASK_WORKING_DIR is the legacy Azure Batch alias, kept
# for already-published images and not-yet-migrated adapters. This entrypoint
# runs in a separate process from the `bash -c "$FULL_COMMAND"` subshell
# above, so it cannot see exports made inside that subshell (e.g. by
# set_dirs.sh) and must resolve directly from its own environment.
JOB_WORKDIR="${HASTE_JOB_WORKDIR:-${AZ_BATCH_TASK_WORKING_DIR:-}}"
if [ -n "$JOB_WORKDIR" ]; then
    chmod -R o+rX "$JOB_WORKDIR" 2>/dev/null || true
fi

exit $EXIT_CODE
