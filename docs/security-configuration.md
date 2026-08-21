# HASTE — Secure Configuration Guidance

| Field | Value |
|-------|-------|
| **Repository** | microsoft/haste |
| **Audience** | Customers / consumers / operators deploying HASTE |
| **Last updated** | 2026-05-14 |

---

## 1. Overview

HASTE (High-speed Assessment and Satellite Tracking for Emergencies) is an AI-driven framework for rapid disaster assessment using satellite imagery. The repository is published as a **library + reference deployment**: Microsoft operates the public reference deployment, while external consumers integrate the `hastegeo` Python library and may optionally redeploy the full stack (UI + Function Apps + Azure Batch) into their own subscription.

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
| **Library-only integration** | Consuming the `hastegeo` Python package in your own application | You inherit only the library's process-level threat model; deployment-time controls are yours. |

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

The CI deploy script (`.github/scripts/deploy_apps.sh`) writes the Function App master key to `.env` during deployment. **Treat this file as sensitive and remove it from any machine that is not your local workstation.** (The `azd` workflow instead injects the Function host key into the APIM backends via the postdeploy hook and does not persist it to disk.) Rotate this key periodically in production via:

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

HASTE ships a `staticwebapp.config.json` (under `ui/public/`) with the following headers. This is the policy the reference UI runs under — verified against the live Azure Maps and labeling pages with a clean console:

```json
{
  "globalHeaders": {
    "Content-Security-Policy": "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; script-src 'self' https://atlas.microsoft.com; style-src 'self' 'unsafe-inline' https://atlas.microsoft.com; font-src 'self' data: https://atlas.microsoft.com https://c.s-microsoft.com https://*.cdn.office.net; img-src 'self' data: blob: https://atlas.microsoft.com https://*.atlas.microsoft.com https://*.tile.openstreetmap.org https://vantor-opendata.s3.amazonaws.com https://data.source.coop; connect-src 'self' https://atlas.microsoft.com https://*.atlas.microsoft.com https://*.tile.openstreetmap.org https://vantor-opendata.s3.amazonaws.com https://data.source.coop; worker-src 'self' blob:; child-src blob:",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin"
  }
}
```

Notes on why each non-`'self'` source is present — tighten if your build removes the dependency:

- **`atlas.microsoft.com` / `*.atlas.microsoft.com`** (script, style, font, img, connect) — the Azure Maps Web SDK is loaded from the CDN in `index.html` and fetches map styles, vector tiles, and glyph fonts at runtime. `'unsafe-inline'` in `style-src` is required by Fluent UI's runtime style injection.
- **`c.s-microsoft.com` and `*.cdn.office.net`** (font) — Fluent UI loads Segoe UI and its icon/language fonts from these Microsoft CDNs at runtime. To drop them, self-host the Fluent fonts and register them locally.
- **`blob:`** (img, worker, child) — the Azure Maps control renders tiles and spawns web workers from blob URLs.
- **`*.tile.openstreetmap.org`** (img, connect) — only needed if you configure an OSM basemap; remove otherwise.
- **`vantor-opendata.s3.amazonaws.com` and `data.source.coop`** (img, connect) — the Open Data Catalog explorer fetches the Vantor and Planet STAC catalogs (and scene thumbnails) directly from the browser. Remove if the Open Data Catalog is not enabled, or move discovery behind a same-origin backend proxy so only `'self'` is needed.

**Per-deployment adjustment:** if your `VITE_API_URL` points at a separate origin (a direct `*.azurewebsites.net` Function App rather than the same-origin SWA `/api` linked-backend route), add that origin to `connect-src`. The default policy assumes the recommended same-origin linked-backend topology (§3.1).

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

### 8.3 CI runners — applies if you fork the repo

CI runs on GitHub Actions with GitHub-hosted runners (CodeQL and Gitleaks secret scanning); the legacy `azure-pipelines.yml`, which used a self-hosted pool, has been removed. If you fork HASTE and add self-hosted runners, note that fork pull-request builds can execute arbitrary code on a self-hosted runner. Keep untrusted-fork PRs on GitHub-hosted runners, or restrict workflow triggers to internal branches before exposing the fork.

### 8.4 Path traversal hardening in chunked uploads

The chunked file-upload endpoint accepts a `file_id` parameter and does not yet enforce a strict character allow-list against path-traversal sequences. The endpoint requires authentication and the parameter is constrained by the UI, but operators should not expose the chunked-upload route to untrusted authenticated clients. A character-class allow-list and `realpath` prefix check are recommended additions if you extend the API.

### 8.5 Imagery URL allowlist and outbound egress controls

HASTE enforces an application-layer allowlist on user-supplied imagery URLs. The `PutLayer` API rejects (HTTP 400) any submission whose `preEventImageryUrls` or `postEventImageryUrls` contains a host outside `*.blob.core.windows.net` (Azure Blob Storage) or `*.amazonaws.com` (AWS S3, including `s3.amazonaws.com` and regional subdomains). The UI mirrors this check client-side so users get inline feedback when adding a URL rather than after submitting a layer. The imagery downloader (`ImageryDownloader._validate_url`) applies the same allowlist as defense-in-depth at fetch time.

