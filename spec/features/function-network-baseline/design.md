# Technical Design: Function App Network Baseline

## Overview

TiTiler's inbound access is limited to the subnet APIM egresses from. The rule
uses App Service access restrictions with the `Microsoft.Web` service endpoint
that `infra/modules/network.bicep` already enables on that subnet. Bicep declares
the baseline. `deploy_apps.sh` re-applies and verifies it before every TiTiler
deploy. Both deploy paths open a short-lived `/32` rule while they publish.

## Architecture

```
Browser ──▶ Static Web App (Easy Auth roles)
              │ linked backend: subscription key + SWA token
              ▼
            APIM  api/titiler  (HTTPS only, validate-jwt product policy)
              │ egress through its VNet integration subnet
              ▼
            TiTiler main site ── default Deny, allow: APIM subnet only
            TiTiler SCM site  ── default Deny, no rules, does not inherit main
```

No HASTE backend calls TiTiler. hastegeo only builds `/api/titiler/...` tile URLs
for the browser.

### New Components

| Component | Path | Responsibility | Technology |
|---|---|---|---|
| Baseline evaluator | `.github/scripts/function_network_baseline.py` | Reads `az functionapp config show` JSON. Reports deny-by-default sites, the subnet rule, `haste-ci-*` rules, and baseline violations. | Python |
| azd deploy access | `deploy/function-deploy-access.ps1` (+ open/close wrappers) | Temporary `/32` rule for the machine running `azd deploy` | PowerShell |

### Modified Components

| Component | Path | Change Description |
|---|---|---|
| Function app module | `infra/modules/functionApp.bicep` | Access-restriction params and `siteConfig` fields; TLS 1.2 on both sites |
| Function apps | `infra/modules/functions.bicep` | TiTiler: APIM subnet only, both sites restricted. API/queues: `false`, `false`. |
| Entry point | `infra/main.bicep` | One `apimSubnetName` shared by the APIM module and the TiTiler rule |
| CI deploy | `.github/scripts/deploy_apps.sh` | `ensure_network_baseline` for TiTiler; `open/close_deploy_access` around `func publish`; EXIT trap |
| azd | `azure.yaml` | TiTiler `predeploy`/`postdeploy` hooks |

## Behavior & Logic

### CI deploy of TiTiler (`deploy_apps.sh`)

1. Resolve the subnet from APIM (`virtualNetworkConfiguration.subnetResourceId`).
   If it is empty, stop before touching the app.
2. Remove any `haste-ci-*` rules left behind by an earlier run.
3. Add `AllowSubnet-1` for that subnet if the main site lacks it. Set both
   default actions to `Deny` and stop SCM from using the main-site rules.
4. Verify the result. Any other allow rule, HTTPS-only off, TLS below 1.2, or
   FTP enabled stops the deploy, and nothing is deleted.
5. Restart, then add `haste-ci-<run>-<attempt>` (`/32` of the runner, priority 90)
   to each site that denies by default.
6. `func azure functionapp publish`, then remove the rule. An EXIT trap removes
   it if the publish fails.

Sites that allow by default never receive the rule, because the first rule on
such a site would switch it to deny-by-default. As a result the API and queues
apps deploy exactly as before.

### Edge Cases

| Case | Expected Behavior |
|---|---|
| APIM has no VNet integration subnet | Deploy fails closed before any change |
| An operator added an allow rule by hand | Deploy fails and names the rule; the rule is kept |
| A run dies before cleanup | The next deploy removes its `haste-ci-*` rule |
| Default action unset, but the site has rules | Treated as deny-by-default, as App Service does |
| `azd deploy` fails between hooks | Run `deploy/function-deploy-access.ps1 -Action Close` |
| Azure sees a different egress address than ipify | Set `HASTE_DEPLOY_SOURCE_IP` (azd path) |

## Configuration

| Config Key | Type | Default | Where Set | Description |
|---|---|---|---|---|
| `allowedInboundSubnetIds` | array | `[]` | `functionApp.bicep` param | Subnets allowed on the main site |
| `restrictMainSite` | bool | `true` | `functionApp.bicep` param | Main site denies by default |
| `restrictScmSite` | bool | `true` | `functionApp.bicep` param | SCM site denies all traffic |
| `HASTE_DEPLOY_SOURCE_IP` | string | (looked up) | azd environment / shell | Address the azd hook allows while publishing |

## Observability

- `az functionapp config access-restriction show` lists the effective rules.
- Blocked requests get App Service's `403 Forbidden` page.
- Deploy logs name each rule they add or remove, without printing the address.

## Open Questions

- [ ] Apply the same baseline to the API and queues apps. `update_size_limits.sh`
      probes their hostnames directly and would need the temporary-rule pattern.
- [ ] Disable basic-auth publishing credentials once CI publishing is confirmed
      to work with Microsoft Entra ID only.
- [ ] Move TiTiler behind a private endpoint with public network access disabled.
