# Plan: stacked pull-request validation

## Tasks

| Task | Agent | Status |
|---|---|---|
| Remove only pull-request target-branch restrictions | backend-dev | complete |
| Add regression coverage and retain publisher safeguards | backend-dev | complete |
| Run release-policy unit tests | backend-validation | complete; 82 tests passed |
| Reuse published imagery-base and ACR compatibility fixes | backend-dev | complete |
| Freeze candidate identity and verify idempotent publication | backend-dev | complete |
| Require matched image/wheel evidence for RC deployment | backend-dev | complete |
| Exercise parallel, retry, checksum and provenance regressions | backend-validation | complete; 112 release/build cases passed |
| Negotiate with the active publisher and preserve legacy producers | backend-dev | complete |
| Exercise old/new producer and publisher combinations | backend-validation | complete; 129 release/build cases passed |
| Verify fresh wheel publication and both actual image builds | backend-validation | pending; do not substitute green skipped jobs |

## Boundaries

The published imagery-base/ACR fixes are included without unrelated
prediction-editing code. Native image smoke coverage passed in the existing
pinned-base runtime, and two real wheel builds produced identical bytes with
a fixed source timestamp. Frozen resolution also matched real, read-only
GitHub run/release metadata.

No Azure deployment, shared-compute change, live release overwrite, or
default-branch merge was performed. Activating the trusted publisher and
proving a fresh verified ACR artifact set remain approval-gated work.
Compatibility builds must still publish ordinary wheels and images using
the currently active legacy contract; a PR-only protocol update must not
break that path.
