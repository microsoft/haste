# Execution Plan: Infrastructure as Code Migration (Bicep + azd)

## Phases

### Phase 0: Spec & ADR — done

**Goal:** Lock the approach.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| ADR-0003 (Bicep + azd decision) | `backend-dev` | — | — | completed |
| Feature spec (README, design, user-stories, plan) | `backend-dev` | ADR | — | completed |

**Exit Criteria:**
- [x] ADR recorded in `spec/architecture/decisions/`
- [x] Feature spec drafted

---

### Phase 1: Bicep modules reproducing current state — done

**Goal:** Stand up `infra/` Bicep that mirrors the resources created by
`setup_infra.sh`, validated with `what-if` against a live environment.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| **As-built inventory** of live env (RG resources + sub-scope custom roles/assignments incl. ACS and the SWA invitation role) | `backend-dev` | Phase 0 | US-001, US-002 | completed |
| `infra/main.bicep` (subscription scope, RG + module wiring) | `backend-dev` | Inventory | US-001, US-002 | completed |
| `infra/main.bicepparam` (typed params, flags, shared refs) | `backend-dev` | main.bicep | US-002 | completed |
| `modules/identity.bicep` (UMI + built-in role assignments) | `backend-dev` | main.bicep | US-002 | completed |
| `modules/roles.bicep` (custom SWA invitation role + assignment to function identity) | `backend-dev` | identity, frontend | US-006 | completed |
| `modules/network.bicep` (vnet, subnets, nsg, endpoints) | `backend-dev` | main.bicep | US-002 | completed |
| `modules/storage.bicep` (func storage + premium file share + rules) | `backend-dev` | identity, network | US-002 | completed |
| `modules/monitoring.bicep` (Log Analytics + App Insights) | `backend-dev` | main.bicep | US-002 | completed |
| `modules/communication.bicep` (ACS + email service + sender domain) | `backend-dev` | main.bicep | US-002, US-004 | completed |
| `modules/apim.bicep` (service + apis + backends + policies) | `backend-dev` | identity, network | US-002 | completed |
| `modules/functions.bicep` (3 Flex Consumption apps) | `backend-dev` | storage, monitoring | US-002 | completed |
| `modules/batch.bicep` (dual create-vs-BYO account; pool autoscale + container config; pool can be created on an existing shared account via cross-RG scope) | `backend-dev` | identity, network | US-002 | completed |
| `modules/frontend.bicep` (SWA + Maps) | `backend-dev` | main.bicep | US-002 | completed |
| `modules/frontdoor.bicep` (feature-flagged Front Door + WAF) | `backend-dev` | frontend | US-002 | completed |
| Validate `az bicep build` + `what-if` vs live RG | `backend-validation` | All above | US-001 | completed |

**Exit Criteria:**
- [x] All modules compile (`az bicep build`)
- [x] `what-if` for a fresh `dev2` environment is clean (42 creates, 0 modify, 0 delete; 5 additive role assignments flagged as unsupported-by-what-if only), reviewed against the env RG **and** `sharedResourceGroup` (cross-RG Batch pool on the shared account)

---

### Phase 2: azd orchestration + app deploy — done

**Goal:** Wire `azure.yaml` so `azd up` provisions and deploys.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| `azure.yaml` (api, titiler, queues, web services) | `backend-dev` | Phase 1 | US-001 | completed |
| Map Bicep outputs → azd service targets | `backend-dev` | azure.yaml | US-001 | completed |
| `azd provision` + `azd deploy` end-to-end test | `backend-validation` | azure.yaml | US-001 | completed |
| `web` frontend config: `ui/.env.production` (static routes) + `VITE_AZURE_MAPS_CLIENT_ID` provision output | `backend-dev` | azure.yaml | US-001 | completed |
| `web` SWA publish via `deploy/deploy-web.ps1` postdeploy hook (`swa deploy --env production`) — replaces the azd `web` service | `backend-dev` | azure.yaml | US-001 | completed |

**Exit Criteria:**
- [x] `azd provision` stands up a fresh `dev2` environment (idempotent adopt of the Bicep deploy)
- [x] All three Function Apps deployed via `azd deploy` (api, titiler, queues) and reachable
- [x] `web` (SWA) frontend config wired — resolved *not* via `.env.dev2`/`build:dev2`/AAD registration
      (the current UI dropped those inputs). Deployed build needs only the static `/api/haste/*` routes
      (committed `ui/.env.production`) plus the per-env Azure Maps client id (`VITE_AZURE_MAPS_CLIENT_ID`
      provision output). SWA EasyAuth uses the built-in Entra provider (no custom registration); role
      assignment is the Phase 3 invitation hook.
