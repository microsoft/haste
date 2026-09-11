# Plan: stacked pull-request validation

## Tasks

| Task | Agent | Status |
|---|---|---|
| Remove only pull-request target-branch restrictions | backend-dev | complete |
| Add regression coverage and retain publisher safeguards | backend-dev | complete |
| Run release-policy unit tests | backend-validation | complete; 82 tests passed |

## Boundaries

This prerequisite does not repair a remote image build, register AML
assets, deploy HASTE, or modify shared compute. Those remain separate gates.
