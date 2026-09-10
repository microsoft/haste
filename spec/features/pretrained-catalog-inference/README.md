# Feature: Pretrained Catalog Inference

**Status:** implemented

## Summary

Run compatible catalog models on prepared standard-workflow image layers without
creating training labels or fine-tuning. Each invocation creates a separate
inference-only Model record and standard inference artifacts.

The first adapters are HASTE's existing trained checkpoints and DINOv3 UPerNet
adapted from microsoft/building-damage-assessment#18 at
`4d0d1925dc3a5a63566f047102f8dd474dbbcf80`. Only the two inference/model source
files are adapted; its training infrastructure is excluded.

## Boundaries

Use main as the base, the existing inference queue and UnifiedRunner, and the
existing aggregation/visualization pipeline. Do not import #183/#200/#201.
Preserve training and embedding behavior, catalog entries and existing results.
Pushes, releases and cloud deployments require explicit user permission.
The local stack runs this main-based branch. Azure Batch execution remains a
separate environment acceptance step; no cloud deployment was performed.

## Documents

[Design](design.md), [stories](user-stories.md), [plan](plan.md),
[data model](data-model.md), [tests](test-plan.md),
[impact](impact-analysis.md), [rollout](rollout.md).
