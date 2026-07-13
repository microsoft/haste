# HASTE UI

The web front end for HASTE (High-speed Assessment and Satellite Tracking for
Emergencies) — a React single-page application for managing disaster-assessment
projects, labeling imagery, running models, and visualizing results.

## Tech stack

- **React** + **Vite** (build toolchain and dev server)
- **Fluent UI** component library
- **Azure Maps** (`azure-maps-control`, `azure-maps-drawing-tools`) for
  interactive map rendering and labeling
- **MSAL** for Microsoft Entra ID authentication
- Served in production behind **Azure Static Web Apps**; proxied to the
  `hastefuncapi` Function App for `/api/*` requests

## Prerequisites

- Node.js 20+ (the container image builds on Node 24)
- The HASTE backend running locally (see the repo-root
  [QUICKSTART.md](../QUICKSTART.md) and
  [docker/README.md](../docker/README.md)) or a configured remote API

## Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start the Vite dev server (uses `--mode env`) |
| `npm run build` | Production build to `dist/` |
| `npm run lint` | Run ESLint (must pass with zero warnings) |
| `npm run preview` | Preview a production build locally |

Environment-specific builds are also available: `build:development`,
`build:dev1`, and `build:testing`.

## Configuration

The app reads `VITE_*` environment variables (API base URL, TiTiler URL, Azure
Maps and MSAL settings) at build time. See the environment files and the
[Configuration Guide](https://microsoft.github.io/haste/configuration.html) for
the full list.

## Documentation

Full project documentation is published at
**[https://microsoft.github.io/haste](https://microsoft.github.io/haste)**, including
the [User Guide](https://microsoft.github.io/haste/usage/overview.html).
