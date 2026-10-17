# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Deterministic offline DINOv2 architecture and native raster contracts."""

import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import rasterio
import torch
import yaml
from rasterio.enums import Resampling

CODE_DIR = str(Path(__file__).resolve().parents[1])
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

import inference_dinov2 as inference  # noqa: E402
import inference_dinov3 as shared  # noqa: E402
from bda.dinov2_upernet import (  # noqa: E402
    BACKBONE,
    BACKBONE_REVISION,
    EXPECTED_CONFIG,
    SOURCE_REVISION,
    DINOv2UPerNet,
)
from tests.test_inference_dinov3 import FakeClassifier, write_rgb  # noqa: E402


class RasterInferenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.threads = torch.get_num_threads()
        torch.set_num_threads(2)

    @classmethod
    def tearDownClass(cls) -> None:
        torch.set_num_threads(cls.threads)

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.input = self.root / "rgb.tif"
        self.output = self.root / "fixture_predictions.tif"
        self.checkpoint = self.root / "model.ckpt"

    def run_fixture(self, **kwargs) -> None:
        options = {
            "device": "cpu",
            "patch_size": 32,
            "padding": 8,
            "batch_size": 3,
            "num_workers": 0,
            "overwrite": True,
        }
        options.update(kwargs)
        with mock.patch.object(
            inference,
            "load_model",
            return_value=FakeClassifier(options["padding"]),
        ):
            inference.run_inference(
                self.input,
                self.checkpoint,
                self.output,
                "a" * 64,
                **options,
            )

    def test_tiny_images_and_grid_seams_preserve_mask_and_georeferencing(
        self,
    ) -> None:
        for height, width in ((1, 1), (1, 7), (53, 71)):
            mask = np.full((height, width), 255, dtype=np.uint8)
            mask[0, 0] = 0
            mask[14:19, 15:35] = 0
            rgb = write_rgb(self.input, height, width, mask=mask)
            for workers in (0, 2):
                with self.subTest(shape=(height, width), workers=workers):
                    self.run_fixture(num_workers=workers)
                    with (
                        rasterio.open(self.input) as src,
                        rasterio.open(self.output) as dst,
                    ):
                        np.testing.assert_array_equal(
                            dst.read(1), np.where(mask, rgb[0] % 3 + 1, 0)
                        )
                        np.testing.assert_array_equal(dst.read_masks(1), mask)
                        self.assertEqual(dst.crs, src.crs)
                        self.assertEqual(dst.transform, src.transform)
                        self.assertEqual(dst.bounds, src.bounds)
                        self.assertEqual(dst.res, src.res)
                        self.assertEqual(dst.nodata, 0)
                        self.assertEqual(
                            dst.tags(ns="IMAGE_STRUCTURE")["LAYOUT"], "COG"
                        )
                        self.assertEqual(
                            dst.tags()["ADAPTER"], "dinov2_upernet"
                        )
                        self.assertEqual(
                            dst.tags()["SOURCE_REVISION"], SOURCE_REVISION
                        )
                        self.assertEqual(
                            dst.tags()["BACKBONE_CONFIG_SOURCE"],
                            "checkpoint.hyper_parameters",
                        )
                        self.assertNotIn("BACKBONE_CONFIG_SHA256", dst.tags())

    def test_unclipped_normalization_and_per_band_nodata(self) -> None:
        rgb = write_rgb(self.input, 32, 32, nodata=0)
        with shared.patch_batches(
            self.input, [(0, 0)], 1, 32, 0, torch.device("cpu"), 0, 2
        ) as batches:
            images, masks, _ = next(batches)
        expected = (
            rgb.astype(np.float32) / 255.0
            - np.array([0.485, 0.456, 0.406], dtype=np.float32)[:, None, None]
        ) / np.array([0.229, 0.224, 0.225], dtype=np.float32)[:, None, None]
        np.testing.assert_allclose(images[0].numpy(), expected, atol=1e-6)
        np.testing.assert_array_equal(masks[0], (rgb != 0).all(axis=0))
        self.assertLess(images.min().item(), 0)
        self.assertGreater(images.max().item(), 1)
        self.run_fixture()
        with rasterio.open(self.output) as dst:
            np.testing.assert_array_equal(
                dst.read(1), np.where(masks[0], rgb[0] % 3 + 1, 0)
            )

    def test_overviews_are_exact_nearest_not_class_averages(self) -> None:
        rgb = write_rgb(self.input, 1024, 1024)
        self.run_fixture(patch_size=512, padding=0)
        expected = rgb[0] % 3 + 1
        with rasterio.open(self.output) as dst:
            self.assertEqual(dst.overviews(1), [2])
            np.testing.assert_array_equal(dst.read(1), expected)
            np.testing.assert_array_equal(
                dst.read(
                    1, out_shape=(512, 512), resampling=Resampling.nearest
                ),
                expected[::2, ::2],
            )

    def test_invalid_source_and_settings_do_not_load_weights(self) -> None:
        write_rgb(self.input, 32, 32, crs=None)
        with mock.patch.object(inference, "load_model") as loader:
            with self.assertRaisesRegex(ValueError, "CRS"):
                inference.run_inference(
                    self.input,
                    self.checkpoint,
                    self.output,
                    "a" * 64,
                    device="cpu",
                )
            loader.assert_not_called()
        for settings in (
            {"patch_size": 31},
            {"padding": 256},
            {"batch_size": 0},
            {"num_workers": -1},
            {"prefetch_factor": 0},
            {"padding": 1.5},
        ):
            with (
                self.subTest(settings=settings),
                self.assertRaises(ValueError),
            ):
                self.run_fixture(**settings)
        with mock.patch.object(torch.cuda, "is_available", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "CUDA"):
                self.run_fixture(device="cuda:0")

    def test_nonfinite_or_wrong_shape_leaves_no_published_output(self) -> None:
        write_rgb(self.input, 3, 5)
        for output, message in (
            (torch.full((1, 3, 32, 32), float("nan")), "non-finite"),
            (torch.zeros(1, 3, 33, 32), "logit shape"),
        ):
            with (
                mock.patch.object(
                    FakeClassifier, "forward", return_value=output
                ),
                self.assertRaisesRegex(RuntimeError, message),
            ):
                self.run_fixture()
            self.assertFalse(self.output.exists())

    def test_input_assets_cannot_be_overwritten(self) -> None:
        for destination in (self.input, self.checkpoint):
            with self.subTest(destination=destination):
                with self.assertRaisesRegex(ValueError, "input asset"):
                    inference.run_inference(
                        self.input,
                        self.checkpoint,
                        destination,
                        "a" * 64,
                        device="cpu",
                    )

    def test_yaml_uses_rgb_checkpoint_and_explicit_output_without_config(
        self,
    ) -> None:
        config = {
            "experiment_dir": str(self.root),
            "imagery": {"rgb_fn": "processed.tif", "raw_fn": "native.tif"},
            "inference": {
                "adapter": "dinov2_upernet",
                "checkpoint_fn": "model.ckpt",
                "checkpoint_sha256": "a" * 64,
                "predictions_filename": "chosen_predictions.tif",
            },
        }
        config_fn = self.root / "config.yml"

        def main() -> mock.Mock:
            config_fn.write_text(yaml.safe_dump(config))
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    ["inference_dinov2.py", "--config", str(config_fn)],
                ),
                mock.patch.object(inference, "run_inference") as run,
            ):
                inference.main()
            return run

        run = main()
        args, kwargs = run.call_args
        self.assertEqual(
            args,
            (
                "processed.tif",
                self.checkpoint,
                self.root / "inference/chosen_predictions.tif",
                "a" * 64,
            ),
        )
        self.assertEqual(kwargs["device"], "cuda:0")
        for change in (
            {"adapter": "dinov3_upernet"},
            {"gpu_id": True},
            {"predictions_filename": "../unsafe_predictions.tif"},
            {"backbone_config_fn": "external.json"},
            {"backbone_config_sha256": "b" * 64},
        ):
            old = config["inference"].copy()
            config["inference"].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                main()
            config["inference"] = old


class ModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.threads = torch.get_num_threads()
        torch.set_num_threads(2)
        torch.manual_seed(42)
        cls.model = DINOv2UPerNet(BACKBONE, EXPECTED_CONFIG).eval()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.checkpoint = Path(cls.tmp.name) / "fixture.ckpt"
        cls.hparams = {
            "model": "upernet",
            "backbone": BACKBONE,
            "in_channels": 3,
            "num_classes": 3,
            "ignore_index": 255,
            "backbone_revision": BACKBONE_REVISION,
            "backbone_config": EXPECTED_CONFIG,
        }
        torch.save(
            {
                "hyper_parameters": cls.hparams,
                "state_dict": {
                    "model." + key: value
                    for key, value in cls.model.state_dict().items()
                },
            },
            cls.checkpoint,
        )
        cls.sha = hashlib.sha256(cls.checkpoint.read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls) -> None:
        del cls.model
        cls.tmp.cleanup()
        torch.set_num_threads(cls.threads)

    def test_actual_structure_restricted_strict_load_and_cpu_forward(
        self,
    ) -> None:
        with (
            mock.patch(
                "socket.socket.connect", side_effect=AssertionError("network")
            ),
            mock.patch.object(torch, "load", wraps=torch.load) as loader,
        ):
            model = inference.load_model(self.checkpoint, self.sha, "cpu")
        self.assertTrue(loader.call_args.kwargs["weights_only"])
        self.assertFalse(model.training)
        self.assertFalse(any(p.requires_grad for p in model.parameters()))
        self.assertEqual(sum(p.numel() for p in model.parameters()), 31897347)
        self.assertEqual(len(model.state_dict()), 270)
        self.assertEqual(model.backbone.out_indices, [3, 6, 9, 12])
        self.assertEqual(model.backbone.num_prefix_tokens, 5)
        with torch.inference_mode():
            logits = model(torch.zeros(1, 3, 15, 29))
        self.assertEqual(logits.shape, (1, 3, 15, 29))
        self.assertTrue(torch.isfinite(logits).all())

    def test_missing_extra_and_mismatched_model_tensors_fail_strictly(
        self,
    ) -> None:
        state = {"model." + k: v for k, v in self.model.state_dict().items()}
        for mutation in ("missing", "extra", "shape"):
            modified = dict(state)
            if mutation == "missing":
                del modified["model.decode_head.classifier.bias"]
            elif mutation == "extra":
                modified["model.unexpected"] = torch.zeros(1)
            else:
                modified["model.decode_head.classifier.bias"] = torch.zeros(4)
            with (
                mock.patch.object(
                    torch,
                    "load",
                    return_value={
                        "hyper_parameters": self.hparams,
                        "state_dict": modified,
                    },
                ),
                self.subTest(mutation=mutation),
                self.assertRaises(RuntimeError),
            ):
                inference.load_model(self.checkpoint, self.sha, "cpu")

    def test_wrong_hash_and_old_torch_fail_before_deserialization(
        self,
    ) -> None:
        with mock.patch.object(torch, "load") as loader:
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                inference.load_model(self.checkpoint, "a" * 64, "cpu")
            loader.assert_not_called()
        for version in ("2.5.1", "2.9.1", "2.10.0rc1"):
            with mock.patch.object(torch, "__version__", version):
                with self.assertRaisesRegex(RuntimeError, r"torch>=2\.10\.0"):
                    inference.load_model("absent.ckpt", self.sha, "cpu")

    def test_unknown_architectures_decoder_and_backbone_config_fail(
        self,
    ) -> None:
        for change in (
            {"backbone": "dinov2_vitb14_reg"},
            {"backbone": "dinov3_vits16"},
            {"model": "unet"},
            {"num_classes": 4},
            {"in_channels": True},
            {"ignore_index": 0},
            {"backbone_revision": "a" * 40},
            {"decoder_variant": "rgb_refine_s2"},
            {"refinement_channels": 64},
            {"backbone_config": None},
        ):
            hparams = dict(self.hparams, **change)
            with (
                mock.patch.object(
                    torch,
                    "load",
                    return_value={
                        "hyper_parameters": hparams,
                        "state_dict": {},
                    },
                ),
                self.subTest(change=change),
                self.assertRaises(ValueError),
            ):
                inference.load_model(self.checkpoint, self.sha, "cpu")
        for change in (
            {"num_attention_heads": 12},
            {"interpolate_offset": 0.1},
            {"layer_norm_eps": 1e-5},
            {"hidden_act": "relu"},
            {"auto_map": {"AutoModel": "remote.code"}},
            {"hidden_size": float("nan")},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                DINOv2UPerNet(BACKBONE, dict(EXPECTED_CONFIG, **change))
        for field in EXPECTED_CONFIG:
            config = copy.deepcopy(EXPECTED_CONFIG)
            del config[field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                DINOv2UPerNet(BACKBONE, config)

    def test_raw_block_selection_strips_registers_before_reshape(self) -> None:
        backbone = self.model.backbone
        tokens = torch.cat((torch.full((5,), -999.0), torch.arange(6).float()))
        tokens = tokens[None, :, None].expand(1, -1, 384)
        outputs = SimpleNamespace(
            hidden_states=tuple(tokens + i for i in range(13)),
            last_hidden_state=tokens + 999,
        )
        with mock.patch.object(backbone.vit, "forward", return_value=outputs):
            features = backbone(torch.zeros(1, 3, 28, 42))
        for index, feature in zip((3, 6, 9, 12), features):
            torch.testing.assert_close(
                feature[0, 0],
                torch.arange(6).reshape(2, 3).float() + index,
                rtol=0,
                atol=0,
            )
        with self.assertRaisesRegex(ValueError, "divisible"):
            backbone(torch.zeros(1, 3, 32, 32))
        with (
            mock.patch.object(
                backbone.vit,
                "forward",
                return_value=SimpleNamespace(
                    hidden_states=(tokens[:, :-1],) * 13,
                ),
            ),
            self.assertRaisesRegex(ValueError, "patch-token grid"),
        ):
            backbone(torch.zeros(1, 3, 28, 42))

    def test_internal_reflection_upsample_then_crop_not_external_resize(
        self,
    ) -> None:
        model = self.model
        coarse = torch.arange(3 * 5 * 7).reshape(1, 3, 5, 7).float()
        features = [torch.zeros(1, 384, 2, 2)] * 4
        with (
            mock.patch.object(
                model.backbone, "forward", return_value=features
            ) as backbone,
            mock.patch.object(
                model.decode_head, "forward", return_value=coarse
            ),
            torch.inference_mode(),
        ):
            for height, width in ((15, 15), (29, 43), (28, 42), (512, 512)):
                image = (
                    torch.arange(3 * height * width)
                    .reshape(1, 3, height, width)
                    .float()
                )
                output = model(image)
                padded = torch.nn.functional.pad(
                    image, (0, -width % 14, 0, -height % 14), mode="reflect"
                )
                torch.testing.assert_close(
                    backbone.call_args.args[0], padded, rtol=0, atol=0
                )
                expected = torch.nn.functional.interpolate(
                    coarse,
                    size=padded.shape[-2:],
                    mode="bilinear",
                    align_corners=False,
                )[..., :height, :width]
                torch.testing.assert_close(output, expected, rtol=0, atol=0)
        for shape in ((3, 28, 28), (1, 4, 28, 28), (1, 3, 14, 28)):
            with self.subTest(shape=shape), self.assertRaises(ValueError):
                model(torch.zeros(shape))


if __name__ == "__main__":
    unittest.main()
