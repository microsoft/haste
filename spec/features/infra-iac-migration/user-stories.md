# User Stories: Infrastructure as Code Migration (Bicep + azd)

## Personas

| Persona | Description | Key Goals |
|---|---|---|
| Platform Engineer | Provisions and operates HASTE Azure environments | One-command, cross-platform, previewable deploys |
| Project Manager | Stands up a new HASTE environment for a disaster response engagement | Fast, reliable environment creation without bash expertise |
| Admin | Configures system settings and bootstraps the first user | Reproducible setup, secrets handled safely |

---

## Stories

### US-001: Cross-platform one-command provision + deploy

**As a** platform engineer,
**I want to** provision and deploy a full HASTE environment with `azd up` on
Windows, macOS, or Linux,
**So that** I am not blocked by bash/`jq` and can deploy from my normal machine.

**Priority:** P1
**Estimate:** L
**Component(s):** `infra/`, `azure.yaml`

**Acceptance Criteria:**

```gherkin
Given a clean subscription and a configured azd environment
When I run "azd up"
Then the resource group and all HASTE resources are provisioned from Bicep
And the three Function Apps and the Static Web App are deployed
And no bash or jq dependency is required
```

```gherkin
Given an existing HASTE environment
When I run "azd provision --preview"
Then a what-if report is shown
And it reports no changes when the Bicep matches the live state
```

**Notes:** Reproduces the resource set from `setup_infra.sh`.

---

### US-002: Declarative, reviewable infrastructure modules

**As a** platform engineer,
**I want** every Azure resource expressed as a typed Bicep module under `infra/`,
**So that** changes are validated, diffable, and code-reviewed before apply.

**Priority:** P1
**Estimate:** L
**Component(s):** `infra/modules/`

**Acceptance Criteria:**

```gherkin
Given the infra/ Bicep tree
When I run "az bicep build" / "azd provision --preview"
Then all modules compile and type-check with no errors
And identity, roles, storage, network, monitoring, communication, apim,
  functions, batch, and frontend resources are all represented
```

```gherkin
Given enableFrontDoor is false
When I provision
Then the Front Door + WAF module is not deployed
```

```gherkin
Given batchAccountMode is Create and batchPoolMode is Create
When I provision
Then a Batch account and a GPU pool are created in the environment resource group
```

```gherkin
Given batchAccountMode is Existing with an account in a shared resource group
And batchPoolMode is Create
When I provision
Then only a new named pool is created on the shared account via a cross-RG-scoped sub-module
And no existing pool on the shared account is modified or deleted
```

```gherkin
Given batchAccountMode is Existing and batchPoolMode is Existing
When I provision
Then the existing account and pool are referenced for app-settings wiring only
And nothing is written to the shared resource group
```

**Notes:** Front Door module is feature-flagged, default off. Batch supports
create-vs-BYO via `batchAccountMode` + `batchPoolMode`; pool creation on a shared
account is additive-only and `what-if` must be reviewed against both the env RG
and `sharedResourceGroup`.

---

### US-003: Imperative tail as idempotent PowerShell hooks

**As an** admin,
**I want** APIM operation import, admin-settings upload, and the bootstrap user
invitation to run as azd hooks,
**So that** the post-provision steps from the old script still happen, on any OS.

**Priority:** P1
**Estimate:** M
**Component(s):** `deploy/`

**Acceptance Criteria:**

```gherkin
Given provisioning has completed
When the postprovision and postdeploy hooks run
Then APIM operations are imported from live function metadata
And config_admin_settings.json is uploaded to the data container
And a bootstrap user invitation URL is produced
```

```gherkin
Given the hooks have already run once
When I run azd up again
Then each hook checks-before-create and makes no duplicate changes
```

**Notes:** PowerShell (`pwsh`) replaces the bash functions; parity with current
idempotency guards.

---

### US-004: Provision the email backend so there is no manual secret

**As an** admin / partner operator,
**I want** the email backend (Azure Communication Services) provisioned by the
IaC with a configurable sender domain,
**So that** `azd up` is one-step with no manually pasted connection string, and
forks can choose an Azure-managed or custom sender domain.

**Priority:** P2
**Estimate:** M
**Component(s):** `infra/modules/communication.bicep`, `infra/modules/functions.bicep`

