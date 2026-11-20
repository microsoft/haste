#!/usr/bin/env bash
set -euo pipefail

wheels="$RUNNER_TEMP/candidate-wheels"
evidence="$RUNNER_TEMP/sqlite-evidence"
mkdir -p "$evidence"
(
  cd "$wheels"
  sha256sum --check SHA256SUMS
  grep -Fx '7f6b2e18f1489af5ea08bb635d86da81cb462c21176bdb2f802b1066c62ca394  haste_gdal_runtime-3.13.3+haste.2-py3-none-manylinux_2_28_x86_64.whl' SHA256SUMS
)
cp "$wheels/SHA256SUMS" "$evidence/"
cp native/gdal-runtime/inspect_sqlite_archives.py "$RUNNER_TEMP/"
cp .github/scripts/prepare_training_runtime_env.py "$RUNNER_TEMP/"
cd worker-source
git rev-parse HEAD | tee "$evidence/worker-source.txt"
mkdir candidate-runtime-wheels
cp "$wheels"/*.whl candidate-runtime-wheels/

case "$WORKER" in
  imageryprep)
    pins=docker/imageryprep/requirements.txt
    marker='COPY --chown=appuser:appgroup docker/imageryprep/requirements.txt /app/'
    workload='prepare-imagery --help && python -m unittest discover -s /imagery-tests -p test_imagery_runtime.py -v && python /verification/verify_worker_sqlite.py'
    ;;
  training)
    pins=docker/training/env/env.yml
    marker='COPY docker/training/env/env.yml /tmp/env.yml'
    workload='python run_workflow.py --help && python -m unittest discover -s /app/tests -p test_gdal_runtime_integration.py -v && python /verification/verify_worker_sqlite.py'
    ;;
  *) exit 2 ;;
esac
dockerfile="docker/$WORKER/Dockerfile"
base=$(awk 'toupper($1) == "FROM" { base=$2 } END { print base }' "$dockerfile")
python "$RUNNER_TEMP/prepare_training_runtime_env.py" \
  "$pins" "$wheels" "$RUNNER_TEMP/worker-pins" --candidate-build 2
sed "s|file://$wheels/|file:///candidate-runtime-wheels/|g" \
  "$RUNNER_TEMP/worker-pins" > "$pins"
grep -q -Fx "$marker" "$dockerfile"
awk -v marker="$marker" '
  $0 == marker { print "COPY candidate-runtime-wheels/ /candidate-runtime-wheels/" }
  {print}
' "$dockerfile" > "$RUNNER_TEMP/worker.Dockerfile"

docker pull "$base"
base_container=$(docker create "$base")
worker_container=
cleanup() {
  docker rm "$base_container" >/dev/null
  if [[ -n "$worker_container" ]]; then docker rm "$worker_container" >/dev/null; fi
}
trap cleanup EXIT
docker cp -L "$base_container:/opt/miniconda/bin/sqlite3" "$RUNNER_TEMP/base-sqlite3"
python - "$RUNNER_TEMP" <<'PY'
import sys
import zipfile
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from inspect_sqlite_archives import inspect_archive

path = root / "positive-control.zip"
with zipfile.ZipFile(path, "w") as archive:
    archive.write(root / "base-sqlite3", "renamed-shell")
assert inspect_archive(path)["sqlite_shell_fingerprint_matches"] == ["renamed-shell"]
print("Renamed-shell positive control detected in the actual worker base binary")
PY

docker build --file "$RUNNER_TEMP/worker.Dockerfile" --tag sqlite-worker-evidence .
docker image inspect --format '{{.Id}} {{.Config.User}} {{json .RootFS.Layers}}' \
  sqlite-worker-evidence | tee "$evidence/image.txt"
worker_container=$(docker create sqlite-worker-evidence)
docker export "$worker_container" | python "$GITHUB_WORKSPACE/.github/scripts/inspect_worker_sqlite_tar.py" \
  "$RUNNER_TEMP/base-sqlite3" | tee "$evidence/merged-filesystem.json"

# Install tracing only in a derived test image; keep the original worker user and entrypoint.
worker_user=$(docker image inspect --format '{{.Config.User}}' sqlite-worker-evidence)
docker build --tag sqlite-worker-trace - <<EOF
FROM sqlite-worker-evidence
USER root
RUN apt-get update && apt-get install -y --no-install-recommends strace && rm -rf /var/lib/apt/lists/*
USER $worker_user
EOF
mkdir "$evidence/trace"
chmod 0777 "$evidence/trace"
docker run --rm --network none --cap-add SYS_PTRACE \
  --mount "type=bind,src=$evidence/trace,dst=/trace" \
  --mount "type=bind,src=$PWD/docker/common,dst=/verification,readonly" \
  --mount "type=bind,src=$PWD/hastelib/tests/core/utils,dst=/imagery-tests,readonly" \
  --entrypoint /usr/bin/strace sqlite-worker-trace \
  -f -e trace=execve,execveat -o /trace/exec.log /app/scripts/entrypoint.sh \
  "command -v sqlite3 && exit 1; python -c 'from importlib.metadata import version; assert version(\"haste-gdal-runtime\") == \"3.13.3+haste.2\"' && $workload"
test -s "$evidence/trace/exec.log"
grep -F '/app/scripts/entrypoint.sh' "$evidence/trace/exec.log"
if grep -Ei 'execve(at)?\([^"]*"([^"]*/)?sqlite3(\.exe)?"' "$evidence/trace/exec.log"; then
  echo "SQLite CLI launch observed" >&2
  exit 1
fi
echo "No SQLite CLI launch observed in the traced entrypoint and checks"
