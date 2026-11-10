# Feature: Energy-aware training and inference

**Status:** in-review
**Author:** Simone Fobi Nsutezo
**Date:** 2026-11-09
**Target Release:** next training-image build
**Priority:** P2
**Work Item:** —

## Summary

Every Damage Mapping job in HASTE runs the polygon training workflow under
`docker/training/code/` on a GPU Batch node: mask creation, fine-tuning the
U-Net, inference over the post-event scene, merging with building footprints
and scoring. The GPU work in that job is the training step and the inference
batch. This change applies four PyTorch-level levers to those two code paths
so a job uses less GPU energy and finishes sooner, without changing the
training objective or what is written to disk:

- channels-last (NHWC) weights and inputs,
- cuDNN convolution autotuning,
- PyTorch's fused AdamW kernel,
- bf16 autocast for the inference forward pass, on GPUs with native bf16.

Each lever is gated on the device it runs on. On CPU nothing changes. On
Turing GPUs (T4) the three layout and kernel levers engage and bf16
inference is skipped. On Ampere and later all four engage.

The levers were found by a GPU green-loop kernel search over HASTE's
training step and inference batch and then ported by hand into the
workflow scripts (see [design.md](design.md)).

## Motivation

- **GPU energy and time per job.** Training and inference dominate the GPU
  time of a Damage Mapping job. Paired measurements of `main` against this
  branch on the LA-fires jobs put the unmodified code's GPU energy at 1.29x
  this branch's (about 22 to 23% less energy per job) and its wall time at
  1.19 to 1.20x (about 17% shorter).
- **Same results.** The training update is the same arithmetic as before;
  only the memory layout and the optimizer kernel change. bf16 is confined
  to the inference forward pass. Building-level accuracy, damaged-building
  F1 and pixel mIoU stayed within the run-to-run spread of HASTE's unseeded
  training on both jobs.
- **Heterogeneous pools.** HASTE's Batch pools mix GPU generations, so no
  lever may assume Ampere; the bf16 lever asks the device for native
  support, as `select_precision` already does for training.

## Success Criteria

- [x] CPU training and inference are unchanged: weights stay NCHW, the
      optimizer is the base torchgeo AdamW, inference stays fp32
      (`tests/test_gpu_efficiency.py`).
- [x] On CUDA the fused AdamW owns the same parameters in the same order,
      with the same learning rate and scheduler, as the base optimizer.
- [x] bf16 autocast is selected only when `torch.cuda` reports native bf16;
      a Turing device reporting emulated bf16 keeps fp32.
- [x] Paired measurements of `main` against this branch on the Palisades
      and Eaton jobs show less GPU energy and wall time per job with
      building-level quality within the run-to-run spread.
- [ ] A training-image build on the pinned Python 3.11 environment runs the
      suite and a Damage Mapping job in dev.
- [ ] A T4 node runs a job end to end (channels-last fp32 on Turing was not
      measured).
- [ ] A multi-GPU (DDP) training run completes.
- [ ] Building-level metrics on a converged checkpoint, not a one-epoch one.

## HASTE Components Affected

| Component | Impact |
|---|---|
| `docker/training/code/fine_tune.py` | cuDNN autotuning; channels-last weights when training on GPU |
| `docker/training/code/bda/trainers.py` | `channels_last_if_cuda`, `maybe_channels_last`, `fused_adamw_supported`; fused AdamW in `configure_optimizers`; NHWC inputs in the step functions |
| `docker/training/code/inference.py` | channels-last, pinned non-blocking copies, bf16 autocast on Ampere+ |
| `docker/training/code/tests/test_gpu_efficiency.py` | New: device-gating and parity tests |
| `CHANGELOG.md` | Entry under Unreleased / Changed |

No `hastelib/`, API or UI change; the configuration schema is untouched.
The change ships with the training image only.

## Related Specs

| Spec | Relationship |
|---|---|
| [`../training-workflow-sync/`](../training-workflow-sync/) | its design decided training precision at runtime per GPU generation; this spec reuses that decision for inference (see [design.md §6](../training-workflow-sync/design.md#6-deliberate-deviations-from-upstream)) |
| [`../batch-compute-expansion/`](../batch-compute-expansion/) | the heterogeneous GPU pools the device gating exists for |

## Document Index

| Document | Purpose | Status |
|---|---|---|
| [design.md](design.md) | Levers, device gating, measurements and provenance, constraints, what remains to verify, testing | in-review |

## Decision Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-11-09 | Port the levers by hand rather than ship the search's kernel | The kernel is a standalone training step and inference batch; HASTE's scripts carry constraint-loss, DDP and checkpoint handling the kernel does not |
| 2026-11-09 | Gate bf16 on native support and restrict it to inference | Emulated bf16 on a T4 trained about six times slower than fp32 (training-workflow-sync); bf16 in the training update would change the arithmetic this spec promises to keep |
| 2026-11-09 | Gate channels-last weights on CUDA, not apply them unconditionally | On CPU the conversion changes weight strides and the convolution numerics (about 6e-6) for no gain |
| 2026-11-09 | Accept fused AdamW's two constraints (no Lightning gradient clipping under mixed precision; optimizer-state resume only under this code) | `fine_tune.py` sets no clipping and HASTE has no optimizer-state resume path; both are documented in `configure_optimizers` and the CHANGELOG |
