# HASTE — Secure Configuration Guidance (DRAFT)

| Field | Value |
|-------|-------|
| **Repository** | microsoft/haste |
| **Audience** | Customers / consumers / operators deploying HASTE |
| **Status** | DRAFT for tech review |
| **Last updated** | 2026-05-13 |

> **Note to reviewers (remove before publishing):** This draft is intended to live in the public HASTE docs site at `https://microsoft.github.io/haste/security-configuration.html` and to be cross-linked from `README.md`, `SECURITY.md`, and `docs/deployment.md`. Tech-review checklist at the end of the document.

---

## 1. Overview

HASTE (High-speed Assessment and Satellite Tracking for Emergencies) is an AI-driven framework for rapid disaster assessment using satellite imagery. The repository is published as a **library + reference deployment**: Microsoft operates the public reference deployment, while external consumers integrate the `haste_geo` Python library and may optionally redeploy the full stack (UI + Function Apps + Azure Batch) into their own subscription.

This guide tells you how to **configure HASTE securely** in your environment. It covers:

- Authentication, authorization, and role assignment
- Secrets and key management
- Network and transport configuration (CORS, CSP, TLS)
- Container and infrastructure hardening
- Logging, monitoring, and incident response
- Known security limitations and backward-compatibility caveats
- How to report a vulnerability

