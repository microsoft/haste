# Plan: GDAL 3.13 Native Runtime

| Phase | Task | Agent | Status |
|---|---|---|---|
| 0 | Spec, ADR-0007, baseline runtime report from every current runtime | `backend-dev` | in-progress |
| 1 | Source lock, build scripts, shared runtime packaging | `backend-dev` + `gis` | in-progress |
| 1 | Build workflow: manifest, SBOM, notices, scan gate, attestation, smoke tests | `backend-dev` | in-progress |
| 1 | Approval-gated publish to `haste-binaries`; license review | `backend-dev`, `security` | pending |
| 2 | hastegeo self-check policy; `harden_gdal()` rework | `backend-dev` | pending |
| 2 | Untrusted-input content check and driver allowlist at open; configuration audit | `gis` | pending |
| 2 | GDAL hardening settings in Bicep, `deploy_apps.sh`, Dockerfiles and compose | `backend-dev` | pending |
| 3 | TiTiler: hash-locked dependencies on the runtime; startup self-check; VRT driver policy; negative tests | `backend-dev` | pending |
| 4 | Build-once Function App packages; `--no-build` deploy; post-deploy verification | `backend-dev` | pending |
| 5 | imageryprep and training images (training to Python 3.11); local dev and CI test environments | `backend-dev` + `gis` | pending |
| 6 | Dependency pin guards, forbidden-configuration guard, docs, close the GDAL exception | `backend-dev` | pending |
| 7 | Dev rollout, runtime evidence, production after approval | `backend-dev` | pending |

Validation for every phase: `backend-validation`. New native dependencies:
`security` audits them and `security-validation` confirms.
