#!/bin/bash

echo "[CONTAINER-ENTRYPOINT] Starting container execution"
echo "[CONTAINER-ENTRYPOINT] Working directory: $(pwd)"
echo "[CONTAINER-ENTRYPOINT] Python path: $PYTHONPATH"
echo "[CONTAINER-ENTRYPOINT] Command to execute: $*"

# Set up environment
export PYTHONPATH=/app:$PYTHONPATH
echo "[CONTAINER-ENTRYPOINT] Updated PYTHONPATH: $PYTHONPATH"

# Store the original working directory (task directory)
TASK_DIR=$(pwd)
echo "[CONTAINER-ENTRYPOINT] Task directory: $TASK_DIR"

# IMPORTANT: Stay in the task directory! The environment variables like INPUT_DIR
# are relative paths that expect the task directory as the working directory.
# The PYTHONPATH is set to /app so imports will still work.
echo "[CONTAINER-ENTRYPOINT] Staying in task directory for relative paths to work"

# List contents for debugging
echo "[CONTAINER-ENTRYPOINT] Contents of /app:"
ls -la /app/

echo "[CONTAINER-ENTRYPOINT] Contents of /app/hastegeo:"
ls -la /app/hastegeo/

echo "[CONTAINER-ENTRYPOINT] Current working directory: $(pwd)"
echo "[CONTAINER-ENTRYPOINT] Contents of current directory:"
ls -la "$(pwd)/" || echo "Current directory not accessible"

# Also show inputs directory contents if it exists
if [ -d "inputs" ]; then
    echo "[CONTAINER-ENTRYPOINT] Contents of inputs directory:"
    ls -la "inputs/"
    echo "[CONTAINER-ENTRYPOINT] Recursive inputs listing (first 20):"
    find "inputs" -type f | head -20
fi

echo "[CONTAINER-ENTRYPOINT] Python version:"
python --version

echo "[CONTAINER-ENTRYPOINT] Testing haste import:"
python -c "import hastegeo.workflows.prepare_imagery; print('Successfully imported prepare_imagery')" 2>&1

# Execute the provided command, but with proper working directory handling
echo "[CONTAINER-ENTRYPOINT] Executing command: $*"

# If the command contains directory changes, we need to handle them carefully
# The command might try to cd to the task directory, which we need to allow
FULL_COMMAND="$*"
echo "[CONTAINER-ENTRYPOINT] Full command: $FULL_COMMAND"

# Execute using bash so directory changes work properly
exec /bin/bash -c "$FULL_COMMAND"
