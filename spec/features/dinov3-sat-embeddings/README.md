# Feature: DINOv3-SAT building embeddings

**Status:** implemented
**Author:** Copilot
**Date:** 2026-08-19
**Priority:** P1

## Summary

Add the satellite-pretrained DINOv3 ViT-L/16 SAT-493M backbone as an
embedding option for Rapid Building Assessment. Administrators stage the
gated Hugging Face model snapshot in HASTE artifact storage, and embedding
jobs receive it as an Azure Batch resource without runtime internet access or
embedded credentials.

## Motivation

DINOv3-SAT provides remote-sensing-specific 1024-dimensional patch features
at a 16-pixel stride. Evaluation in `~/src/haste-developement` found it useful
for building-damage classification, but HASTE currently exposes only MOSAIKS
and DINOv2 backbones.

## Success criteria

- [x] Users can select **DINOv3-SAT ViT-L/16** when creating an embedding.
- [x] Batch jobs load SAT-493M weights from a staged local snapshot and never
      require Hugging Face credentials or internet access.
- [x] DINOv3 outputs preserve the existing one-row-per-footprint invariant.
- [x] Setup, provenance, storage, and configuration are documented.
- [x] Targeted Python tests, UI lint, and UI build pass.

## HASTE components affected

| Component | Impact |
|---|---|
| `hastelib/src/hastegeo/workflows/` | Add the DINOv3-SAT token adapter. |
| `hastelib/src/hastegeo/core/processors/` | Stage the managed model snapshot. |
| `hastelib/src/hastegeo/core/config.py` | Add model artifact configuration. |
| `ui/src/Components/` | Add selection and display labels. |
| `docker/training/` | Install the pinned model runtime dependency. |
| `docs/usage/` | Document administration and operation. |

## Document index

| Document | Purpose |
|---|---|
| [design.md](design.md) | Artifact and runtime design |
| [user-stories.md](user-stories.md) | Acceptance criteria and agent mapping |
| [plan.md](plan.md) | Execution status |
| [test-plan.md](test-plan.md) | Validation coverage |
