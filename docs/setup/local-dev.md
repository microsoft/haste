# Local Development

The recommended way to run HASTE locally is the **Docker Compose stack**, which brings up
the entire platform — storage emulator, tile server, API, queue workers, and UI — with a
single command.

```{note}
This page is a **summary**. The complete, step-by-step instructions live in two files at
the repository root, which are the source of truth:

- **[`QUICKSTART.md`](https://github.com/microsoft/haste/blob/main/QUICKSTART.md)** — a
  phased, verify-gated runbook (also used to drive AI coding agents).
- **[`docker/README.md`](https://github.com/microsoft/haste/blob/main/docker/README.md)** —
  the comprehensive human-facing prose guide, including prerequisites, memory tuning, and
  troubleshooting.

When any doc disagrees with the compose file, `docker/docker-compose.yml` is ground truth.
```

## What you're standing up

The local stack runs entirely from `docker/docker-compose.yml`:

| Layer | Services | Notes |
|-------|----------|-------|
| Storage emulator | `azurite`, `data-init` | Azure Blob/Queue/Table emulator; `data-init` seeds it once and exits |
| Edge | `api-proxy` (nginx), `titiler` | CORS proxy on `:7071`; COG tile server |
| API | `hastefuncapi`, `hastefuncqueues` | Azure Functions (Python 3.11); the queue worker spawns GPU jobs |
| UI | `ui` | Vite + React via SWA CLI on `:4280` |
| Build-only | `training_image`, `imageryprep_image` | Spawned on demand by the LocalRunner via the Docker socket |

## Prerequisites

- **Docker** with Compose v2 (`docker compose version`)
- ~100 GB free disk for the full image set

```{warning}
**Apple Silicon:** the images are amd64-only, so you must export
`DOCKER_DEFAULT_PLATFORM=linux/amd64` before every `build`/`up` command. Docker Desktop
then runs them under emulation — functional, just somewhat slower.
```

```{note}
**GPU** acceleration is Linux-only. On macOS or Windows the stack runs CPU-only, so
training and inference jobs are slow or impractical — the rest of the app (UI, project and
imagery management, tiling) is fully usable for evaluation.
```

## Bring it up

From the repository root:

```bash
# 1. Configure host + docker socket GID (see QUICKSTART §2 for the full recipe)
cat > docker/.env <<'EOF'
HOST_IP=localhost
DOCKER_GID=<gid-of-your-docker.sock>
HASTE_ENABLE_GPU=0
EOF

# 2. Build the images (first build is ~15–30 min)
docker compose -f docker/docker-compose.yml build

# 3. Start the stack
docker compose -f docker/docker-compose.yml up -d
```

Once running:

- **UI** — `http://<HOST_IP>:4280`
- **API** — `http://<HOST_IP>:7071/api/`
- **Azurite blob** — `http://<HOST_IP>:10000`

```{important}
For Docker Compose, the SWA mock-login form pre-fills **User's roles** with
`administrators`. Enter a user ID and username, confirm the role is present,
then select **Login**.
```

```{tip}
For platform-specific profiles (Apple Silicon, GPU vs. CPU), the health-check gates, the
critical traps (nginx upstream caching, `data-init` re-seeding), and full troubleshooting,
follow [`QUICKSTART.md`](https://github.com/microsoft/haste/blob/main/QUICKSTART.md)
end to end.
```

## Ready for production?

The local stack is for development and evaluation only. To deploy a production-grade
environment on Azure, see the [Deployment Guide](../deployment.md) and the
[Configuration Guide](../configuration.md).
