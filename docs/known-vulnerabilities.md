# Known Vulnerabilities

This document tracks Dependabot alerts that are deferred because they cannot be patched without breaking a dependency, and explains the constraints.

Update this file when upstream packages ship fixes or when the deployment model changes.

---

## ~~Root Cause A — azurite → @azure/ms-rest-js (deprecated)~~ — RESOLVED

**Previously affected:** Dependabot alerts #3, #4, #6, #7, #9, #10, #11 (`package-lock.json`)

**Resolution:** `azurite` was removed from `package.json` and is now installed globally by developers (`npm install -g azurite`). It no longer appears in the project's dependency tree, so these alerts no longer surface in `npm audit` or Dependabot scans. See [development.md](development.md#local-storage-emulator-azurite) for usage guidance.

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

- **Alerts #3, #4, #6, #7, #9, #10, #11:** Resolved — `azurite` removed from `package.json` (global install). These alerts should auto-close on next Dependabot rescan; dismiss as fixed if they persist.
- **Alerts #14, #15, #16:** `inBundle: true` inside `npm@11.13.0` tarball; non-bundled installs already at patched versions. No production exposure.
