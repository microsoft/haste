# Feature: Pretrained Catalog Inference

**Status:** implemented

## Summary

Run compatible catalog models on prepared standard-workflow image layers without
creating training labels or fine-tuning. Each invocation creates a separate
inference-only Model record and standard inference artifacts.

The supported adapters are HASTE's existing trained checkpoints, DINOv3 UPerNet
from microsoft/building-damage-assessment#18 at
`4d0d1925dc3a5a63566f047102f8dd474dbbcf80`, and six DINOv2 follow-up checkpoints
from the same source PR at `958ff3d30601ffc3577da81af1ac0a545deb295e`.
Only inference/model code is adapted; upstream training infrastructure is excluded.

## Boundaries

Use main as the base, the existing inference queue and UnifiedRunner, and the
existing aggregation/visualization pipeline. The September 29 rebase integrates
with the shared results/editor and loading features now merged into main.
Preserve training and embedding behavior, catalog entries and existing results.
Pushes, releases and cloud deployments require explicit user permission.
This rebase does not redeploy the existing local stack. Azure Batch execution remains a
separate environment acceptance step; no cloud deployment was performed.

## Documents

[Design](design.md), [stories](user-stories.md), [plan](plan.md),
[data model](data-model.md), [tests](test-plan.md),
[impact](impact-analysis.md), [rollout](rollout.md).