It is **not** a substitute for your own threat model. Treat HASTE as one component within a larger Azure workload and apply the [Microsoft Cloud Security Benchmark (MCSB)](https://learn.microsoft.com/security/benchmark/azure/) controls that apply to your overall workload.

---

## 2. Deployment models and their security posture

HASTE supports three deployment modes. Each has a distinct threat model.

| Mode | Intended use | Security posture |
|------|--------------|------------------|
| **Local development** (Docker Compose) | Single-developer evaluation only | Disabled auth, wildcard CORS, hardcoded dev keys (Azurite). **Never expose to a network beyond `localhost`.** |
| **Self-hosted Azure deployment** | Customer running HASTE in their own subscription | Production-grade if configured per this guide. Customer is responsible for SWA auth, Key Vault, RBAC, and infra hardening. |
| **Library-only integration** | Consuming the `haste_geo` Python package in your own application | You inherit only the library's process-level threat model; deployment-time controls are yours. |

**Required disclosure**: The local-development Docker Compose stack (`docker/docker-compose.yml`) mounts `/var/run/docker.sock` into containers to enable a local execution mode. This grants root-equivalent host access and is acceptable **only** on developer workstations. The file header documents this; this guide repeats it because it is the single most consequential local-vs-production gap.

---

## 3. Identity, authentication, and authorization

### 3.1 Authentication: rely on Azure Static Web Apps Easy Auth

HASTE's REST API does **not** implement its own authentication. It trusts the `x-ms-client-principal` header injected by [Azure Static Web Apps Easy Auth](https://learn.microsoft.com/azure/static-web-apps/authentication-authorization). For this to be safe:

- **The Function App must only be reachable through the Static Web App linked-backend route** (`/api/*`). Do **not** expose `*.azurewebsites.net` directly to the public internet. Use one of:
  - SWA linked backend (default and recommended)
  - VNet integration + private endpoint
  - Function App access restrictions (`az functionapp config access-restriction add`) that allow only SWA's outbound IPs
- **Use AAD (Entra ID) as the identity provider**, not the SWA mock auth or GitHub identity. Configure in `staticwebapp.config.json` and tenant settings.
- **Confirm `principal.userDetails` is the user's email** in your tenant. HASTE's user-management endpoint compares this field to the target user's email; if your IdP returns a different claim shape, self-service flows will fail closed (safe) but you should validate before rollout.

### 3.2 Authorization: roles

HASTE uses two SWA roles:

| Role | Capability |
|------|------------|
| `administrators` | Full admin: user management, group management, admin settings, deletes |
| `contributors` | Standard authenticated user: read project data, run jobs, edit own profile |

**Configuration guidance:**

- Assign roles via the [SWA role invitation flow](https://learn.microsoft.com/azure/static-web-apps/configuration#routes) or via the HASTE UI's user-invitation flow (gated by the `administrators` role).
- Apply the principle of least privilege: most users should be `contributors`. The `administrators` role grants the ability to manage other users, change roles, and modify global settings.
- Audit the list of administrators periodically. The HASTE UI's Admin → Users page shows the current set.

### 3.3 `DEVELOPMENT_MODE` must never be set in Azure

The `DEVELOPMENT_MODE` environment variable disables authentication and admin-role checks. It exists for local emulator testing only.

**Production**: Ensure `DEVELOPMENT_MODE` is **not** set in your Function App's Application Settings. Treat any nonzero value of this setting on an Azure-hosted Function App as a misconfiguration.

---

## 4. Secrets and key management

### 4.1 Use managed identity wherever possible

HASTE's Function Apps support [system-assigned managed identity](https://learn.microsoft.com/azure/app-service/overview-managed-identity) for:

- **Azure Maps** — Use `VITE_AZURE_MAPS_CLIENT_ID` (managed-identity client ID) instead of a subscription key. The UI fetches an AAD token from a dedicated `GetAzureMapsToken` endpoint exposed by the Function App. **Do not bake subscription keys into the client bundle.**
- **Azure Blob Storage** — Configure `BLOB_ACCOUNT_URL` and grant the Function App's identity the `Storage Blob Data Contributor` RBAC role on the storage account. Prefer this over `BLOB_CONNECTION_STRING` in production.
- **Azure Cosmos DB** — Use AAD authentication via `DefaultAzureCredential`; assign `Cosmos DB Built-in Data Contributor`.

### 4.2 Where connection strings are unavoidable, use Key Vault references

For services that do not yet support managed identity in your topology (e.g., Azure Communication Services email, Azure Batch account key on classic auth), store the secret in Key Vault and use [Key Vault references](https://learn.microsoft.com/azure/app-service/app-service-key-vault-references) in Application Settings:

```
EMAIL_CONNECTION_STRING = @Microsoft.KeyVault(SecretUri=https://<vault>.vault.azure.net/secrets/email-conn/...)
```

### 4.3 Function master keys

The deployment scripts (`setup/deploy_apps.sh`, `.github/scripts/deploy_apps.sh`) write the Function App master key to `.env` during setup. **Treat this file as sensitive and remove it from any machine that is not your local workstation.** Rotate this key periodically in production via:

```bash
az functionapp keys set --resource-group <rg> --name <function-app> --key-type masterKey --key-name default
```

### 4.4 Do not pass secrets as positional CLI arguments

If you author your own deploy scripts based on the HASTE templates, use the file form `az functionapp config appsettings set --settings @<file>.json` rather than `--settings KEY=VALUE` on the command line. Positional secrets leak via process tables and CI debug logs.

### 4.5 Disable basic-auth publishing after deployment

The deploy scripts set `properties.allow=true` for SCM/FTP publishing during deployment. **Disable basic-auth publishing on the Function App after deployment**:

```bash
az resource update --resource-group <rg> --name scm --namespace Microsoft.Web \
  --resource-type basicPublishingCredentialsPolicies \
  --parent sites/<function-app> --set properties.allow=false
az resource update --resource-group <rg> --name ftp --namespace Microsoft.Web \
  --resource-type basicPublishingCredentialsPolicies \
  --parent sites/<function-app> --set properties.allow=false
```

---

## 5. Network and transport security

### 5.1 CORS

- **Local development**: Use explicit origins (`http://localhost:5173,http://localhost:4280`). See `local.settings.example.jsonc`.
- **Production**: Set CORS to your UI's domain only. **Never use `*`** in production.

```bash
az functionapp cors add --resource-group <rg> --name <function-app> \
  --allowed-origins https://your-haste-ui.azurewebsites.net
```

### 5.2 HTTP security headers

Add a `staticwebapp.config.json` at the UI root with the following headers (minimum):

```json
{
  "globalHeaders": {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data: https://*.tile.openstreetmap.org https://*.azuremaps.com; connect-src 'self' https://*.azuremaps.com; style-src 'self' 'unsafe-inline'; script-src 'self'",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin"
  }
}
```

Tune `Content-Security-Policy` for the imagery providers and tile servers you actually use. The default above assumes Azure Maps and OpenStreetMap; widen only as needed.

### 5.3 TLS

- Static Web Apps and Function Apps enforce HTTPS by default. Do not disable.
- For custom domains, use [Azure-managed certificates](https://learn.microsoft.com/azure/static-web-apps/custom-domain) and verify auto-renewal.

### 5.4 CSRF

The UI's API client does **not** send explicit CSRF tokens; HASTE relies on the SWA Easy Auth session cookie having `SameSite=Lax` and on `Origin`/`Referer` enforcement at the SWA edge. If you front HASTE with a different reverse proxy or auth layer, validate that equivalent CSRF protection is in place — see §8.2.

---

## 6. Containers and infrastructure

### 6.1 Pin Docker base images to digests

For reproducible and supply-chain-safe builds, pin Docker base images to immutable digests rather than floating tags:

```dockerfile
FROM mcr.microsoft.com/azure-functions/python:4-python3.11@sha256:<digest>
```

Use [Dependabot for Docker](https://docs.github.com/code-security/dependabot/working-with-dependabot/about-dependabot-version-updates) to keep digests current.

### 6.2 Run containers as a non-root user

For production deployments to Azure Batch, AKS, or Container Apps, add a non-root `USER` directive to each Dockerfile after install steps:

```dockerfile
RUN useradd -m -u 10001 hasteuser
USER hasteuser
```

Verify file permissions on mounted volumes match the non-root UID.

### 6.3 Use ACR scanning and signed images

- Enable [Microsoft Defender for Cloud — Container scanning](https://learn.microsoft.com/azure/defender-for-cloud/defender-for-containers-introduction) on your Azure Container Registry.
- Tag images with the commit SHA (not `:latest`) when pushing for production use. The `build_and_push_images.sh` script accepts `-t <tag>`; pass a SHA.
- Consider [content trust / image signing](https://learn.microsoft.com/azure/container-registry/container-registry-content-trust) for high-assurance deployments.

### 6.4 Docker Compose hardening

The shipped `docker/docker-compose.yml` is **local-development only**. If you adapt it for any networked environment, add:

```yaml
security_opt:
  - no-new-privileges:true
cap_drop:
  - ALL
read_only: true   # where the workload allows it
```

And bind ports to `127.0.0.1` explicitly rather than `0.0.0.0`.

---

## 7. Logging, monitoring, and incident response

### 7.1 Enable Application Insights

```bash
az monitor app-insights component create --app haste-insights --location <region> --resource-group <rg>
az functionapp config appsettings set --name <function-app> --resource-group <rg> \
  --settings APPLICATIONINSIGHTS_CONNECTION_STRING="<conn-string>"
```

Recommended log retention: **90 days minimum** for security events; longer if regulatory requirements apply.

### 7.2 What HASTE logs (and what it does not)

- **Logs**: HTTP method + route, principal `userId`, job state transitions, errors with stack traces.
- **Does not log**: Request bodies, imagery contents, or values of admin settings — by design. If you require auditing of admin-config changes, layer Azure Activity Log or a custom audit trail on top.

### 7.3 Alerts to configure

At minimum, alert on:

- 5xx error rate > 1% for 5 minutes (API availability)
- Repeated 401/403 from a single principal (credential stuffing / role probing)
- Spikes in user-management calls (anomalous admin activity)
- Function App restart loops (potential exploit / crash)

### 7.4 Incident response — reporting vulnerabilities

If you discover a vulnerability in HASTE, **do not file a public GitHub issue.** Report it via:

- Microsoft Security Response Center: https://aka.ms/SECURITY.md and https://msrc.microsoft.com
- Encrypted email to `secure@microsoft.com` (PGP key on the MSRC site)

See [`SECURITY.md`](https://github.com/microsoft/haste/blob/main/SECURITY.md) in the repository.

---

## 8. Known security limitations and backward-compatibility notes

This section documents current limitations that customers must understand to configure HASTE securely. Each entry describes the limitation and the operational mitigation you should apply.

### 8.1 The API trusts the SWA-injected principal header without independent verification

HASTE's API trusts the `x-ms-client-principal` header from Azure Static Web Apps without performing independent signature verification. **This is safe only when the Function App is unreachable except through SWA's linked-backend route.** If you deploy the Function App with a publicly reachable endpoint, you must either:

- Front it with an API gateway that strips and re-injects identity, or
- Add network-level access restrictions so the Function App accepts traffic only from SWA's outbound IP ranges, or
- Use VNet integration with a private endpoint.

See §3.1 for the recommended SWA linked-backend topology.

### 8.2 CSRF protection relies on SWA cookie attributes

The UI does not send explicit CSRF tokens. Protection depends on the SWA Easy Auth session cookie's `SameSite=Lax` attribute and on `Origin`/`Referer` enforcement at the SWA edge. If you replace the auth layer or front the API with a different proxy, reintroduce equivalent CSRF protection.

### 8.3 Self-hosted CI runner — applies if you fork the repo

If you fork HASTE and reuse the included `azure-pipelines.yml` with a self-hosted runner on a public fork, fork-pull-request builds can execute arbitrary code on your runner. Either disable Azure Pipelines and rely on GitHub Actions, or restrict pipeline triggers to internal branches before exposing the fork.

### 8.4 Path traversal hardening in chunked uploads

The chunked file-upload endpoint accepts a `file_id` parameter and does not yet enforce a strict character allow-list against path-traversal sequences. The endpoint requires authentication and the parameter is constrained by the UI, but operators should not expose the chunked-upload route to untrusted authenticated clients. A character-class allow-list and `realpath` prefix check are recommended additions if you extend the API.

### 8.5 SSRF — outbound imagery download has no host allow-list

The imagery-download workflow fetches user-supplied URLs without an enforced host allow-list. **Customers running HASTE in their own subscription should add network egress controls** (NSG, Azure Firewall, or Function App outbound restrictions) limiting outbound traffic to the imagery providers you actually use (e.g., Planet Labs, NASA, Maxar).

### 8.6 Open redirect on logout

The UI's logout flow accepts a `redirectPath` query parameter that is not strictly validated against an allow-list. A maliciously crafted logout link could redirect users to an attacker-controlled domain after sign-out. Until validation is tightened to relative paths only, train users to verify the URL of any "you have been signed out" landing page.

### 8.7 Backward-compatibility notes for upgrades

- **User-management endpoint scope (post-v1.4.1)**: The `PutUser` endpoint was originally gated entirely on the `administrators` role. A subsequent release narrowed the gate to allow self-service updates **only** when the caller's email matches the target's email, and rejects role-change attempts from non-admins. Customers upgrading from v1.4.0 or earlier should re-test any external integrations that call `PutUser` on behalf of non-admin users.
- **`VITE_AZURE_MAPS_KEY` removed (post-v1.4.1)**: The UI no longer reads `VITE_AZURE_MAPS_KEY`. Set `VITE_AZURE_MAPS_CLIENT_ID` to your Function App's managed-identity client ID. **If you ever set `VITE_AZURE_MAPS_KEY`, rotate the corresponding Azure Maps subscription key**, because it was previously baked into the client bundle and may have been distributed.
- **`azurite` removed from `package.json`**: Developers must now install Azurite globally (`npm install -g azurite`). No production impact.

Each HASTE release documents security-relevant changes in [`CHANGELOG.md`](https://github.com/microsoft/haste/blob/main/CHANGELOG.md). The rolling list of acknowledged dependency vulnerabilities — fixed, dismissed with rationale, or pending — is maintained at [`docs/known-vulnerabilities.md`](https://github.com/microsoft/haste/blob/main/docs/known-vulnerabilities.md).

---

## 9. Secure configuration checklist (pre-production)

Before exposing HASTE to anyone other than its developers, verify:

- [ ] Function App is reachable only via SWA linked backend (or equivalent access restriction)
- [ ] AAD (Entra ID) is configured as the SWA identity provider; mock auth is disabled
- [ ] `DEVELOPMENT_MODE` is not set in any Application Setting
- [ ] All secrets are in Key Vault or supplied via managed identity (no inline connection strings in source control)
- [ ] `VITE_AZURE_MAPS_KEY` is **not** set; `VITE_AZURE_MAPS_CLIENT_ID` is set instead
- [ ] CORS is restricted to your UI's exact origin (no `*`)
- [ ] `staticwebapp.config.json` defines CSP, HSTS, X-Content-Type-Options, X-Frame-Options
- [ ] Basic-auth publishing is disabled on the Function App post-deployment
- [ ] Docker images are pinned to digests; ACR scanning is enabled
- [ ] Application Insights is enabled with ≥90-day retention
- [ ] Alerts are configured for 5xx rate, auth failures, and admin-action spikes
- [ ] Outbound network egress from the Function App is restricted (NSG or Azure Firewall) — see §8.5
- [ ] All administrators have been reviewed and assigned via least-privilege
- [ ] The known-limitations section (§8) has been read and the listed operational mitigations applied

---

## 10. References

- **Microsoft Cloud Security Benchmark** — https://learn.microsoft.com/security/benchmark/azure/
- **Azure Static Web Apps — Authentication and Authorization** — https://learn.microsoft.com/azure/static-web-apps/authentication-authorization
- **Azure Functions — Securing Functions** — https://learn.microsoft.com/azure/azure-functions/security-concepts
- **Azure Key Vault references in App Service** — https://learn.microsoft.com/azure/app-service/app-service-key-vault-references
- **Azure RBAC for storage** — https://learn.microsoft.com/azure/storage/blobs/assign-azure-role-data-access
- **Microsoft Defender for Cloud — Containers** — https://learn.microsoft.com/azure/defender-for-cloud/defender-for-containers-introduction
- **MSRC vulnerability reporting** — https://msrc.microsoft.com and https://aka.ms/SECURITY.md
- **HASTE Security Policy** — https://github.com/microsoft/haste/blob/main/SECURITY.md
- **HASTE CHANGELOG** — https://github.com/microsoft/haste/blob/main/CHANGELOG.md
- **HASTE Known Vulnerabilities (rolling)** — https://github.com/microsoft/haste/blob/main/docs/known-vulnerabilities.md

---

## Tech-review checklist (delete before publication)

- [ ] **Tech review on content** — content team confirms accuracy of every Azure CLI snippet, header recommendation, and remediation reference
- [ ] **Tech review on UI surfaces that point to this doc** — confirm the in-product Help link (e.g., Admin → Security or footer) resolves to the published URL once live
- [ ] **High-priority security issues resolved or disclosed** — verify each item in §8 is either fixed or accurately described as a current limitation with an operational mitigation
- [ ] **Backward-compatibility items documented** — §8.7 covers the current set; extend at each release where customer-visible auth/secrets/network behavior changes
- [ ] **Final security review before release** — schedule with the security team
- [ ] **Development team final approval** — sign-off recorded in this doc's commit history
- [ ] **Internet-accessible publication** — confirm the doc renders at `https://microsoft.github.io/haste/security-configuration.html` and is indexed by search
- [ ] **In-product link** — confirm the HASTE UI's footer or Help menu links to the published URL

---

*Draft prepared 2026-05-13. Send tech-review feedback to the HASTE engineering channel.*