- [x] `web` deployed to the SWA **production** environment and confirmed live (dev2): `default` env
      `Ready`; `/` → 302 `/login` → `/.auth/login/aad`; placeholder gone. Deployed via
      `deploy/deploy-web.ps1` (postdeploy), **not** an azd `web` service — azd only passes
      `swa deploy --env production` when no `swa-cli.config.json` is in the service path, and that file
      is required for local `swa start`. The hook builds the UI and calls `swa deploy --env production`
      explicitly with the SWA token, preserving one-command `azd up`.
- [x] **api/queues application settings ported to Bicep.** Root cause of the api/queues 404s: the
      `functions`/`functionApp` modules set only 4 base settings (storage + App Insights); the ~30
      hastegeo **app** settings the legacy `setup_infra.sh` set (`env`, `BLOB_*`, `QUEUE_*`,
      `*_STORAGE_TYPE`, `RUNNER_TYPE`, `DATA_PATH`, `AZURE_BATCH_*`, `STATIC_APP_*`, `EMAIL_*`,
      `TITILER_ENDPOINT`) were missing, so `hastegeo`'s import-time `Config()` left the worker unable to
      index `function_app.py` → 0 functions. Now `functionApp.bicep` takes an `appSettings` array and
      `functions.bicep` builds a shared set for api + queues only (titiler excluded). Storage/queue via
      managed identity (`BLOB_ACCOUNT_URL` + existing role grants); `BLOB_CONNECTION_STRING` / batch key
      (cross-RG existing ref) / ACS string via `listKeys()`/outputs (no Key Vault). Proven on dev2:
      manual set → api indexed (404→401), queues indexed 7 triggers; then encoded in Bicep (what-if clean).
- [x] Full one-shot `azd up` from a clean env confirmed (dev3, 2026-07-02): provision → 3 function
      apps (41 ops indexed) → postdeploy (SWA→production, 41 APIM ops synced, backend keys injected,
      first-admin seeded). Zero manual steps; SWA serves the auth-gated app; APIM→func routing = 200.
      Caught + fixed a fresh-provision-only bug: `apimApis` backends can't `listKeys` the func host key
      at provision time (host not running) → backends are now credential-less in Bicep and the key is
      injected by the postdeploy hook.

---

### Phase 3: Imperative hooks + email domain — done

