# Technical Design: Energy-aware training and inference

## Contents

- [1. Problem](#1-problem)
- [2. The four levers](#2-the-four-levers)
- [3. Device gating](#3-device-gating)
- [4. Measured results and provenance](#4-measured-results-and-provenance)
- [5. Constraints](#5-constraints)
- [6. Known non-determinism](#6-known-non-determinism)
- [7. Remaining verification](#7-remaining-verification)
- [8. Testing](#8-testing)

## 1. Problem

A Damage Mapping job runs `run_workflow.py` on one GPU Batch node:
`create_masks.py`, `fine_tune.py`, `inference.py`,
`merge_with_building_footprints.py`, then scoring. The GPU is busy in two
places only, the training step in `bda/trainers.py` and the inference batch
loop in `inference.py`, and both ran with PyTorch's defaults: NCHW tensors,
per-tensor optimizer kernels, cuDNN's heuristic algorithm choice, fp32
inference on every GPU. Each of those defaults leaves energy on the table on
a modern GPU, and HASTE pays for it once per job.

The goal is less GPU energy and wall time per job with the training
objective, the checkpoint format and the prediction raster format unchanged.

## 2. The four levers

| Lever | Where | What it changes | Why it is safe |
|---|---|---|---|
| Channels-last (NHWC) weights and inputs | `fine_tune.py` via `maybe_channels_last`; `trainers.py` step functions via `channels_last_if_cuda`; `inference.py` | Memory layout of 4-D tensors so cuDNN runs convolutions on tensor cores without inserting layout transposes | Layout only. The same values are read and written; the convolution arithmetic is the same kernel family at a different stride order |
| cuDNN autotuning | `torch.backends.cudnn.benchmark = True` in `fine_tune.py` and `inference.py` | cuDNN times its candidate algorithms for each new input shape and reuses the fastest | Patches are a fixed size, so the benchmark runs once per shape. Algorithm choice does not change the operation, only its implementation (see §6 for the reproducibility cost) |
| Fused AdamW | `CustomSemanticSegmentationTask.configure_optimizers` | One kernel launch steps every parameter instead of one launch per tensor | Same update rule, same hyperparameters (`lr`, `patience`, monitor key are copied from the torchgeo base optimizer and scheduler); only the kernel differs. Precondition is checked exactly: every parameter a floating CUDA tensor |
| bf16 autocast, inference only | `inference_autocast_dtype` and the batch loop in `inference.py` | The forward pass runs with bf16 activations where autocast allows, roughly halving the memory traffic of every convolution | Inference is a forward pass ending in an argmax; training is untouched. The argmax does move on some pixels (about 1% on a one-epoch checkpoint, 3% on a randomly initialised network), and building-level accuracy, damaged-building F1 and pixel mIoU stayed within the run-to-run spread on both measured jobs (§4). Only GPUs with native bf16 take this path (§3) |

Two smaller changes ride along in `inference.py`: the `DataLoader` pins host
memory when running on CUDA, and the host-to-device copy is `non_blocking`,
so the copy of batch *n+1* overlaps the forward pass of batch *n*.

The three helpers in `bda/trainers.py` are pure functions so the gates can
be tested without hardware:

```python
def channels_last_if_cuda(x: Tensor) -> Tensor
def maybe_channels_last(model: torch.nn.Module, use_cuda: bool) -> torch.nn.Module
def fused_adamw_supported(params: list[Tensor]) -> bool
```

`inference_autocast_dtype(device, cuda)` in `inference.py` takes the
`torch.cuda` module as an argument, as `bda.config.select_precision` does,
and asks `cuda.is_bf16_supported(including_emulation=False)` after a
compute-capability check.

## 3. Device gating

Every lever decides on the device it runs on, not on a configuration flag.
`fine_tune.py` gates on `gpu_ids`, which is already emptied when CUDA is
unavailable; `inference.py` gates on `device.type`.

| Device class | Channels-last | cuDNN autotune | Fused AdamW | bf16 inference | Measured |
|---|---|---|---|---|---|
| CPU | no (weights stay NCHW, inputs untouched) | set, no effect | no (base torchgeo AdamW) | no (fp32) | unit tests only; numerics identical to `main` |
| Turing (T4, sm_75) | yes | yes | yes | no (fp32; emulated bf16 is refused) | not measured |
| Ampere and later (A10, A100, L4, RTX 6000 Ada, ...) | yes | yes | yes | yes | RTX 6000 Ada, §4 |

The CPU row is exact: the only thing that changes on CPU is a
`cudnn.benchmark` flag that cuDNN never reads. The Turing row is the
reason the CHANGELOG does not say pre-Ampere GPUs "behave as before"; three
levers engage there and channels-last fp32 on Turing has not been timed.

Training precision is unchanged by this spec: `select_precision` still
picks `bf16-mixed` for the training loop on native-bf16 GPUs and `32-true`
otherwise, the decision recorded in
[training-workflow-sync/design.md §6](../training-workflow-sync/design.md#6-deliberate-deviations-from-upstream).
The inference gate reuses that decision's test (`including_emulation=False`)
rather than introducing a second definition of "has bf16".

## 4. Measured results and provenance

### Paired job measurements

Each measurement ran the full Damage Mapping job (mask creation, one
training epoch, inference, merge, scoring) with the unmodified `main` and
this branch as a pair on the same RTX 6000 Ada, measuring GPU energy per
run. The ratio is `main` divided by this branch, so values above 1 favour
this branch; intervals are 95% confidence intervals over the paired runs.

| Job | Paired runs | GPU-energy ratio | Wall-time ratio | Quality |
|---|---|---|---|---|
| LA fires, Palisades | 4 | 1.292 [1.277, 1.300] | 1.20 | within run-to-run spread |
| LA fires, Eaton (hidden job, held out from the search) | 2 | 1.289 [1.288, 1.289] | 1.19 | within run-to-run spread |

"Within run-to-run spread" means building-level accuracy, damaged-building
F1 and pixel mIoU of this branch fell inside the spread of repeated,
unseeded runs of `main` on the same job. HASTE's training is unseeded, so
that spread is the right yardstick; no pixel-exact match is claimed.

Expressed as savings: GPU energy per job down about 22 to 23%, wall time
about 17% shorter.

### bf16 inference, measured separately

Against fp32 on the same checkpoint, bf16 autocast changed the
argmax class on about 1% of pixels for a one-epoch checkpoint and about 3%
for a randomly initialised network. The building-level metrics above
already include that effect.

### Where the levers came from

The levers were found by a GPU green-loop kernel search over two
standalone kernels extracted from HASTE: the training step and the
inference batch. The best kernel found by that search combined the same
four levers and measured a GPU-energy ratio of 1.299 to 1.307 against the
unmodified kernels on the Palisades job. The hand port into the workflow
scripts (this branch) measures 1.29 on the full job; the kernel figure
covers the two GPU-bound code paths in isolation, the job figure includes
the rest of the workflow.

## 5. Constraints

Both come from `fused=True` on AdamW and are documented in
`configure_optimizers` and the CHANGELOG.

1. **No Lightning gradient clipping under mixed precision.** Lightning
   raises if `gradient_clip_val` is set with a fused optimizer under mixed
   precision. `fine_tune.py` sets no clipping today. Anyone adding it must
   drop `fused` in `configure_optimizers` (or clip manually).
2. **Optimizer-state resume is one-way.** A checkpoint written by this
   code carries a param group with `fused=True` and moment tensors in
   channels-last layout. Resuming it *with optimizer state* under the
   pre-change code fails to match the NCHW parameters; resuming a
   pre-change checkpoint with optimizer state under this code has the
   mirror problem. Weight-only loading is unaffected in both directions:
   `inference.py` (`load_from_checkpoint`), `fine_tune.py`'s
   `initial_weights_path` filter read the `state_dict` only, and
   `run_workflow.py`'s `*.ckpt` glob only checks that a checkpoint exists.
   HASTE has no optimizer-state resume path today, so nothing in the
   product exercises the incompatible case.

## 6. Known non-determinism

`cudnn.benchmark = True` lets cuDNN pick a convolution algorithm per
input shape by timing, and different algorithms accumulate in different
orders. Two runs on the same node can therefore differ at the last bits
even with identical seeds, and that difference propagates through a
training run. HASTE's training was already unseeded (random sampler, no
`seed_everything`), so run-to-run variation is the existing state and the
quality criterion in §4 is defined against it. Anyone adding seeded,
bit-reproducible training would need to set `cudnn.benchmark = False` and
`cudnn.deterministic = True`, at a speed cost that has not been measured.

## 7. Remaining verification

Measured so far: RTX 6000 Ada, single GPU, one training epoch, in an image
whose conda environment is Python 3.10. Still to do in dev:

- **Full image build on Python 3.11.** `docker/training/env/env.yml` pins
  Python 3.11 and torch 2.5.1+cu124; the suite and a job should run in an
  image built from the current Dockerfile.
- **T4 node.** A Damage Mapping job end to end on a Turing pool, confirming
  fp32 inference is selected and recording the channels-last fp32 timing.
- **Multi-GPU DDP.** `--training.gpu_ids 0 1`: the fused optimizer and
  channels-last weights under Lightning's `ddp` strategy.
- **Converged checkpoint.** Building-level metrics against `main` after a
  full training schedule, not the one-epoch runs used for the paired
  measurements.

## 8. Testing

`docker/training/code/tests/test_gpu_efficiency.py` (unittest style, run
by pytest) covers:

- `fused_adamw_supported`: false for CPU parameters, an empty list, or any
  non-floating CUDA tensor; true only when every parameter is a floating
  CUDA tensor.
- `configure_optimizers`: on CPU the result is torchgeo's base optimizer
  and scheduler (type, `lr`, `patience`, monitor key, dict shape); on CUDA
  a fused AdamW owning the same parameters in the same order, with the
  scheduler rebound to it, and one real optimizer step.
- `channels_last_if_cuda` and `maybe_channels_last`: CPU tensors and CPU
  weights keep their NCHW strides (checked on the kernels wide enough to
  tell the layouts apart; 1x1 kernels are contiguous in both); CUDA tensors
  and weights become channels-last.
- Step functions: a CPU training step leaves the batch and the weights
  NCHW; validation and test steps run with the constraint loss; a CUDA
  training step runs on a channels-last model.
- `inference_autocast_dtype`: CPU keeps fp32; a fake `torch.cuda` reporting
  Turing (sm_75, emulated bf16 only) keeps fp32; a fake reporting Ampere
  returns bf16 and was asked for native support; the real device is also
  checked when CUDA is present.

CUDA cases are skipped without a GPU, so the file passes on CPU-only CI
with the GPU branches reported as skips.

Run the training-code suite inside the training image, which carries the
pinned torch, Lightning and torchgeo. The entrypoint runs its argument
through `bash -c` after `cd /app`, so the checkout is mounted elsewhere and
entered explicitly:

```bash
# CPU
docker run --rm --network none --user "$(id -u):$(id -g)" --env HOME=/tmp \
  -v "$PWD/docker/training/code:/code:ro" haste-training \
  "cd /code && python -m pytest -q -p no:cacheprovider tests"

# GPU 0
docker run --rm --gpus device=0 --network none --user "$(id -u):$(id -g)" \
  --env HOME=/tmp -v "$PWD/docker/training/code:/code:ro" haste-training \
  "cd /code && python -m pytest -q -p no:cacheprovider tests"
```

Add `tests/test_gpu_efficiency.py` after `tests` to run only this feature's
tests.
