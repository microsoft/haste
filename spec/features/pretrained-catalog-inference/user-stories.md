# Stories: Pretrained Catalog Inference

| Story | Acceptance criteria |
|---|---|
| PCI-1 | Catalog read/manage operations work in local development; genuine empty, failed and incompatible states are distinguishable. |
| PCI-2 | Standard layer row/card exposes Inference without requiring training labels. Users select a compatible DINOv3 or HASTE catalog model in a centered modal. The catalog loads automatically; Retry appears only on failure, with no standalone reload control. |
| PCI-3 | Each invocation creates a new inference-only run; retries do not duplicate work, prior models/results remain intact, and cancellation works. |
| PCI-4 | DINOv3 executes from staged assets with correct normalization, tiling, class mapping, NoData and georeferencing, on local GPU and Batch. |
| PCI-5 | Legacy HASTE models preserve checkpoint/configuration semantics without executing fine-tuning. |
| PCI-6 | Existing standard results, downloads and reports consume the generated artifacts correctly. |
| PCI-7 | Initial registration is idempotent, retains provenance/hashes/notices, and does not reset catalog or project data. |

## Agent Assignment Map

| Stories | Implementing agents | Validating agents |
|---|---|---|
| PCI-1, PCI-2 | `backend-dev`, `ui` | `backend-validation`, `ui-validation` |
| PCI-3, PCI-5 | `backend-dev` | `backend-validation` |
| PCI-4, PCI-6 | `gis`, `backend-dev`, `ui` | `backend-validation`, `ui-validation` |
| PCI-7 | `gis`, `backend-dev`, `security` | `backend-validation`, `security-validation` |