**Goal:** Port the imperative tail and finish the email sender-domain wiring. No
Key Vault is introduced — derived secrets are deploy-time outputs wired by Bicep.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| APIM base APIs + backends + product links + hardcoded ops (`infra/modules/apimApis.bicep`) — the service alone left dev2 APIM empty, so the app's API routing was broken | `backend-dev` | Phase 2 | US-003 | completed |
| APIM per-endpoint operation sync (`deploy/sync-apim-operations.ps1`, postdeploy) — additive, from the deployed function list; backend routing via an API-level `set-backend-service` policy so no per-op policy (avoids az rest's BOM-response bug on Windows) | `backend-dev` | Phase 2 | US-003 | completed |
| Seed storage defaults (`deploy/seed-storage-defaults.ps1`) — admin settings **and** the first-admin user (`users_acl.json`), firewall open → **account-key** upload (skip-if-exists) → restore. Account key because the deployer has no blob-data RBAC (only the func identity does) — the old `--auth-mode login` version failed silently. The first-admin seed is required: a fresh env has no `users_acl.json`, so `GetUserById` throws before the auto-create and the UI renders blank. | `backend-dev` | Phase 2 | US-003 | completed |
| `DEVELOPMENT_MODE` dev-only Bicep param (`developmentMode`, default false; dev2→true via `HASTE_DEVELOPMENT_MODE`) — auto-provision + anonymous auth. Prod stays false and manages users explicitly. | `backend-dev` | Phase 2 | US-003 | completed |
| Self-invite the deployer (`deploy/invite-user.ps1`) — admin+contributor, listUsers dedup, requires `domain` in the body | `backend-dev` | Phase 2 | US-003 | completed |
| `deploy/postdeploy.ps1` orchestrator (web publish → apim sync → admin settings → invite) + `azure.yaml` wiring | `backend-dev` | Phase 2 | US-003 | completed |
| Wire ACS connection string output → function app settings | `backend-dev` | Phase 1 | US-004 | completed (part of the api/queues app-settings port; `EMAIL_CONNECTION_STRING`/`EMAIL_SENDER` from the communication module) |
| Custom-domain DNS record hook (only when `emailSenderDomainType=Custom`) | `backend-dev` | Phase 1 | US-004 | dropped — the legacy scripts never provisioned email domains/DNS (email was an external prerequisite). Bicep provisions the Azure-managed domain; custom-domain DNS lives in the customer's zone and is out-of-band |
| Validate hook idempotency + confirm no manual/plain-text secret | `backend-validation`, `security-validation` | hooks | US-003, US-004 | completed |
| Designated first admin (`HASTE_FIRST_ADMIN_EMAIL`) — the seed + invite hooks honor it, falling back to the signed-in deployer; closes the CI/service-principal gap where a non-interactive prod deploy has no signed-in user and would end up with no admin | `backend-dev` | seed + invite hooks | US-003 | completed |
| Transparent Batch image tags (`deploy/resolve-batch-image-tags.ps1`, preprovision) — when `batchPoolMode=Existing`, reads the shared pool's `containerImageNames` and sets `HASTE_TRAINING_IMAGE`/`HASTE_IMAGERYPREP_IMAGE` (never clobbering an explicit override), so operators don't hand-match the immutable pool's tags | `backend-dev` | Phase 2 | US-003 | completed |

**Exit Criteria:**
- [x] Hooks run idempotently on repeat `azd up` — op-sync skips existing ops; admin-settings skips-if-exists; invite dedups on accepted users. Validated on dev2.
- [x] No human-supplied secret — APIM backend keys via `listKeys()`, storage via managed identity + `listKeys()`, ACS from the communication output; nothing plaintext in the repo (detect-secrets passes). Email works with the Azure-managed default domain.
- [x] APIM routing proven on dev2: `GET /api/haste/GetAzureMapsToken` through APIM → function backend → **200** (API-level policy + injected host key). Base APIs + 41 api ops + titiler + storage-proxy ops all live.
- Note: SWA→APIM uses the SWA-managed product subscription; the full SWA→app path needs a browser login to confirm (routing itself is proven; structure matches the working dev1/prod).

---

### Phase 4: Retire bash + docs — done

**Goal:** Remove the legacy scripts and document the azd workflow.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Remove `setup/setup_infra.sh`, `setup/deploy_apps.sh` | `backend-dev` | Phases 1–3 confirmed | US-005 | completed |
| Rewrite `setup/README.md` for azd | `backend-dev` | — | US-005 | completed |
| Update `docs/deployment.md` | `backend-dev` | — | US-005 | completed |
| Document configuration modes (Batch create-vs-BYO + image-tag immutability, email sender domain, Front Door flag, development mode, first-admin seed) in `docs/configuration.md` | `backend-dev` | — | US-005 | completed |
| Update spec statuses → implemented | `orchestrator` | All | — | completed |

**Exit Criteria:**
- [x] Legacy scripts removed
- [x] Docs describe only the azd workflow

---

### Phase 5 (stretch): CI integration — TBD

**Goal:** Switch the pipeline deploy path to azd.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Update `.github/workflows/deploy-apps.yml` to `azd provision`/`azd deploy` (retire `.github/scripts/deploy_apps.sh`) | `backend-dev` | Phase 4 | — | not-started |

**Exit Criteria:**
- [ ] Pipeline deploys via azd

---

## Milestones

| Milestone | Date | Deliverable |
|---|---|---|
| Spec approved | TBD | Signed-off design docs + ADR |
| Bicep parity | TBD | `what-if` clean against live env |
| azd up working | TBD | One-command provision + deploy |
| Hooks + email domain | TBD | Imperative tail + ACS sender domain |
| Bash retired | TBD | Legacy scripts removed, docs updated |

## Agent Summary

| Agent | Tasks Owned | Phases |
|---|---|---|
| `backend-dev` | 22 | 0–5 |
| `backend-validation` | 3 | 1, 2, 3 |
| `security-validation` | 1 | 3 |
| `orchestrator` | 1 | 4 |

## Resource Requirements

- **Agents:** `backend-dev`, `backend-validation`, `security-validation`, `orchestrator`.
- **Tools:** Azure CLI, Bicep CLI, Azure Developer CLI (`azd`), PowerShell (`pwsh`).
- **Azure access:** A subscription + a non-production environment for `what-if`
  parity validation.

## Open Questions

- [x] **CI switch — resolved (2026-06-25): separate follow-up.** Kept as Phase 5
      (stretch). Target is `.github/workflows/deploy-apps.yml` (the real deploy
      CI), not `azure-pipelines.yml` (scans only). Cut over as its own PR after
      local `what-if` parity is confirmed.
- [x] **Key Vault — resolved (2026-06-25): dropped.** Provision ACS in-IaC so the
      email connection string is a deploy output, not a stored secret. No Key
      Vault module; managed-identity hardening for ACS + Batch is a follow-up.
- [x] **Resource naming — resolved (2026-06-25): keep `prefix` + `randomSuffix`.**
      Required for `what-if` parity with existing deployments; azd's
      `resourceToken` would rename everything. Suffix may auto-default for new
      envs but stays overridable.
