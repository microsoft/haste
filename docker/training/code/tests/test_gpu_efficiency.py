# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for the GPU efficiency levers in ``bda.trainers`` and ``inference``.

Four levers were ported from the GPU green-loop search (channels-last model
and inputs with cuDNN autotune, fused AdamW, bf16 autocast for the inference
forward pass, pinned non-blocking copies). Each is gated on the device, so
the tests check two things: that CPU behaviour is exactly what it was before
(a non-fused AdamW with the same learning rate and scheduler, inputs left
alone, fp32 inference), and that on a CUDA device the levers engage.
"""

import os
import sys
import unittest

import torch
from torch.optim import AdamW
from torch.optim.lr_scheduler import ReduceLROnPlateau

# The `bda` package lives in the parent directory and is not installed.
CODE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from bda.trainers import (  # noqa: E402
    CustomSemanticSegmentationTask,
    channels_last_if_cuda,
    fused_adamw_supported,
    maybe_channels_last,
)
from inference import inference_autocast_dtype  # noqa: E402

CUDA = torch.cuda.is_available()
LR = 3e-4
PATIENCE = 7


def _tiny_task(**kwargs) -> CustomSemanticSegmentationTask:
    """A small randomly initialised U-Net; no weights are downloaded."""
    torch.manual_seed(0)
    return CustomSemanticSegmentationTask(
        model="unet",
        backbone="resnet18",
        weights=False,
        in_channels=3,
        num_classes=4,
        loss="ce",
        ignore_index=0,
        lr=LR,
        patience=PATIENCE,
        **kwargs,
    )


def _tiny_batch(device: str = "cpu") -> dict:
    torch.manual_seed(1)
    return {
        "image": torch.rand(2, 3, 64, 64, device=device),
        "mask": torch.randint(0, 4, (2, 64, 64), device=device),
    }


class TestFusedAdamWSupported(unittest.TestCase):
    def test_false_for_cpu_parameters(self):
        self.assertFalse(fused_adamw_supported([torch.zeros(2)]))

    def test_false_for_an_empty_parameter_list(self):
        self.assertFalse(fused_adamw_supported([]))

    @unittest.skipUnless(CUDA, "needs a CUDA device")
    def test_true_only_when_every_parameter_is_floating_cuda(self):
        self.assertTrue(fused_adamw_supported([torch.zeros(2, device="cuda")]))
        self.assertFalse(
            fused_adamw_supported(
                [torch.zeros(2, device="cuda"), torch.zeros(2)]
            )
        )
        self.assertFalse(
            fused_adamw_supported(
                [torch.zeros(2, device="cuda", dtype=torch.long)]
            )
        )


class TestConfigureOptimizers(unittest.TestCase):
    def test_cpu_returns_the_base_optimizer_and_scheduler(self):
        """On CPU the result must be byte-for-byte torchgeo's."""
        task = _tiny_task()
        config = task.configure_optimizers()

        self.assertEqual(set(config), {"optimizer", "lr_scheduler"})
        optimizer = config["optimizer"]
        self.assertIsInstance(optimizer, AdamW)
        self.assertEqual(type(optimizer), AdamW)
        self.assertFalse(optimizer.defaults.get("fused"))
        self.assertEqual(optimizer.defaults["lr"], LR)

        lr_scheduler = config["lr_scheduler"]
        self.assertEqual(set(lr_scheduler), {"scheduler", "monitor"})
        self.assertEqual(lr_scheduler["monitor"], task.monitor)
        scheduler = lr_scheduler["scheduler"]
        self.assertIsInstance(scheduler, ReduceLROnPlateau)
        self.assertIs(scheduler.optimizer, optimizer)
        self.assertEqual(scheduler.patience, PATIENCE)

    @unittest.skipUnless(CUDA, "needs a CUDA device")
    def test_cuda_returns_fused_adamw_with_the_scheduler_rebound(self):
        task = _tiny_task().cuda()
        config = task.configure_optimizers()

        optimizer = config["optimizer"]
        self.assertEqual(type(optimizer), AdamW)
        self.assertTrue(optimizer.defaults["fused"])
        self.assertEqual(optimizer.defaults["lr"], LR)
        # The same parameters, in the same order, as the base optimizer.
        owned = [p for g in optimizer.param_groups for p in g["params"]]
        self.assertEqual(
            [id(p) for p in owned], [id(p) for p in task.parameters()]
        )

        lr_scheduler = config["lr_scheduler"]
        self.assertEqual(lr_scheduler["monitor"], task.monitor)
        scheduler = lr_scheduler["scheduler"]
        self.assertIsInstance(scheduler, ReduceLROnPlateau)
        self.assertIs(scheduler.optimizer, optimizer)
        self.assertEqual(scheduler.patience, PATIENCE)

        # The fused kernel actually steps: a forward/backward and an update.
        batch = _tiny_batch("cuda")
        before = [p.detach().clone() for p in task.parameters()]
        loss = task.criterion(task(batch["image"]), batch["mask"])
        loss.backward()
        optimizer.step()
        self.assertTrue(
            any(
                not torch.equal(a, b)
                for a, b in zip(before, task.parameters())
            )
        )


