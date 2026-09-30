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
| Rebase onto merged results/editor and loading contracts | `backend-dev`, `ui` | PCI-3, PCI-6 | complete locally; modern attributes/revisions, authorization, task recovery and shared viewer/report contracts retained |
| Add six pinned DINOv2 follow-up choices | `gis`, `backend-dev`, `ui` | PCI-8 | complete locally; six strict-load/reference checks and repeated real-asset import passed; only the selected seed below is registered in the live local catalog |
| Repair clean-CI release-policy test imports | `backend-dev` | PCI-4, PCI-8 | fixed; all 118 release-policy tests pass in a fresh environment containing only `build==1.3.0` and its dependencies, with PyYAML absent |
| Deploy locally and register selected DINOv2 model | `backend-dev`, `gis` | PCI-4, PCI-7, PCI-8 | complete September 29; source `263b9fa`, six matching images, source-balanced seed 0 registered and ready on four prepared standard layers; existing project data and catalog entries preserved |

The branch starts at main `72436853e36da50ea0871d56b6e02ad85872cc3f`.
The September 29 rebase targets main `d16f93ed0008d56cf9f3c54687273d02e6c54670`.
The user authorized committing and pushing the rebase and DINOv2 additions.
Cloud deployment remains a separate action requiring authorization.

The trusted `workflow_run` publisher executes from main. Until its transformer
matrix change lands there, automatic RC publishing builds only training and
imageryprep images. A branch deployment additionally needs a separately built
transformer image at the matching RC tag; a green standalone Docker gate is not
evidence that those image builds ran.

The local rollout replaced only API, queue worker and UI containers and
restarted the proxy; storage, `data-init` and TiTiler were not restarted.
Derived statistics were regenerated after API startup. The selected checkpoint
ran offline on CUDA in the built image; no live project inference was submitted.
Hosted dev was neither inspected nor modified and requires its own catalog
recipe registration.
