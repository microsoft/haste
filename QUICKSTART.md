# HASTE — Local Environment Quickstart (Agent Runbook)

> **Purpose:** This file is an **executable runbook for an AI coding agent**
> (Claude Code, GitHub Copilot, Cursor, etc.). Given the instruction *"stand up
> and start a local instance of HASTE"*, follow the phases below **in order**,
> running the commands, and **stopping at each ✅ Verify gate** before moving on.
> Do not skip gates. If a gate fails, jump to the matching entry in
> [§9 Troubleshooting](#9-troubleshooting) and re-run the gate before continuing.
>
> **Human-facing reference:** [`docker/README.md`](docker/README.md) is the
> comprehensive prose guide. This file is the condensed, decision-driven version
> for automation. When the two disagree, `docker/docker-compose.yml` is the
> ground truth.

---

## 0. What you are standing up

HASTE is a
building-damage-assessment platform. The local stack runs entirely in Docker
Compose from [`docker/docker-compose.yml`](docker/docker-compose.yml):

| Layer | Services | Notes |
|-------|----------|-------|
| Storage emulator | `azurite`, `data-init` | Azure Blob/Queue/Table emulator; `data-init` seeds it once and exits |
| Edge | `api-proxy` (nginx), `titiler` | CORS proxy on `:7071`; COG tile server |
| API | `hastefuncapi`, `hastefuncqueues` | Azure Functions (Python 3.11); queue worker spawns GPU jobs |
| UI | `ui` | Vite + React via SWA CLI on `:4280` |
| Build-only | `training_image`, `imageryprep_image` | Not long-running; spawned on demand by the LocalRunner via the Docker socket |

**Access points once running:** UI at `http://<HOST_IP>:4280`, API at
`http://<HOST_IP>:7071/api/`, Azurite blob at `http://<HOST_IP>:10000`.

---

## 1. Preflight — decide the target profile

Run these checks first and record the answers; they drive every later decision.

```bash
# Platform + CPU architecture
uname -s                       # Linux | Darwin
uname -m                       # x86_64 | arm64  <-- arm64 = Apple Silicon; see note below
# Docker present and daemon up
docker --version && docker compose version && docker info >/dev/null 2>&1 && echo "docker OK"
# GPU present? (Linux only — expect failure on macOS/Windows Docker Desktop)
docker run --rm --gpus all nvidia/cuda:12.2.2-base-ubuntu22.04 nvidia-smi 2>/dev/null && echo "GPU OK" || echo "NO GPU"
# Free disk (need ~100 GB for the full image set)
df -h .
```

> **⚠️ Apple Silicon (`uname -m` = `arm64`) — REQUIRED emulation.** The images
> are **amd64-only** (the Azure Functions base
> `mcr.microsoft.com/azure-functions/python:4-python3.11` has no arm64 variant —
> a plain build fails with `no match for platform in manifest`). You **must**
> export `DOCKER_DEFAULT_PLATFORM=linux/amd64` for **every** `build` and `up`
> command below; Docker Desktop then runs them under Rosetta/QEMU emulation
> (functional, somewhat slower). Set it once for your shell session:
>
> ```bash
> export DOCKER_DEFAULT_PLATFORM=linux/amd64   # Apple Silicon only
> ```

Decide the **profile** from the results:

| Condition | Profile | GPU flag |
|-----------|---------|----------|
| Linux host **with** working `--gpus all` | `gpu` | `HASTE_ENABLE_GPU=1` |
| Linux host **without** a GPU | `cpu` | `HASTE_ENABLE_GPU=0` |
| **macOS / Windows** (this repo's host is often macOS) | `cpu` | `HASTE_ENABLE_GPU=0` |

> **macOS/Windows reality check:** Docker Desktop **cannot** pass an NVIDIA GPU
> into containers. The stack (UI, API, storage, tiling, project/imagery CRUD)
> comes up fine and is fully usable for evaluation, but **training/inference
> jobs run CPU-only and are slow or may be impractical**. Set
> `HASTE_ENABLE_GPU=0` and tell the user this limitation up front.

**✅ Verify (Gate 1):** `docker info` succeeds and you have chosen a profile.
If Docker is missing or the daemon is down, install Docker CE / start Docker
Desktop before continuing — see `docker/README.md` §"Prerequisites" for the
Linux install script. **Do not proceed** until this gate passes.

---

## 2. Configure `docker/.env`

Docker Compose auto-reads [`docker/.env`](docker/.env). Every `VITE_*` URL is
interpolated from `HOST_IP`; a wrong value means the browser can't reach the API.

Compute the values:

```bash
# HOST_IP: 'localhost' for a machine you browse from directly;
#          the VM's PUBLIC IP if you'll reach it from another machine.
HOST_IP=localhost

# DOCKER_GID: GID of the docker socket, so hastefuncqueues can spawn siblings.
# Linux:
DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)
# macOS (BSD stat — the -c form does NOT work). Docker Desktop puts the socket
# under $HOME, NOT /var/run, so resolve the real path from the docker context:
# SOCK=$(docker context inspect --format '{{.Endpoints.docker.Host}}' | sed 's|unix://||')
# DOCKER_GID=$(stat -f '%g' "$SOCK")   # typically 20 (staff) on macOS
```

Write the file (adjust `HASTE_ENABLE_GPU` per your Gate-1 profile):

```bash
cat > docker/.env <<EOF
# --- Required ---
HOST_IP=${HOST_IP}
DOCKER_GID=${DOCKER_GID}

# --- GPU profile (0 = CPU-only: macOS/Windows or no NVIDIA GPU) ---
HASTE_ENABLE_GPU=0
HASTE_GPU_DEVICES=all

# --- Optional: Azure Maps for the Visualizer swipe map ---
# Leave as placeholder to skip; the rest of the app works without it.
# Get the Client ID (a UUID, NOT a key) from:
#   Azure Portal -> Azure Maps Account -> Authentication -> Client ID
# For local dev also run 'az login' with the "Azure Maps Data Reader" role.
VITE_AZURE_MAPS_CLIENT_ID=placeholder

# --- Optional: memory tuning for spawned training containers ---
# Match to host RAM (see docker/README.md "Memory & Performance Tuning").
# HASTE_DOCKER_SHM_SIZE=8g
# HASTE_DOCKER_MEM_LIMIT=28g
EOF
```

> **If GPU profile = `gpu`,** set `HASTE_ENABLE_GPU=1` instead, and size
> `HASTE_DOCKER_SHM_SIZE` / `HASTE_DOCKER_MEM_LIMIT` to the host: 32 GB RAM →
> `8g`/`28g`; 112 GB → `32g`/`96g`; 256 GB → `64g`/`200g`.

**✅ Verify (Gate 2):** `docker/.env` exists, `HOST_IP` is non-empty, and
`DOCKER_GID` is a number. Confirm with `cat docker/.env`.

---

## 3. Build the images

All compose commands use the repo root as build context (`context: ..`). Run
from the repo root and always pass `-f docker/docker-compose.yml`.

> **Apple Silicon:** prefix with `DOCKER_DEFAULT_PLATFORM=linux/amd64` (or
> `export` it once, per §1) on this and every command below.

```bash
docker compose -f docker/docker-compose.yml build
```

This builds ~9 images including the large CUDA + conda `haste-training` image.
**Expect 15–30 minutes** on a first build. If it fails on the training image and
you're on the `cpu` profile, you still need it built (the LocalRunner references
`haste-training:latest`), but you can defer it and build the rest first:

```bash
# Faster path to a browsable UI: build everything except the heavy training image
docker compose -f docker/docker-compose.yml build \
  azurite data-init api-proxy titiler hastefuncapi hastefuncqueues ui imageryprep_image
```

**✅ Verify (Gate 3):** `docker compose -f docker/docker-compose.yml build`
exits 0 for the services you intend to run. `docker images | grep haste`
shows the built images.

---

## 4. Start the stack

```bash
docker compose -f docker/docker-compose.yml up -d
```

> **⚠️ Deferred the training image (CPU profile / didn't build `haste-training`)?**
> A plain `up -d` will **trigger a full build of the heavy CUDA `haste-training`
> image**, because `hastefuncqueues` declares `depends_on: [training_image,
> imageryprep_image]`. On a CPU-only host that build is a slow, multi-GB waste.
> Start only the runtime services with `--no-deps` so compose never touches the
> build-only `training_image`. Since `--no-deps` also skips `depends_on`
> ordering, bring `azurite` up first and gate on its blob port before the rest:
>
> ```bash
> export DOCKER_DEFAULT_PLATFORM=linux/amd64   # Apple Silicon only
> C="docker compose -f docker/docker-compose.yml"
> $C up -d --no-deps azurite
> until curl -s "http://localhost:10000/devstoreaccount1?comp=list" >/dev/null; do sleep 1; done
> $C up -d --no-deps data-init         # seeds, then exits 0
> $C up -d --no-deps titiler hastefuncapi hastefuncqueues ui api-proxy
> ```
>
> (`imageryprep_image` is also build-only but its image is small and built in
> §3, so `--no-deps` simply leaves it alone.)

Boot order is enforced by `depends_on`: `azurite` → `data-init` (seeds config +
queues, then exits 0) → `titiler` / `hastefuncapi` → `hastefuncqueues` →
`api-proxy` → `ui`.

Watch it settle:

```bash
docker compose -f docker/docker-compose.yml ps
docker compose -f docker/docker-compose.yml logs -f --tail=50
```

`data-init` reaching `Exited (0)` is **expected and correct** — it is a one-shot
seeder, not a crash. `"Container already exists"` lines from it are benign.

**✅ Verify (Gate 4):** `docker compose ps` shows `azurite`, `api-proxy`,
`titiler`, `hastefuncapi`, `hastefuncqueues`, and `ui` as `Up`/`running`, and
`data-init` as `Exited (0)`.

---

## 5. Health checks (the real acceptance gate)

Run each and confirm the expected result. Use `localhost` here regardless of
`HOST_IP` since you're running on the host.

```bash
# Azurite blob endpoint responds
curl -s "http://localhost:10000/devstoreaccount1?comp=list" >/dev/null && echo "azurite OK"

# API functions are loaded (should return JSON, not a connection error)
curl -s http://localhost:7071/api/GetAdminSettings | head -c 200 ; echo

# TiTiler is healthy
curl -s http://localhost:8000/healthz && echo "  <- titiler OK"

# UI is serving (root 302-redirects to the SWA auth portal — this is expected;
# follow redirects to confirm it resolves to HTTP 200)
curl -s -L -o /dev/null -w "ui HTTP %{http_code}\n" http://localhost:4280
```

**✅ Verify (Gate 5 — DONE criteria):** all four succeed:
`/api/GetAdminSettings` returns JSON, TiTiler returns healthy, and the UI root
returns **HTTP 302 → `/login` → `/.auth/login/aad`, resolving to HTTP 200**
(the SWA CLI emulator's login portal — a bare `curl` without `-L` shows `302`,
which is correct, not a failure). Then open **`http://<HOST_IP>:4280`** in a
browser. The SWA emulator presents a **mock-login portal** (`DEVELOPMENT_MODE=true`
bypasses real Azure AD in the API, but the UI still runs the SWA emulator auth).
**Report this URL to the user as the finish line.**

> **⚠️ You MUST supply a role at the mock-login form, or you get a redirect
> loop.** Every route in `ui/public/staticwebapp.config.json` requires
> `allowedRoles: ["administrators", "contributors"]`, and the SWA emulator only
> grants `anonymous`/`authenticated` by default — so logging in without a role
> just bounces you back to the login page (logs show `/401.html → 401` then
> `/.auth/login/aad → 200`, repeating). On the emulator login form fill:
> **User ID** = anything (e.g. `dev`), **Username** = anything, and
> **User's roles** = **`administrators`** (or `administrators,contributors`),
> then click **Login**. The app then loads.

If any check fails, go to [§9 Troubleshooting](#9-troubleshooting), apply the
fix, and re-run this section.

---

## 6. Smoke test (optional, confirms end-to-end)

Only meaningful on the `gpu` profile (or if you accept slow CPU runs):

1. In the UI, **New Project** → name it, pick a Source Type.
2. **Imagery** tab → upload a pre-event and post-event GeoTIFF. This enqueues
   `local-image-queue`; `hastefuncqueues` spawns `haste-imageryprep`.
3. Watch the worker: `docker compose -f docker/docker-compose.yml logs -f hastefuncqueues`.
4. Training/Inference tabs spawn `haste-training`; inspect the spawned container:
   ```bash
   docker ps -a --filter ancestor=haste-training:latest
   docker logs -f <container_id>
   ```

**✅ Verify (Gate 6):** an imagery-prep job completes and imagery appears in the
map viewer. Skip this gate on CPU-only hosts if jobs are impractically slow —
say so rather than waiting indefinitely.

---

## 7. Lifecycle commands (for the agent to reuse)

```bash
export DOCKER_DEFAULT_PLATFORM=linux/amd64  # Apple Silicon only
C="docker compose -f docker/docker-compose.yml"

$C up -d                                    # start (⚠ builds haste-training unless deferred — see §4)
# CPU / training-deferred start (skip the CUDA image):
$C up -d --no-deps azurite data-init titiler hastefuncapi hastefuncqueues ui api-proxy
$C down                                     # stop, keep data
$C down -v                                  # stop, WIPE all Azurite data
$C logs -f <service>                        # tail one service
$C restart api-proxy                        # fix stale nginx upstream (see traps)

# Rebuild ONE service after a code change WITHOUT re-running data-init:
$C up -d --no-deps --force-recreate --build hastefuncapi
$C restart api-proxy                        # nginx caches the upstream IP — always follow with this
```

---

## 8. Critical traps (read before editing anything)

These are non-obvious and will silently break the stack. Source: `AGENTS.md`.

1. **`data-init` re-seeds on every full `up`.** It re-uploads
   `project_stats.json` with empty defaults, wiping the dashboard's project
   list. When recreating a single service use `--no-deps` (as in §7). If stats
   were wiped, regenerate: `curl http://localhost:7071/api/GenerateProjectStats`.
2. **nginx caches the `hastefuncapi` upstream IP at startup.** After recreating
   `hastefuncapi`, its container IP changes and `/api/*` starts returning 404 —
   always `docker compose ... restart api-proxy` afterward.
3. **The docker-socket GID must match the host** or `hastefuncqueues` can't
   spawn training/imageryprep containers. This is the `DOCKER_GID` you set in
   §2. If job spawning fails with a permission error, re-check it.
4. **Project/volume/network names are folder-derived.** Compose prefixes with
   the project dir name (`docker`), yielding `docker_default` and
   `docker_azurite-data` — these are hard-referenced in
   `HASTE_DOCKER_NETWORK` / `HASTE_DOCKER_AZURITE_VOLUME`. If you run compose
   with a custom `-p <name>` or from a renamed folder, update those two env vars
   to `<name>_default` / `<name>_azurite-data` or spawned jobs won't reach
   Azurite. Verify with `docker network ls | grep default` and
   `docker volume ls | grep azurite`.

---

## 9. Troubleshooting

Match the failing gate to a fix, apply it, then **re-run the gate**.

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `docker info` fails (Gate 1) | Daemon not running | Start Docker Desktop / `sudo systemctl start docker` |
| Build fails: `no match for platform in manifest` | arm64 host, amd64-only base image | `export DOCKER_DEFAULT_PLATFORM=linux/amd64` and rebuild (§1) |
| Pull dies mid-layer with `EOF` / `TLS handshake timeout` | flaky/VPN'd connection to `mcr.microsoft.com` | Turn off VPN; retry — Docker resumes cached layers, so a loop of retries converges. Pre-pull the base: `docker pull --platform linux/amd64 mcr.microsoft.com/azure-functions/python:4-python3.11` |
| `up -d` unexpectedly builds `haste-training` (CUDA/torch wheels) | `hastefuncqueues depends_on training_image` | Start runtime services with `--no-deps` (§4) |
| `--gpus all` test fails on Linux | NVIDIA Container Toolkit missing | Install it (`docker/README.md` §3), `sudo systemctl restart docker` |
| UI stuck in login loop (login page reloads; logs show `401.html`↔`/.auth/login/aad`) | mock-login granted no role; routes need `administrators`/`contributors` | On the SWA emulator login form set **User's roles** = `administrators`, then Login (Gate 5) |
| UI blank / "Network Error" (Gate 5) | `HOST_IP` wrong, or nginx stale | `cat docker/.env`; `docker compose ... restart api-proxy` |
| `/api/GetAdminSettings` refuses connection | `hastefuncapi` not up / Azurite not ready | `docker compose ... logs --tail=200 hastefuncapi`; restart it |
| `/api/*` returns 404 after a recreate | nginx cached old upstream IP | `docker compose ... restart api-proxy` (Trap #2) |
| API 500s | Azurite wasn't ready at startup | `docker compose ... restart hastefuncapi` |
| Training job never starts | `DOCKER_GID` mismatch / socket perms | Recompute `DOCKER_GID` (§2), recreate `hastefuncqueues` (Trap #3) |
| Training "killed by signal" / OOM | shared memory too small | Raise `HASTE_DOCKER_SHM_SIZE` / `HASTE_DOCKER_MEM_LIMIT` in `docker/.env` |
| Spawned job "no such network/volume" | project-name prefix mismatch | Fix `HASTE_DOCKER_NETWORK` / `HASTE_DOCKER_AZURITE_VOLUME` (Trap #4) |
| Dashboard lost its projects | `data-init` re-seeded stats | `curl http://localhost:7071/api/GenerateProjectStats` (Trap #1) |
| TiTiler 502 / tiles blank | proxy stale or titiler down | `docker compose ... ps titiler`; `curl localhost:8000/healthz`; restart `api-proxy` |
| Visualizer inert / no map | `VITE_AZURE_MAPS_CLIENT_ID` unset | Set a real Client ID + `az login` with Maps Data Reader role (§2) |

To fully reset state and start clean:

```bash
docker compose -f docker/docker-compose.yml down -v
docker compose -f docker/docker-compose.yml up -d
```

---

## 10. Definition of done

Report success to the user only when **all** of these hold:

- [ ] `docker/.env` written with correct `HOST_IP`, `DOCKER_GID`, and GPU flag.
- [ ] `docker compose ps` shows all long-running services `Up` and `data-init` `Exited (0)`.
- [ ] Gate 5 health checks all pass (Azurite, API, TiTiler, UI).
- [ ] The UI loads at `http://<HOST_IP>:4280` and you can complete the SWA emulator mock-login with role `administrators` (or `contributors`).
- [ ] You told the user the profile (`gpu`/`cpu`) and, if `cpu`, that
      training/inference will be slow or limited.
- [ ] On Apple Silicon: you exported `DOCKER_DEFAULT_PLATFORM=linux/amd64`,
      started runtime services with `--no-deps` (skipping `haste-training`), and
      told the user the stack runs under amd64 emulation.
