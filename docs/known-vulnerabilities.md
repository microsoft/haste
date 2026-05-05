# Known Vulnerabilities

This document tracks Dependabot alerts that are deferred because they cannot be patched without breaking a dependency, and explains the constraints.

Update this file when upstream packages ship fixes or when the deployment model changes.

---

## Root Cause A — azurite → @azure/ms-rest-js (deprecated)

**Affects:** Dependabot alerts #3, #4, #6, #7, #9, #10, #11 (`package-lock.json`)

`azurite` depends on `@azure/ms-rest-js@1.x`, an Azure SDK v2 package that is deprecated and receives no new releases. It in turn pulls in `axios@0.x` and `uuid@3.x`, both of which carry open CVEs.

These cannot be fixed with npm `overrides`:
- `@azure/ms-rest-js` calls `require('uuid/v4')` — a subpath removed in uuid v7+. Forcing uuid ≥7 breaks azurite at runtime.
- `@azure/ms-rest-js` uses `axios.CancelToken` — removed in axios 1.x. Forcing axios ≥1.x breaks azurite at runtime.

**Why the risk is tolerable:** azurite is a localhost-only dev storage emulator, not deployed to any environment. It is not internet-facing, does not handle production credentials, and is not called by application code paths that accept untrusted input. See [development.md](development.md#local-storage-emulator-azurite) for usage constraints.

**Resolution:** Upgrade azurite once it ships a version that removes or replaces its `@azure/ms-rest-js` dependency.

| Alert # | Package | CVE | Advisory | Severity |
|---------|---------|-----|----------|----------|
| #3 | axios | CVE-2023-45857 | GHSA-wf5p-g6vw-rhxx | Moderate |
| #4 | @azure/identity | CVE-2024-35255 | GHSA-m5vv-6r4h-3vj9 | Moderate |
| #6 | axios | CVE-2025-27152 | GHSA-jr5f-v2jv-69x6 | Moderate |
| #7 | axios | CVE-2026-25639 | GHSA-43fc-jf86-j433 | High |
| #9 | axios | CVE-2026-40175 | GHSA-fvcv-3m26-pcqx | Critical (CVSS 9.9) |
| #10 | axios | CVE-2025-62718 | GHSA-3p68-rc4w-qgx5 | Critical (CVSS 9.3) |
| #11 | uuid | — | GHSA-w5hq-g745-h8pq | Moderate |

---

## Root Cause B — npm bundled dependencies

**Affects:** Dependabot alerts #14, #15, #16 (`ui/package-lock.json`)

`npm` bundles its own copies of `picomatch` and `brace-expansion` inside its tarball (`inBundle: true`). These bundled copies cannot be reached by npm `overrides`. The unpatched versions were inside `npm@11.12.1`; upgrading to `npm@11.13.0` (already done) ships `picomatch@4.0.4` and `brace-expansion@5.0.5` inside the bundle.

If Dependabot still flags these after the next rescan of `main`, the alerts should auto-close. If they persist, they can be dismissed — the patched versions are already installed as top-level `node_modules` entries and no production code path runs the bundled copies.

| Alert # | Package | CVE | Advisory | Severity |
|---------|---------|-----|----------|----------|
| #14 | picomatch | CVE-2026-33671 | GHSA-c2c7-rcm5-vvqj | High |
| #15 | picomatch | CVE-2026-33672 | GHSA-3v7f-55p6-f55p | Moderate |
| #16 | brace-expansion | CVE-2026-33750 | GHSA-f886-m6hf-6m8v | High |

---

## Dismissal rationale (for GitHub Dependabot)

When dismissing these alerts on GitHub, use **"Risk tolerable for this project"** with notes along these lines:

- **Alerts #3, #6, #7, #9, #10, #11:** `azurite` dev-only emulator; patching axios/uuid breaks `@azure/ms-rest-js` at runtime. No production exposure. Blocked on azurite upstream removing `@azure/ms-rest-js`.
- **Alert #4:** `azurite → tedious` pins `@azure/identity` to 3.x. Dev-only emulator; EoP vulnerability not exercised in local emulation context. Blocked on same azurite upgrade.
- **Alerts #14, #15, #16:** `inBundle: true` inside `npm@11.13.0` tarball; non-bundled installs already at patched versions. No production exposure.