class TestChannelsLastIfCuda(unittest.TestCase):
    def test_cpu_tensor_is_returned_untouched(self):
        x = torch.rand(2, 3, 8, 8)
        self.assertIs(channels_last_if_cuda(x), x)
        self.assertTrue(x.is_contiguous())

    @unittest.skipUnless(CUDA, "needs a CUDA device")
    def test_cuda_4d_tensor_becomes_channels_last(self):
        x = torch.rand(2, 3, 8, 8, device="cuda")
        out = channels_last_if_cuda(x)
        self.assertTrue(out.is_contiguous(memory_format=torch.channels_last))
        self.assertTrue(torch.equal(out, x))

    @unittest.skipUnless(CUDA, "needs a CUDA device")
    def test_cuda_non_4d_tensor_is_returned_untouched(self):
        x = torch.rand(2, 8, 8, device="cuda")
        self.assertIs(channels_last_if_cuda(x), x)


class TestMaybeChannelsLast(unittest.TestCase):
    """``fine_tune.py`` calls this with ``bool(gpu_ids)``, which is False on
    CPU (``gpu_ids`` is emptied when CUDA is unavailable) and True on GPU."""

    def test_cpu_weights_stay_nchw_contiguous(self):
        task = _tiny_task()
        before = {n: p.stride() for n, p in task.model.named_parameters()}

        model = maybe_channels_last(task.model, use_cuda=False)

        self.assertIs(model, task.model)
        # 1x1 or single-input-channel kernels are contiguous in both
        # layouts, so only wider kernels can tell NCHW from NHWC.
        four_d = [
            p
            for p in model.parameters()
            if p.dim() == 4 and p.shape[1] > 1 and p.shape[2] * p.shape[3] > 1
        ]
        self.assertTrue(four_d)
        for p in four_d:
            self.assertTrue(p.is_contiguous())
            self.assertFalse(
                p.is_contiguous(memory_format=torch.channels_last)
            )
        self.assertEqual(
            {n: p.stride() for n, p in model.named_parameters()}, before
        )

    @unittest.skipUnless(CUDA, "needs a CUDA device")
    def test_cuda_weights_become_channels_last(self):
        task = _tiny_task().cuda()
        model = maybe_channels_last(task.model, use_cuda=True)
        for p in model.parameters():
            if p.dim() == 4:
                self.assertTrue(
                    p.is_contiguous(memory_format=torch.channels_last)
                )


class TestTrainingStepOnCpu(unittest.TestCase):
    def test_training_step_runs_without_layout_side_effects(self):
        """A 4-D CPU batch trains as before: NCHW in, NCHW weights."""
        task = _tiny_task()
        batch = _tiny_batch()

        loss = task.training_step(batch, 0)

        self.assertTrue(torch.isfinite(loss))
        self.assertTrue(loss.requires_grad)
        self.assertTrue(batch["image"].is_contiguous())
        self.assertFalse(
            batch["image"].is_contiguous(memory_format=torch.channels_last)
        )
        for p in task.parameters():
            if p.dim() == 4:
                self.assertTrue(p.is_contiguous())

    def test_validation_and_test_steps_run_with_the_constraint_loss(self):
        task = _tiny_task(use_constraint_loss=True, no_damage_index=4)
        task.validation_step(_tiny_batch(), 0)
        task.test_step(_tiny_batch(), 0)

    @unittest.skipUnless(CUDA, "needs a CUDA device")
    def test_training_step_runs_on_a_channels_last_cuda_model(self):
        task = _tiny_task().cuda()
        task.model = task.model.to(memory_format=torch.channels_last)
        loss = task.training_step(_tiny_batch("cuda"), 0)
        self.assertTrue(torch.isfinite(loss))


class _FakeCuda:
    """Stand-in for ``torch.cuda`` describing one GPU generation."""

    def __init__(self, capability: tuple, native_bf16: bool):
        self._capability = capability
        self._native_bf16 = native_bf16
        self.emulation_asked = None

    def get_device_capability(self, device=None):
        return self._capability

    def is_bf16_supported(self, including_emulation: bool = True):
        self.emulation_asked = including_emulation
        # Emulated bf16 reports True everywhere, as on a real T4.
        return self._native_bf16 or including_emulation


class TestInferenceAutocastDtype(unittest.TestCase):
    CUDA0 = torch.device("cuda:0")

    def test_cpu_keeps_fp32(self):
        cuda = _FakeCuda((8, 9), native_bf16=True)
        self.assertIsNone(inference_autocast_dtype(torch.device("cpu"), cuda))
        self.assertIsNone(cuda.emulation_asked)

    def test_turing_keeps_fp32_despite_emulated_bf16(self):
        """A T4 reports emulated bf16; that must not enable autocast."""
        cuda = _FakeCuda((7, 5), native_bf16=False)
        self.assertIsNone(inference_autocast_dtype(self.CUDA0, cuda))

    def test_ampere_or_later_uses_bfloat16_and_asks_for_native(self):
        cuda = _FakeCuda((8, 6), native_bf16=True)
        self.assertIs(
            inference_autocast_dtype(self.CUDA0, cuda), torch.bfloat16
        )
        self.assertIs(cuda.emulation_asked, False)

    @unittest.skipUnless(CUDA, "needs a CUDA device")
    def test_cuda_with_native_bf16_uses_bfloat16(self):
        if torch.cuda.get_device_capability(self.CUDA0)[0] < 8:
            self.skipTest("pre-Ampere GPU has no native bf16")
        self.assertIs(
            inference_autocast_dtype(self.CUDA0, torch.cuda), torch.bfloat16
        )

    @unittest.skipUnless(CUDA, "needs a CUDA device")
    def test_pre_ampere_cuda_keeps_fp32(self):
        if torch.cuda.get_device_capability(self.CUDA0)[0] >= 8:
            self.skipTest("Ampere or later GPU has native bf16")
        self.assertIsNone(inference_autocast_dtype(self.CUDA0, torch.cuda))


if __name__ == "__main__":
    unittest.main()
