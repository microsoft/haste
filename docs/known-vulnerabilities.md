# Known Vulnerabilities

This document tracks Dependabot alerts that are deferred because they cannot be patched without breaking a dependency, and explains the constraints.

Update this file when upstream packages ship fixes or when the deployment model changes.

---

## ~~Root Cause A — azurite → @azure/ms-rest-js (deprecated)~~ — RESOLVED

**Previously affected:** Dependabot alerts #3, #4, #6, #7, #9, #10, #11, #20, #21, #22, #23, #24, #25, #26, #27, #28, #29 (`package-lock.json`)

**Resolution:** `azurite` was removed from `package.json` and `package-lock.json` regenerated. It no longer appears in the project's dependency tree, so these alerts no longer surface in `npm audit` or Dependabot scans. Azurite is now installed globally by developers (`npm install -g azurite`). See [development.md](development.md#local-storage-emulator-azurite) for usage guidance.

---

## Root Cause B — npm bundled dependencies

**Affects:** Dependabot alerts #14, #15, #16, #32 (`ui/package-lock.json`)

`npm` bundles copies of certain packages inside its tarball (`inBundle: true`). These cannot be reached by npm `overrides` — the only fix is upgrading `npm` itself to a version that ships the patched bundled copy.

- **Alerts #14, #15, #16** — `picomatch` and `brace-expansion` were unpatched inside `npm@11.12.1`; upgrading to `npm@11.13.0` (already done) ships the fixed versions inside the bundle. These alerts should auto-close on the next Dependabot rescan; dismiss as fixed if they persist.
- **Alert #32** — `ip-address@10.1.0` (CVE-2026-42338, GHSA-v2v4-37r5-5v8g, Medium) is bundled inside `npm@11.13.0` via `socks`. Patched version is `10.1.1`. Blocked on `npm` shipping a release that bundles `ip-address@10.1.1`. The XSS in `Address6` HTML-emitting methods is not reachable from any application code path — `npm` does not render IP addresses as HTML at runtime.

| Alert # | Package | CVE | Advisory | Severity | Status |
|---------|---------|-----|----------|----------|--------|
| #14 | picomatch | CVE-2026-33671 | GHSA-c2c7-rcm5-vvqj | High | Fixed in npm@11.13.0 |
| #15 | picomatch | CVE-2026-33672 | GHSA-3v7f-55p6-f55p | Moderate | Fixed in npm@11.13.0 |
| #16 | brace-expansion | CVE-2026-33750 | GHSA-f886-m6hf-6m8v | High | Fixed in npm@11.13.0 |
| #32 | ip-address | CVE-2026-42338 | GHSA-v2v4-37r5-5v8g | Medium | Blocked on npm upstream |

---

## Dismissal rationale (for GitHub Dependabot)

When dismissing these alerts on GitHub, use **"Risk tolerable for this project"** with notes along these lines:

- **Alerts #3, #4, #6, #7, #9, #10, #11, #20–29:** Resolved — `azurite` removed from `package.json` and `package-lock.json` regenerated. These alerts should auto-close on next Dependabot rescan; dismiss as fixed if they persist.
- **Alerts #14, #15, #16:** `inBundle: true` inside `npm@11.13.0` tarball; non-bundled installs already at patched versions. No production exposure.
- **Alert #32:** `ip-address` `inBundle: true` inside `npm@11.13.0` tarball. XSS in `Address6` HTML-emitting methods; not reachable from application code. Blocked on npm upstream shipping `ip-address@10.1.1` in its bundle.
