# HASTE Local Docker Deployment — Comprehensive Guide

> **HASTE** (Humanitarian AI for Satellite-based Terrain Evaluation) is a damage-assessment
> platform that combines satellite imagery with deep-learning models to identify and classify
> building damage after natural disasters.
>
> This guide walks you through **every step** required to run the full HASTE stack locally
> with Docker Compose — from provisioning a VM to verifying that training and inference
> jobs complete successfully.
>
> **Automating setup with an AI agent?** See [`../QUICKSTART.md`](../QUICKSTART.md) — a
> condensed, decision-driven runbook for Claude Code / GitHub Copilot with explicit verify
> gates. This file remains the comprehensive human reference.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Hardware Requirements](#hardware-requirements)
3. [Prerequisites — Host Machine Setup](#prerequisites--host-machine-setup)
   - [Docker & Docker Compose](#1-docker--docker-compose)
   - [NVIDIA GPU Drivers](#2-nvidia-gpu-drivers-gpu-vms-only)
   - [NVIDIA Container Toolkit](#3-nvidia-container-toolkit-gpu-vms-only)
   - [Git & Repository Clone](#4-git--repository-clone)
4. [Environment Configuration](#environment-configuration)
   - [Required: `docker/.env`](#required-dockerenv)
   - [Azure Maps Authentication](#azure-maps-authentication)
   - [Memory & Performance Tuning](#memory--performance-tuning)
5. [Building & Starting the Stack](#building--starting-the-stack)
   - [First-Time Build](#first-time-build)
   - [Subsequent Starts](#subsequent-starts)
   - [Start Order & Boot Sequence](#start-order--boot-sequence)
6. [Service Reference](#service-reference)
   - [Infrastructure Services](#infrastructure-services)
   - [API Services](#api-services)
   - [UI Service](#ui-service)
   - [Build-Only Images](#build-only-images-used-by-localrunner)
7. [Network & Port Reference](#network--port-reference)
8. [Volume & Storage Reference](#volume--storage-reference)
9. [How the Local Runner Works](#how-the-local-runner-works)
10. [Using the Application](#using-the-application)
    - [Accessing the UI](#accessing-the-ui)
    - [Creating a Project](#creating-a-project)
    - [Uploading Imagery](#uploading-imagery)
    - [Running Training](#running-training)
    - [Running Inference](#running-inference)
    - [Viewing Results in the Visualizer](#viewing-results-in-the-visualizer)
11. [Rebuilding the Haste Wheel](#rebuilding-the-haste-wheel)
12. [Common Operations Cheat-Sheet](#common-operations-cheat-sheet)
13. [Troubleshooting](#troubleshooting)
14. [Production Considerations](#production-considerations)

---

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────────────────┐
│                              HASTE Docker Stack                            │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  ┌───────────┐    ┌──────────────┐    ┌──────────────────┐                 │
│  │    UI     │───▶│  API Proxy   │───▶│   hastefuncapi   │                 │
│  │  :4280    │    │  (nginx)     │    │ (Azure Functions) │                 │
│  │ Vite+React│    │   :7071      │    │  HTTP Triggers    │                 │
│  └───────────┘    │              │    └───────┬──────────┘                 │
│                   │  ┌──────────▶│            │ Enqueues messages           │
│                   │  │  TiTiler  │   ┌────────▼──────────┐                 │
│                   │  │  proxied  │   │  hastefuncqueues   │                 │
│                   │  │  /api/    │   │  (Queue Triggers)  │                 │
│                   │  │  titiler/ │   │  RUNNER_TYPE=local  │                 │
│                   │  └──────────▶│   └────────┬──────────┘                 │
│                   └──────────────┘            │                             │
│                                               │ Spawns GPU containers       │
│   ┌──────────┐                                ▼                             │
│   │  TiTiler │◀────────┐  ┌────────────────────────────────────────────┐   │
│   │  :8000   │         │  │       GPU Processing Containers            │   │
│   │ COG tiles│         │  │  ┌──────────────┐  ┌──────────────┐        │   │
│   └──────────┘         │  │  │haste-imagery-│  │haste-training│        │   │
│                        │  │  │prep (download,│  │(fine-tune,   │        │   │
│                        │  │  │ tile, mask)   │  │ inference)   │        │   │
│                        │  │  └──────────────┘  └──────────────┘        │   │
│                        │  └────────────────────────────────────────────┘   │
│                        │                       │                           │
│                        │  reads COGs from      │ writes outputs to         │
│                        └──────────────┐        │                           │
│                                       ▼        ▼                           │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │                       Azurite Emulator                             │    │
│  │        Blob Storage :10000  │  Queue Storage :10001                │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                      ▲                                                     │
│                      │ seeds config on first boot                          │
│                 ┌────┴─────┐                                               │
│                 │ data-init│                                               │
│                 └──────────┘                                               │
└────────────────────────────────────────────────────────────────────────────┘
```

### Service Summary

| Service | Image | Role |
|---------|-------|------|
| **azurite** | `mcr.microsoft.com/azure-storage/azurite` | Azure Storage emulator (Blob + Queue + Table) |
| **data-init** | Custom (Python 3.11) | One-shot init container: creates blob containers, queues, and uploads seed config |
| **api-proxy** | `mcr.microsoft.com/oss/nginx/nginx:1.21.6` | CORS-enabled reverse proxy; routes `/api/` → hastefuncapi, `/api/titiler/` → titiler |
| **titiler** | `developmentseed/titiler` | Cloud-Optimized GeoTIFF tile server |
| **hastefuncapi** | Custom (Azure Functions Python 3.11) | HTTP API — project CRUD, imagery endpoints, visualizer |
| **hastefuncqueues** | Custom (Azure Functions Python 3.11) | Queue-triggered workers — imagery prep, training, inference, stats, zip |
| **ui** | Custom (Node 20 + Vite + React) | SPA served via Azure Static Web Apps CLI |
| **training_image** | Custom (CUDA 12.4 + conda `bda` env) | Build-only — spawned at runtime by LocalRunner for training/inference |
| **imageryprep_image** | Custom (Python 3.11) | Build-only — spawned at runtime by LocalRunner for imagery download/prep |

---

## Hardware Requirements

### Minimum (Development / Testing)

- **CPU:** 8 cores
- **RAM:** 32 GB
- **GPU:** None (CPU-only mode — training will be slow but functional)
- **Storage:** 100 GB SSD

### Recommended (Production Training)

- **CPU:** 24+ cores
- **RAM:** 256+ GB
- **GPU:** 1–4× NVIDIA V100 / A100 (16+ GB VRAM each)
- **Storage:** 500+ GB NVMe SSD

### Example VM Sizes

| Cloud | VM Size | GPUs | RAM | Notes |
|-------|---------|------|-----|-------|
| Azure | Standard_NC24rs_v3 | 4× V100 16 GB | 448 GB | Tested configuration |
| Azure | Standard_NC6s_v3 | 1× V100 16 GB | 112 GB | Development / single-GPU |
| Azure | Standard_ND40rs_v2 | 8× V100 32 GB | 672 GB | Large-scale training |

---

## Prerequisites — Host Machine Setup

> The instructions below assume an **Ubuntu 22.04+** Linux host. Adapt package
> managers accordingly for other distributions.

### 1. Docker & Docker Compose

```bash
# Install Docker CE (do NOT use the snap package — it lacks GPU support)
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Allow your user to run docker without sudo
sudo usermod -aG docker $USER
newgrp docker

# Verify
docker --version          # e.g. Docker version 24.x
docker compose version    # e.g. Docker Compose version v2.x
```

### 2. NVIDIA GPU Drivers (GPU VMs only)

```bash
# Check if the driver is already installed
nvidia-smi

# If not, install the recommended driver
sudo apt-get install -y linux-headers-$(uname -r)
sudo apt-get install -y nvidia-driver-535   # or latest recommended
sudo reboot
```

### 3. NVIDIA Container Toolkit (GPU VMs only)

```bash
distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Verify GPU is visible inside Docker
docker run --rm --gpus all nvidia/cuda:12.2.2-base-ubuntu22.04 nvidia-smi
```

### 4. Git & Repository Clone

```bash
sudo apt-get install -y git

git clone https://github.com/microsoft/haste.git
cd haste

```

---

## Environment Configuration

### Required: `docker/.env`

Create (`or edit`) the file **`docker/.env`** — Docker Compose automatically reads it:

```bash
# ============================================================
#  REQUIRED
# ============================================================

# The IP address that the browser will use to reach the VM.
# • For a remote/cloud VM: use its Public IP (e.g. 20.112.10.254)
# • For a local machine:   use 'localhost' or '127.0.0.1'
HOST_IP=<YOUR_VM_PUBLIC_IP>

# ============================================================
#  OPTIONAL — Memory / Performance
# ============================================================

# Memory allocation for GPU training containers.
# Set these according to the table in "Memory & Performance Tuning" below.
# HASTE_DOCKER_SHM_SIZE=64g
# HASTE_DOCKER_MEM_LIMIT=256g

# ============================================================
#  REQUIRED — Azure Maps (for Visualizer map tiles)
# ============================================================

# The Azure Maps Account client ID (NOT a subscription key).
# Find it in: Azure Portal → Azure Maps Account → Authentication → Client ID
# For local dev, run `az login` first and ensure your account has the
# "Azure Maps Data Reader" role on the Maps account.
VITE_AZURE_MAPS_CLIENT_ID=<YOUR_AZURE_MAPS_CLIENT_ID>
```

> **Important:** `HOST_IP` is interpolated into every `VITE_*` URL that the UI
> uses. If it is wrong (or missing), the browser won't be able to reach the API
> or load map tiles.

### Azure Maps Authentication

The **Visualizer** component uses Azure Maps for before/after satellite imagery
comparison with a swipe-bar. Maps authentication now uses Azure AD tokens via
managed identity — no subscription key is needed or used.

1. In the Azure Portal, open your **Azure Maps Account** → **Authentication** → copy the **Client ID** (a UUID, not a key).
2. Add it to `docker/.env`:
   ```bash
   VITE_AZURE_MAPS_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
   ```
3. For **local development**, run `az login` and ensure your account has the **Azure Maps Data Reader** role on the Maps account. The backend (`GetAzureMapsToken`) will use your CLI credentials to fetch a short-lived token.
4. In **production**, the Function App's managed identity must have the **Azure Maps Data Reader** role — no additional config required.

### Memory & Performance Tuning

These environment variables control resource limits for the **GPU training/inference
containers** that the LocalRunner spawns dynamically:

| Variable | Default | Description |
|----------|---------|-------------|
| `HASTE_DOCKER_SHM_SIZE` | `64g` | Shared memory (`/dev/shm`). Critical for PyTorch DataLoader workers. **Increase if training crashes with "killed by signal".** |
| `HASTE_DOCKER_MEM_LIMIT` | `256g` | Hard memory ceiling for each spawned container. |
| `HASTE_DATALOADER_WORKERS` | `8` | Number of PyTorch DataLoader workers. Reduce if RAM-constrained. (Set in `docker-compose.yml`.) |

**Tuning guide by VM size:**

| VM RAM | `HASTE_DOCKER_SHM_SIZE` | `HASTE_DOCKER_MEM_LIMIT` | Suggested Batch Size |
|--------|-------------------------|--------------------------|----------------------|
| 32 GB  | `8g`  | `28g`  | 8  |
| 112 GB | `32g` | `96g`  | 16 |
| 256 GB | `64g` | `200g` | 32 |
| 448 GB | `128g`| `400g` | 64 |

---

## Building & Starting the Stack

> **All commands should be run from the `docker/` directory** (the Docker Compose
> context is set to the repository root via `context: ..` in the compose file).

### First-Time Build

```bash
cd docker

# Build every image (may take 15–30 min depending on network speed)
docker compose build

# Start all services in detached mode
docker compose up -d

# Watch the real-time log stream
docker compose logs -f
```

The **first boot** will:

1. Build all Docker images (including the large `haste-training` image with CUDA + conda).
2. Start **Azurite** (the storage emulator).
3. Run **data-init** (seeds Azurite with `config_admin_settings.json`, `users_acl.json`,
   `project_stats.json`, and creates the required message queues).
4. Start **hastefuncapi** (waits for Azurite, regenerates project-stats cache on startup).
5. Start **hastefuncqueues** (listens on queues for jobs).
6. Start **api-proxy** (nginx — routes external traffic).
7. Start **titiler** (COG tile server).
8. Start **ui** (Vite dev server behind SWA CLI).

### Subsequent Starts

```bash
# If images are already built:
docker compose up -d

# To rebuild a single service after code changes:
docker compose up -d --build hastefuncapi

# To rebuild everything from scratch:
docker compose up -d --build --force-recreate
```

### Start Order & Boot Sequence

Docker Compose `depends_on` ensures the correct ordering, but the key chain is:

```
azurite
  └─▶ data-init          (seeds storage, then exits)
  └─▶ titiler
  └─▶ hastefuncapi        (runs startup.py → waits for Azurite → regenerates stats)
  └─▶ hastefuncqueues     (depends on training_image + imageryprep_image builds)
        └─▶ training_image       (build-only, no running container)
        └─▶ imageryprep_image    (build-only, no running container)

hastefuncapi
  └─▶ api-proxy (nginx)

hastefuncapi + hastefuncqueues + titiler
  └─▶ ui
```

> **Tip:** If the `data-init` container fails (e.g. Azurite wasn't ready), just run:
> ```bash
> docker compose up -d data-init
> ```

---

## Service Reference

### Infrastructure Services

#### Azurite (Azure Storage Emulator)

- **Ports:** 10000 (Blob), 10001 (Queue), 10002 (Table)
- **Volume:** `azurite-data` mounted at `/data`
- **Connection String (well-known Azurite default):**
  ```
  DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;
  AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;  # pragma: allowlist secret # gitleaks:allow
  BlobEndpoint=http://azurite:10000/devstoreaccount1;
  QueueEndpoint=http://azurite:10001/devstoreaccount1;
  ```
- **Important:** Runs with `--skipApiVersionCheck` to accommodate newer Azure SDK versions.

#### data-init (One-Shot Initializer)

- Waits up to 60 s for Azurite to become healthy.
- Creates the `data` blob container with **public blob access** (necessary for direct browser
  reads of imagery tiles in local dev).
- Creates all message queues:
  - `local-image-queue`
  - `local-train-queue`
  - `local-inference-queue`
  - `local-stats-queue`
  - `local-zip-queue`
  - `local-image-queue-poison`
- Uploads seed config files (`config_admin_settings.json`, `users_acl.json`, `project_stats.json`).
- Set to `restart: "no"` — runs once and exits with code 0.

#### api-proxy (NGINX)

- Listens on **port 7071** (matches the default Azure Functions port for familiarity).
- Routes:
  - `GET/POST /api/titiler/*` → `http://titiler:8000/` (strips the prefix)
  - `GET/POST /api/*` → `http://hastefuncapi:8080` (preserves full URI)
- Adds `Access-Control-Allow-Origin: *` headers to every response (CORS).
- Handles `OPTIONS` preflight requests.

#### TiTiler (Raster Tile Server)

- Built from `developmentseed/titiler:latest`.
- Serves Cloud-Optimized GeoTIFF (COG) tiles for satellite imagery visualization.
- Internal: `http://titiler:8000/`
- External (via proxy): `http://<HOST_IP>:7071/api/titiler/`

### API Services

#### hastefuncapi (HTTP API)

- **Dockerfile:** `api/hastefuncapi/Dockerfile`
- **Base image:** `mcr.microsoft.com/azure-functions/python:4-python3.11`
- **Key environment variables:**
  - `DEVELOPMENT_MODE=true` — **bypasses Azure AD authentication** (anonymous access)
  - `BLOB_CONNECTION_STRING` — points to Azurite
  - `TITILER_PUBLIC_ENDPOINT` — used to build tile URLs returned to the UI
- **Startup script** (`startup.py`): waits for Azurite, then regenerates `project_stats.json`
  so the dashboard shows existing projects after a container restart.
- **Bind mount:** `../data:/app/data` for local data access.
- **Docker socket mount:** `/var/run/docker.sock` (read-write; lets the API and queue containers spawn sibling training/imageryprep containers via the local runner).
- Copies `hastelib/src/hastegeo` directly into the image (avoids wheel installation in Docker).

#### hastefuncqueues (Queue Worker)

- **Dockerfile:** `api/hastefuncqueues/Dockerfile`
- **Key environment variables:**
  - `RUNNER_TYPE=local` — uses the **LocalRunner** (Docker-based) instead of Azure Batch
  - `DEVELOPMENT_MODE=true` — anonymous queue access via Azurite
  - `HASTE_ENABLE_GPU=1` / `HASTE_GPU_DEVICES=all` — GPU passthrough to spawned containers
  - `HASTE_DOCKER_NETWORK=docker_default` — spawned containers join this network to reach Azurite
  - `HASTE_DOCKER_AZURITE_VOLUME=docker_azurite-data` — shared volume for blob data access
  - `HASTE_OUTPUT_DIR=/shared/azurite` — LocalRunner writes outputs here (shared with Azurite volume)
- **Bind mounts:**
  - `../data:/app/data`
  - `azurite-data:/shared/azurite` — **shared Named Volume** with Azurite for direct file-system reads
  - `/var/run/docker.sock:/var/run/docker.sock` — **required** to spawn training/imageryprep containers
- Copies `hastelib/src/hastegeo` directly into the image.

### UI Service

- **Dockerfile:** `ui/Dockerfile`
- **Base image:** `mcr.microsoft.com/azurelinux/base/nodejs:24`
- Uses **Vite** for dev HMR and **Azure Static Web Apps CLI** to serve the app.
- Reads a `.env.docker` file baked into the image for default `VITE_API_URL`.
- Environment variables in `docker-compose.yml` **override** the baked-in `.env.docker` values.
- Key env vars:
  - `VITE_API_URL` → `http://<HOST_IP>:7071/api/` (all API calls)
  - `VITE_STORAGE_APIM_URL` → `http://<HOST_IP>:10000` (direct Azurite blob reads)
  - `VITE_TITILER_URL` → `http://<HOST_IP>:7071/api/titiler/` (tile requests)
  - `VITE_AZURE_MAPS_CLIENT_ID` → Azure Maps Account client ID (for Visualizer; auth via managed identity/Azure AD)

### Build-Only Images (used by LocalRunner)

These services **only build an image** — they don't run as persistent containers.
The `hastefuncqueues` LocalRunner spawns them on-demand via the Docker socket.

#### haste-training

- **Dockerfile:** `docker/training/Dockerfile`
- **Base:** `mcr.microsoft.com/azureml/curated/minimal-py312-cuda12.4-inference`
- Multi-stage build: Stage 1 creates the conda `bda` env and packs it; Stage 2 unpacks it.
- Contains: `fine_tune.py`, `inference.py`, `create_masks.py`, etc.
- The LocalRunner mounts the Azurite volume and Docker network when spawning it.

#### haste-imageryprep

- **Dockerfile:** `docker/imageryprep/Dockerfile`
- **Base:** `mcr.microsoft.com/azure-functions/python:4-nightly-python3.11-slim`
- Provides CLI entrypoints: `prepare-imagery`, `zip-artifacts`.
- Used for downloading imagery, creating tiles, and packaging outputs.

---

## Network & Port Reference

| Port | Service | Description | Expose Externally? |
|------|---------|-------------|--------------------|
| **4280** | UI (SWA CLI) | Web interface | ✅ Yes |
| **7071** | api-proxy (nginx) | Unified API + TiTiler proxy | ✅ Yes |
| **8000** | TiTiler (direct) | COG tile server | ❌ Optional (use proxy) |
| **10000** | Azurite Blob | Blob Storage emulator | ✅ Yes (UI reads blobs directly) |
| **10001** | Azurite Queue | Queue Storage emulator | ❌ Internal only |
| **10002** | Azurite Table | Table Storage emulator | ❌ Internal only |

### Firewall / NSG Rules

For access from a remote browser (e.g. your laptop connecting to a cloud VM):

```bash
# Allow traffic on required ports
sudo ufw allow 4280/tcp    # UI
sudo ufw allow 7071/tcp    # API proxy
sudo ufw allow 10000/tcp   # Azurite blob (direct reads from browser)
```

For Azure VMs, add **Inbound Security Rules** to the VM's **Network Security Group (NSG)**
for ports 4280, 7071, and 10000.

### Docker Network

Docker Compose creates a network named **`docker_default`** (prefixed by the compose
project name, which defaults to the folder name `docker`). Spawned training containers
must join this network so they can resolve `azurite` by hostname.

---

## Volume & Storage Reference

### Named Volumes

| Volume | Mounted In | Mount Path | Purpose |
|--------|------------|------------|---------|
| `azurite-data` | azurite | `/data` | Persistent blob/queue data |
| `azurite-data` | hastefuncqueues | `/shared/azurite` | LocalRunner reads/writes output files directly on the Azurite volume |

### Bind Mounts

| Host Path | Container Path | Service(s) | Purpose |
|-----------|----------------|------------|---------|
| `../data` | `/app/data` | hastefuncapi, hastefuncqueues | Optional local data directory |
| `/var/run/docker.sock` | `/var/run/docker.sock` | hastefuncapi, hastefuncqueues | Allows spawning sibling containers |
| `./nginx.conf` | `/etc/nginx/nginx.conf` | api-proxy | NGINX configuration (read-only) |

### Data Flow

1. The UI uploads imagery → **hastefuncapi** stores it in **Azurite** blobs.
2. **hastefuncapi** places a message on the image queue.
3. **hastefuncqueues** picks up the message, spawns `haste-imageryprep` container.
4. `haste-imageryprep` reads from Azurite, processes imagery, writes outputs back.
5. Training/inference similarly: queue message → spawn `haste-training` container → write outputs.
6. **hastefuncapi** reads outputs from Azurite and returns URLs to the UI.
7. **TiTiler** reads COGs from Azurite to serve map tiles.

---

## How the Local Runner Works

When `RUNNER_TYPE=local`, the `hastefuncqueues` service uses a **LocalRunner** instead
of Azure Batch. Here's what happens under the hood:

1. A queue message arrives (e.g. `local-train-queue`).
2. The queue trigger function deserializes the task configuration.
3. LocalRunner calls the Docker API (via the mounted socket) to create and start a container:
   - **Image:** `haste-training:latest` or `haste-imageryprep:latest`
   - **GPU:** `--gpus all` (if `HASTE_ENABLE_GPU=1`)
   - **Network:** Attaches to `docker_default` so the container can reach `azurite` by hostname.
   - **Volumes:** Mounts the shared `docker_azurite-data` volume.
   - **Memory:** Capped at `HASTE_DOCKER_MEM_LIMIT`; shared memory set to `HASTE_DOCKER_SHM_SIZE`.
4. The spawned container runs the workflow (e.g. `fine_tune.py` or `inference.py`).
5. Outputs are written to the Azurite volume at `/shared/azurite/__blobstorage__/...`.
6. The container exits; LocalRunner reads the exit code and logs.
7. Post-processing runs inside `hastefuncqueues` to update metadata, generate stats, etc.

> **Key difference from Azure Batch:** In local mode, inference outputs go into an
> `inference/` subfolder, whereas Azure Batch writes them at the top level. The
> `InferencePostprocessor` handles this conditionally based on `runner_type`.

---

## Using the Application

### Accessing the UI

Open a browser and navigate to:

```
http://<HOST_IP>:4280
```

> The SWA mock-login portal still appears for the UI. Keep its default roles,
> enter any user ID and username, and select **Login**. The Docker-only UI
> configuration accepts the default `authenticated` role, and
> `DEVELOPMENT_MODE=true` auto-creates that local user as an administrator.

### Creating a Project

1. Click **"New Project"** on the dashboard.
2. Enter a project name and description.
3. Select the **Source Type** (e.g. "Azure Blob", "Maxar", etc.).
4. The project is created and a blob folder structure is provisioned in Azurite.

### Uploading Imagery

1. Open your project → **Imagery** tab.
2. Upload pre-event and post-event satellite GeoTIFF files.
3. The upload goes to Azurite. An image-processing queue message is created.
4. `hastefuncqueues` picks it up and runs `haste-imageryprep` to:
   - Download/validate the imagery
   - Create Cloud-Optimized GeoTIFFs (COGs)
   - Generate tile indices
5. Once processing completes, imagery appears in the map viewer.

### Running Training

1. Open your project → **Training** tab.
2. Configure training parameters:
   - **Epochs:** 5–50 (start small for testing)
   - **Batch Size:** See the memory tuning table above
   - **Base Model:** Select a pre-trained model
3. Click **"Start Training"**.
4. Watch progress in the queue-worker logs:
   ```bash
   docker compose logs -f hastefuncqueues
   ```
5. To see the GPU container's own logs:
   ```bash
   docker ps -a --filter ancestor=haste-training:latest
   docker logs <container_id>
   ```

### Running Inference

1. Go to **Inference** tab → select a trained model.
2. Click **"Run Inference"**.
3. The LocalRunner spawns a `haste-training` container with `inference.py`.
4. Outputs include:
   - A damage-assessment **GeoPackage** (`.gpkg`)
   - A **predicted damage layer** COG for visualization
5. When complete, `gpkgUrl` and `predictedDamageLayerUrl` are populated in the metadata.

### Viewing Results in the Visualizer

1. Navigate to the **Visualizer** for your completed inference.
2. If `VITE_AZURE_MAPS_CLIENT_ID` is set and Azure Maps auth is configured, you'll get an interactive **before/after swipe map**.
3. The overlay shows damage classifications color-coded by severity.
4. Download the GeoPackage for GIS analysis in QGIS, ArcGIS, etc.

---

## Rebuilding the Haste Wheel

The `hastelib/` directory contains the shared Python library (`hastegeo` package) used by
the API services, imageryprep, and training containers. In the Docker deployment, the
source is **copied directly** into images (no wheel install needed).

However, if deploying to Azure (non-Docker), you'll need a wheel:

```bash
cd hastelib

# Build the wheel (auto-bumps version, uploads to blob, updates requirements.txt)
python haste_build.py

# Or build manually without the custom script:
pip install build hatchling
python -m build --wheel
```

The custom `haste_build.py` script:
1. Increments the version in `src/hastegeo/__about__.py`
2. Builds a `.whl` file under `hastelib/dist/`
3. Uploads it to `researchlabwuopendata.blob.core.windows.net/haste-binaries/` (requires `az login`) and removes the local copy from `hastelib/dist/`
4. Rewrites the `hastegeo @ <url>` line in `api/hastefuncapi/requirements.txt`, `api/hastefuncqueues/requirements.txt`, and `docker/imageryprep/requirements.txt` so they pin the new wheel URL

> **For local Docker**, you do NOT need to rebuild the wheel — the Dockerfiles
> copy the source directly with `COPY hastelib/src/hastegeo /home/site/wwwroot/hastegeo`.

---

## Common Operations Cheat-Sheet

### Starting & Stopping

```bash
# Start everything
docker compose up -d

# Stop everything (preserves volumes)
docker compose down

# Stop and destroy all data
docker compose down -v

# Restart a single service
docker compose restart hastefuncapi
```

### Building

```bash
# Rebuild a single service
docker compose up -d --build hastefuncapi

# Rebuild everything from scratch (no cache)
docker compose build --no-cache

# Rebuild only the training image
docker compose build training_image
```

### Viewing Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f hastefuncqueues

# Last 100 lines
docker compose logs --tail=100 hastefuncqueues

# Spawned training container
docker ps -a --filter ancestor=haste-training:latest
docker logs <container_id>
docker logs -f <container_id>   # Follow live
```

### Inspecting State

```bash
# List running containers
docker compose ps

# Check Azurite is healthy
curl http://localhost:10000/devstoreaccount1?comp=list

# Check API functions loaded
curl http://localhost:7071/api/GetAdminSettings

# Check TiTiler health
curl http://localhost:8000/healthz

# See what queues exist
curl "http://localhost:10001/devstoreaccount1?comp=list"
```

### Data Management

```bash
# Reset all data (Azurite blobs, queues, etc.)
docker compose down -v
docker compose up -d

# Re-run data initialization only
docker compose up -d data-init

# View Azurite blob containers
curl "http://localhost:10000/devstoreaccount1?comp=list&include=metadata"
```

### Fixing Common Issues Quickly

```bash
# Restart nginx (fixes 502 errors after container IP changes)
docker restart docker-api-proxy-1

# Force re-seed Azurite data
docker compose rm -f data-init
docker compose up -d data-init

# Kill a stuck training container
docker ps -a --filter ancestor=haste-training:latest
docker rm -f <container_id>
```

---

## Troubleshooting

### UI loads but shows "Network Error" or blank page

| Check | Command | Fix |
|-------|---------|-----|
| `HOST_IP` is set | `cat .env` | Set it to the VM's public IP |
| API proxy is running | `docker compose ps api-proxy` | `docker compose up -d api-proxy` |
| nginx can reach the API | `docker logs docker-api-proxy-1` | Restart: `docker restart docker-api-proxy-1` |
| Functions loaded | `curl http://localhost:7071/api/GetAdminSettings` | Check hastefuncapi logs |

### API returns 500 errors

```bash
# Check function app logs
docker compose logs --tail=200 hastefuncapi

# Common causes:
# - Azurite not ready → restart hastefuncapi
# - haste module import error → check Dockerfile copies hastelib correctly
```

### Training/Inference job stuck or fails

```bash
# 1. Check the queue worker logs
docker compose logs -f hastefuncqueues

# 2. Find the spawned training container
docker ps -a --filter ancestor=haste-training:latest

# 3. Check its logs
docker logs <container_id>

# 4. Common issues:
#    - OOM (killed by signal) → increase HASTE_DOCKER_SHM_SIZE / HASTE_DOCKER_MEM_LIMIT
#    - "no such network" → verify HASTE_DOCKER_NETWORK matches `docker network ls`
#    - "no such volume" → verify HASTE_DOCKER_AZURITE_VOLUME matches `docker volume ls`
```

### GPU not detected in training containers

| Symptom | Cause | Fix |
|---------|-------|-----|
| `nvidia-smi` works on host but not in container | nvidia-container-toolkit not installed | See [NVIDIA Container Toolkit](#3-nvidia-container-toolkit-gpu-vms-only) |
| `nvidia-ctk` configured but GPU still not visible | Docker needs restart | `sudo systemctl restart docker` |
| "Secure Boot" errors in `dmesg` | NVIDIA modules blocked | Disable Secure Boot in BIOS/UEFI |
| Snap Docker installed | Snap Docker lacks GPU support | Remove snap, install Docker CE |

### TiTiler returns 502 or tiles don't load

```bash
# Check TiTiler is running
docker compose ps titiler
curl http://localhost:8000/healthz

# Restart the proxy
docker restart docker-api-proxy-1

# Verify the proxy config routes /api/titiler/ correctly
docker exec docker-api-proxy-1 cat /etc/nginx/nginx.conf
```

### Visualizer page crashes

If you see `Cannot read properties of undefined (reading 'remove')`:
- This was a known bug — the map controls were accessed before Azure Maps initialized.
- Ensure you're on the latest code.

### Inference completes but `gpkgUrl` / `predictedDamageLayerUrl` are null

- This indicates the post-processor couldn't find the output files at the expected path.
- In local mode, inference outputs are in an `inference/` subfolder.
- Ensure the `haste` library version is ≥ 0.0.1001 (contains the `runner_type` conditional fix).

### "Container already exists" messages in data-init logs

- **These are benign.** The data-init script handles `ResourceExistsError` gracefully.

### Docker network/volume name mismatch

Docker Compose prefixes network and volume names with the **project name** (defaults to
the parent folder name). If your `docker-compose.yml` is in a folder named `docker/`:

```
Network name:  docker_default
Volume name:   docker_azurite-data
```

If you renamed the folder or use `-p`, update these in `docker-compose.yml`:
```yaml
HASTE_DOCKER_NETWORK: "<project>_default"
HASTE_DOCKER_AZURITE_VOLUME: "<project>_azurite-data"
```

Verify with:
```bash
docker network ls | grep default
docker volume ls | grep azurite
```

---

## Production Considerations

When transitioning from local Docker to a production deployment:

| Concern | Local Docker | Production |
|---------|-------------|------------|
| Storage | Azurite emulator | Azure Blob + Queue Storage |
| Authentication | `DEVELOPMENT_MODE=true` (anonymous) | `DEVELOPMENT_MODE=false` (Azure AD) |
| Runner | `RUNNER_TYPE=local` (Docker containers) | `RUNNER_TYPE=azure_batch` (Azure Batch pools) |
| SSL/TLS | None (HTTP) | Terminate TLS at nginx or Azure Front Door |
| Monitoring | `docker compose logs` | Azure Application Insights |
| Scaling | Single VM | Azure Batch auto-scaling pools |
| Data backup | Docker volumes | Azure Storage geo-redundancy |
| Docker images | Built locally | Pushed to Azure Container Registry (ACR) |

---

## File Reference

| File | Purpose |
|------|---------|
| `docker/docker-compose.yml` | Main orchestration file — all service definitions |
| `docker/nginx.conf` | NGINX reverse proxy config (CORS, API routing, TiTiler proxy) |
| `docker/.env` | Environment overrides (HOST_IP, memory settings, Azure Maps client ID) |
| `docker/emulators/Dockerfile` | Azurite storage emulator image |
| `docker/data-init/Dockerfile` | Init container that seeds Azurite with config and queues |
| `docker/data-init/upload_data.py` | Python script for the init container |
| `docker/training/Dockerfile` | GPU training image (CUDA 12.4 + conda `bda` env) |
| `docker/training/env/env.yml` | Conda environment definition for training |
| `docker/imageryprep/Dockerfile` | Imagery preparation image |
| `docker/titiler/Dockerfile` | TiTiler COG tile server image |
| `docker/ui/Dockerfile` | UI image (same as `ui/Dockerfile`) |
| `api/hastefuncapi/Dockerfile` | HTTP API Azure Functions image |
| `api/hastefuncapi/startup.py` | Startup script (waits for Azurite, regenerates stats) |
| `api/hastefuncapi/entrypoint.sh` | Container entrypoint (runs startup.py then Functions host) |
| `api/hastefuncqueues/Dockerfile` | Queue worker Azure Functions image |
| `setup/config_admin_settings.json` | Seed config (source types, base models, labeling settings) |
| `ui/.env.docker` | Default UI environment (baked into Docker image, overridden by compose) |
| `ui/swa-cli.config.json` | SWA CLI configuration (uses `local` profile in Docker) |
| `local.settings.example.jsonc` | Template for non-Docker local development (not used in Docker) |