**Acceptance Criteria:**

```gherkin
Given emailSenderDomainType is AzureManaged
When I run azd up
Then ACS and an azurecomm.net sender domain are provisioned
And the email connection string is wired from a deploy-time output
And no connection string is manually supplied and no DNS step is required
```

```gherkin
Given emailSenderDomainType is Custom and emailCustomDomain is set
When provisioning completes
Then a custom sender domain is provisioned
And a hook prints the TXT/SPF/DKIM records to verify out-of-band
```

**Notes:** No Key Vault is introduced — the connection string is a deploy-time
`listKeys()` output. Moving ACS + Batch to managed-identity auth is a follow-up.

---

### US-005: Retire bash scripts and update docs

**As a** project manager,
**I want** the old bash scripts removed and the docs rewritten for azd,
**So that** there is one clear, current way to deploy HASTE.

**Priority:** P2
**Estimate:** S
**Component(s):** `setup/`, `docs/deployment.md`

**Acceptance Criteria:**

```gherkin
Given azd parity is confirmed against a live environment
When the migration completes
Then setup_infra.sh and deploy_apps.sh are removed
And setup/README.md and docs/deployment.md describe the azd workflow
```

**Notes:** Only after US-001..US-003 are validated.

---

### US-006: Runtime invitation role for the API function app

**As a** platform engineer,
**I want** the custom role and assignment that lets the API function app issue
Static Web App user invitations modeled in IaC,
**So that** runtime user invitations keep working in a freshly provisioned
environment without a manual RBAC step.

**Priority:** P1
**Estimate:** S
**Component(s):** `infra/modules/roles.bicep`, `infra/modules/functions.bicep`

**Acceptance Criteria:**

```gherkin
Given the infra/ Bicep tree
When I provision
Then a custom role granting "microsoft.web/staticSites/*" is defined
And it is assigned at the Static Web App scope to the API app's system-assigned identity
```

```gherkin
Given the API function app is provisioned
When its identity is configured
Then it has both a system-assigned and a user-assigned identity
And DefaultAzureCredential resolves the system-assigned identity for the invitation call
```

```gherkin
Given a freshly provisioned environment
When an admin invites a user through the API
Then a Static Web App invitation URL is returned with no manual role assignment
```

**Notes:** Reproduces a manually-created role discovered in the as-built
inventory. The narrower legacy `createinvitation/action` role is retired (see
design.md), superseded by this broader role.

---

## Agent Assignment Map

### Available Agents

| Agent | Scope | Touches Code? |
|---|---|---|
| `backend-dev` | Python backend, API, processors, data layers, runners, **IaC (`infra/`, `azure.yaml`, `.github/workflows/`)** | Yes |
| `backend-validation` | Validates backend/IaC against specs, conventions, tests | No (validates only) |
| `security` | Secret handling, sender-domain config, dependency review | No (reports only) |
| `security-validation` | Validates security agent findings | No (validates only) |
| `orchestrator` | Records what agents did, tracks spec status | No (observes only) |

> Per `copilot-instructions.md`, `infra/`, `azure.yaml`, and
> `.github/workflows/` are owned by `backend-dev` / `backend-validation`.

### Story → Agent Mapping

| Story | Implementing Agent(s) | Validating Agent(s) | Notes |
|---|---|---|---|
| US-001 | `backend-dev` | `backend-validation` | azd provision + deploy; what-if parity check |
| US-002 | `backend-dev` | `backend-validation` | Bicep modules; `az bicep build` validation |
| US-003 | `backend-dev` | `backend-validation` | PowerShell hooks; idempotency check |
| US-004 | `backend-dev` | `security`, `security-validation` | Provision ACS; configurable sender domain; verify no manual/plain-text secret remains |
| US-005 | `backend-dev` | `backend-validation` | Script removal + docs after parity |
| US-006 | `backend-dev` | `backend-validation`, `security` | Custom invitation role (`roles.bicep`) + system-assigned identity; least-privilege review |

> **Rules applied:** `infra/`, `azure.yaml`, and `.github/workflows/` →
> `backend-dev` implements, `backend-validation` validates. Secret handling →
> `security` audits, `security-validation` confirms. `orchestrator` tracks all
> work (no per-story assignment).