This closes the application-layer SSRF risk that previously existed in the imagery-download path: the Function App and Batch workers cannot be coerced into fetching arbitrary user-controlled URLs (which could otherwise reach the Instance Metadata Service at `169.254.169.254`, internal VNet addresses, `localhost`-bound services on the host, or attacker-controlled HTTP endpoints from the server's network position).

**Defense-in-depth recommendation**: even with the application-layer allowlist, restrict outbound egress from the Function App and Batch node pool (NSG, Azure Firewall, or Function App outbound IP restrictions) to the specific imagery providers you actually use. This protects against:

- Future code paths that bypass the allowlist
- Compromise of an allowlisted hostname (e.g., a hostile Azure Blob container in another tenant)
- DNS rebinding — the application-layer check validates the hostname *string*, but the actual TCP connection performs a separate DNS resolution at fetch time. Pinning egress at the network layer to known imagery-provider IP ranges removes that window.

If your imagery sources are a small static set (customer-owned storage accounts, specific public S3 buckets), use that exact set for the egress allowlist as well rather than the broad `*.blob.core.windows.net` / `*.amazonaws.com` patterns.

### 8.6 Open redirect on logout

The UI's logout flow validates the `redirectPath` parameter via `sanitizeRedirectPath()` (`ui/src/util/validation.js`) before building the `post_logout_redirect_uri`: the value is collapsed to a same-origin relative path, so absolute URLs, protocol-relative (`//host`), backslash-normalized (`/\host`), and any scheme-bearing input fall back to `/`. This closes the previously-documented open-redirect; no operator action is required.

### 8.7 Backward-compatibility notes for upgrades

- **User-management endpoint scope (post-v1.4.1)**: The `PutUser` endpoint was originally gated entirely on the `administrators` role. A subsequent release narrowed the gate to allow self-service updates **only** when the caller's email matches the target's email, and rejects role-change attempts from non-admins. Customers upgrading from v1.4.0 or earlier should re-test any external integrations that call `PutUser` on behalf of non-admin users.
- **`VITE_AZURE_MAPS_KEY` removed (post-v1.4.1)**: The UI no longer reads `VITE_AZURE_MAPS_KEY`. Set `VITE_AZURE_MAPS_CLIENT_ID` to your Function App's managed-identity client ID. **If you ever set `VITE_AZURE_MAPS_KEY`, rotate the corresponding Azure Maps subscription key**, because it was previously baked into the client bundle and may have been distributed.
- **`azurite` removed from `package.json`**: Developers must now install Azurite globally (`npm install -g azurite`). No production impact.
- **Imagery URL allowlist enforced (post-v1.4.1)**: `PutLayer` now rejects requests whose `preEventImageryUrls` or `postEventImageryUrls` contain a host outside `*.blob.core.windows.net` or `*.amazonaws.com`. The pre-existing batch-download code silently skipped such URLs, so this change makes the rejection visible at submission time rather than producing failed jobs with empty outputs. Customers with API integrations that submit imagery from other sources must move that imagery into an allowlisted source before upgrading, or the affected layer-creation calls will fail.

### 8.8 GDAL driver allowlist and ingestion size/type limits

GDAL `3.9.2` is pinned (no trusted prebuilt pip wheel exists for the patched 3.13 line under HASTE's runtime), so three memory-safety CVEs — most notably **CVE-2026-8087**, a heap overflow in the HDF4/HDF-EOS driver — are deferred under a documented exception with **compensating controls enforced in code** (see [`known-vulnerabilities.md`](https://github.com/microsoft/haste/blob/main/docs/known-vulnerabilities.md) Root Cause C and [ADR-0004](https://github.com/microsoft/haste/blob/main/spec/architecture/decisions/0004-gdal-driver-allowlist.md)).

- **Driver allowlist.** At process startup `hastegeo.core.utils.gdal_security.harden_gdal()` restricts GDAL/OGR to the drivers HASTE actually uses (raster `GTiff, COG, VRT, JPEG, PNG, MEM`; vector `GPKG, GeoJSON, Memory`) by deregistering every other driver. Because GDAL dispatches by sniffing file *content* (not the extension), this removes the vulnerable HDF4/HDF-EOS code path from every `gdal.Open`/`rasterio.open`/`pyogrio` read in-process. The imageryprep and training containers also set `GDAL_SKIP="HDF4 HDF4Image HDF5 HDF5Image netCDF"` so subprocess GDAL CLI tools (`gdalwarp`/`gdal_translate`) refuse those drivers too.
- **Ingestion size/type limits.** Chunked uploads are capped (`HASTE_MAX_UPLOAD_BYTES`, default 5 GiB) and the assembled file's magic bytes must match its declared format before GDAL parses it. Remote imagery fetches are capped (`HASTE_MAX_IMAGERY_DOWNLOAD_BYTES`, default 8 GiB) and refuse cross-host redirects (SSRF guard). Defaults are generous because satellite COGs are legitimately large; tune them to your largest expected imagery.

**Operator action:** keep `GDAL_SKIP` set in any custom GDAL-bearing image, and do not add file formats to the pipeline without extending the allowlist in `gdal_security.py`. If you legitimately need a format outside the allowlist, add its driver explicitly rather than disabling the control.

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
