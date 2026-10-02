# Feature: Function App Network Baseline

**Status:** in-review
**Author:** HASTE engineering team
**Date:** 2026-10-02
**Target Release:** next
**Priority:** P0
**Work Item:** —

## Summary

The TiTiler tile server must be reachable only through HASTE's authenticated
entry point: the browser calls the Static Web App, whose linked backend calls
APIM, which calls TiTiler. This feature makes that guarantee hold at the network
layer. TiTiler's main site accepts traffic only from the APIM VNet integration
subnet, its SCM/Kudu site denies all traffic, and both deployment paths keep the
baseline in place across every redeployment.

## Motivation

- TiTiler reads whatever source a request names, and its function is anonymous
  by design. The SWA role check and the APIM subscription and JWT checks protect
  it only if nothing can reach the app around them.
- A network-level control keeps that guarantee independent of the tiler's
  application code and route surface.
- The dev and production environments are redeployed by `deploy_apps.sh`, not
  re-provisioned from Bicep. A control that lived only in Bicep would not
  protect them.

## Success Criteria

- [x] Direct requests to the TiTiler `*.azurewebsites.net` and
      `*.scm.azurewebsites.net` hostnames are refused (`403`).
- [ ] Tiles still load through SWA → APIM.
- [ ] A fresh `azd up` provisions the baseline and can still publish TiTiler.
- [ ] `deploy-apps.yml` re-applies and verifies the baseline before every
      TiTiler deploy, and still publishes through the locked SCM site.
- [ ] No deployment leaves a temporary allow rule behind, including failed ones.
- [x] API and queues apps are unchanged.

## HASTE Components Affected

| Component | Impact |
|---|---|
| `infra/modules/functionApp.bicep` | New `allowedInboundSubnetIds`, `restrictMainSite`, `restrictScmSite` params; TLS 1.2 on both sites |
| `infra/modules/functions.bicep`, `infra/main.bicep` | TiTiler limited to the APIM subnet; API/queues unchanged |
| `.github/scripts/deploy_apps.sh` | Enforces and verifies the baseline; temporary runner rule while publishing |
| `.github/scripts/function_network_baseline.py` | Shared rule evaluation for both deploy paths |
| `azure.yaml`, `deploy/*-deploy-access.ps1` | azd predeploy/postdeploy hooks for TiTiler |
| `docs/` | Security guide §5.5, deployment guide |

## Related Specs

| Spec | Relationship |
|---|---|
| [infra-iac-migration](../infra-iac-migration/) | related: the Bicep/azd path this extends |
| [gdal-compensating-controls](../gdal-compensating-controls/) | related: limits who can make the tiler's GDAL read a source |

## Document Index

| Document | Purpose | Status |
|---|---|---|
| [design.md](design.md) | Technical design | in-review |

## Decision Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-10-02 | Allow the APIM subnet through a service-endpoint rule rather than move TiTiler behind a private endpoint | Works with the existing VNet layout and APIM StandardV2 integration, and needs no DNS changes. A private endpoint stays a later option. |
| 2026-10-02 | Fail the deploy on unexpected allow rules instead of deleting them | Deleting could remove an access path someone relies on without telling them. Failing makes a person decide. |
| 2026-10-02 | Publish through a temporary `/32` rule for the deploying machine | Keeps SCM closed outside deployments without a self-hosted runner. |
| 2026-10-02 | Keep API and queues ingress unchanged in this change | Limits the change to the tile server. The same baseline can follow for the other apps. |
