# Lessons Learned — Local Dev Environment

Operational lessons from running HASTE locally via Docker Compose on an Azure ML compute instance.

## Docker Compose

### Don't `--force-recreate` the queue worker while tasks are running

The queue worker (`hastefuncqueues`) monitors running training/inference containers and uploads their output to blob storage after they finish. If you `docker compose up -d --force-recreate hastefuncqueues` while a task is in progress, the upload step never runs and artifacts (including model checkpoints) are lost from blob storage — even though they exist on the local Docker volume.

**Safe approach:** Wait for active tasks to complete before recreating the queue worker. If you need to update other services, target them explicitly:

```bash
docker compose up -d --force-recreate hastefuncapi api-proxy ui
```

### `docker compose restart` does NOT re-read `.env` interpolation

If you change values in `docker/.env` (e.g. `HASTE_ENABLE_GPU`), `docker compose restart <service>` will **not** pick them up. The `.env` file is only read during `up`. You must use:

```bash
docker compose up -d --force-recreate <service>
```

### nginx proxy caches container DNS

After recreating backend containers (which changes their IP), the nginx `api-proxy` may still route to the old IP. Fix with:

```bash
docker compose exec api-proxy nginx -s reload
```

### Docker socket GID must match the host

The queue worker needs Docker socket access to spawn training containers. The compose file uses `group_add: ["${DOCKER_GID:-1001}"]`. Check your host's Docker GID and set it in `docker/.env`:

```bash
echo "DOCKER_GID=$(getent group docker | cut -d: -f3)" >> docker/.env
```

## Disk & Storage

### Move Docker data-root to a large disk

The default `/var/lib/docker` lives on the OS disk which is typically small (~120 GB). The training image alone is ~22 GB and builds need ~60-80 GB peak. Move the data-root to a larger mount:

```json
// /etc/docker/daemon.json
{
  "data-root": "/mnt/code/docker-data"
}
```

Then restart Docker: `sudo systemctl restart docker`

## Training & Inference Pipeline

### argparse treats negative coordinates as flags

`--bbox -156.5,20.5,-155.8,21.0` fails because argparse interprets `-156.5` as a flag. Use the `=` form:

```python
# Bad
"--bbox", value
# Good
f"--bbox={value}"
```

### Training container file permissions

The training container runs as `dockeruser` (UID 1000). The queue worker runs as `appuser` (UID 999). Without `umask 0022` in the training entrypoint, checkpoint files are created with `600` permissions and the queue worker can't read them for upload.

**Fix:** `umask 0022` in `docker/training/scripts/entrypoint.sh`.

### `get_base_url()` must respect the connection string

Hardcoding `https://{account}.blob.core.windows.net` breaks when using Azurite (local blob emulator). Use `BlobServiceClient.url` which respects the `BlobEndpoint` in the connection string.

## Build

### Set `HASTE_SKIP_VERSION_BUMP=1` in Docker builds

The Hatchling custom build hook (`haste_build.py`) tries to bump versions and upload to Azure blob storage during `pip install`. Set this env var in Dockerfiles that install `hastelib` to skip the hook.

### Vite 8 requires Node.js ≥ 20.19 or ≥ 22.12

The UI uses Vite 8 which dropped support for older Node versions. Use `node:22-slim` (or newer) as the base image for the UI Dockerfile.
