# Plan: Pretrained Catalog Inference

| Task | Agent | Stories | Status |
|---|---|---|---|
| Confirm main baseline and contracts | `backend-dev` | PCI-1 to PCI-7 | complete |
| Repair catalog and resolve inference recipes | `backend-dev`, `ui` | PCI-1, PCI-2, PCI-5 | implemented; real dev HTTP and legacy recipe exercised |
| Validate checkpoint/configuration and implement DINOv3 runtime | `gis`, `security` | PCI-4, PCI-7 | complete locally; Torch 2.10 and actual checkpoint accepted |
| Implement new-run submission and queue lifecycle | `backend-dev` | PCI-3, PCI-5 | complete; real replay and running cancellation exercised |
| Add layer inference UI and model-row presentation | `ui` | PCI-2, PCI-3, PCI-6 | complete; narrow first-load and narrative fixes included |
| Verify common postprocessing and artifacts | `gis`, `backend-dev` | PCI-4 to PCI-6 | complete; legacy 9545 and DINOv3 1072 processed |
| Add idempotent asset/catalog registration | `backend-dev`, `gis` | PCI-7 | complete; repeated import preserved both catalog entries |
| Validate local GPU, API/UI and Batch behavior | `backend-validation`, `ui-validation` | PCI-1 to PCI-7 | local acceptance complete; live Azure Batch acceptance pending environment access |
| Rename transformer inference image and deployment settings | `backend-dev` | PCI-4 | complete; local image/settings updated, DINOv3 model identity and existing run snapshots preserved |

The branch starts at main `72436853e36da50ea0871d56b6e02ad85872cc3f`.
The user authorized pushing this branch and opening a PR after the image rename.
Cloud deployment remains a separate action requiring authorization.
