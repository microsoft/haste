# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Native deterministic GIS fixtures; real asset acceptance is separately opt-in."""

import ast
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import rasterio
import torch
import yaml
from rasterio.enums import ColorInterp, Resampling
from rasterio.transform import from_origin

CODE_DIR = str(Path(__file__).resolve().parents[1])
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

import inference_dinov3 as inference  # noqa: E402
from bda.dinov3_upernet import DINOv3UPerNet  # noqa: E402


def write_rgb(path, height, width, mask=None, nodata=None, crs="EPSG:32610"):
    red = np.indices((height, width)).sum(axis=0).astype(np.uint8)
    rgb = np.stack([red, red // 2, np.full_like(red, 255)])
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=3,
        dtype="uint8",
        crs=crs,
        transform=from_origin(500000, 4200000, 2, 2),
        nodata=nodata,
    ) as dst:
        dst.write(rgb)
        dst.colorinterp = (
            ColorInterp.red,
            ColorInterp.green,
            ColorInterp.blue,
        )
        if mask is not None:
            dst.write_mask(mask)
    return rgb


class FakeClassifier(torch.nn.Module):
    """Invert normalization, classify red modulo three; optionally poison margins."""

    def __init__(self, margin=0):
        super().__init__()
        self.margin = margin

    def forward(self, images):
        red = images[:, 0] * float(inference.IMAGENET_STD[0])
        red = red + float(inference.IMAGENET_MEAN[0])
        classes = red.round().long() % 3
        if self.margin:
            classes[:, : self.margin] = 2
            classes[:, -self.margin :] = 2
            classes[:, :, : self.margin] = 2
            classes[:, :, -self.margin :] = 2
        return (
            torch.nn.functional.one_hot(classes, 3).permute(0, 3, 1, 2).float()
        )


class RasterInferenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.threads = torch.get_num_threads()
        torch.set_num_threads(2)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.threads)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.input = self.root / "rgb.tif"
        self.output = self.root / "fixture_predictions.tif"

    def run_fixture(self, **kwargs):
        margin = kwargs.get("padding", 8)
        options = {
            "device": "cpu",
            "patch_size": 32,
            "padding": margin,
            "batch_size": 3,
            "num_workers": 0,
            "overwrite": True,
        }
        options.update(kwargs)
        with mock.patch.object(
            inference, "load_model", return_value=FakeClassifier(margin)
        ):
            inference.run_inference(
                self.input,
                self.root / "unused.ckpt",
                self.output,
                self.root / "unused.json",
                "a" * 64,
                "b" * 64,
                **options,
            )

    def test_remapping_preserves_background_and_nodata(self):
        values = np.array([[0, 1, 2, 255, 2]], dtype=np.uint8)
        valid = np.array([[True, True, True, True, False]])
        np.testing.assert_array_equal(
            inference.remap_classes(values, valid), [[1, 2, 3, 0, 0]]
        )
        with self.assertRaises(ValueError):
            inference.remap_classes(np.array([4]), np.array([True]))

    def test_tiny_and_seamed_images_have_every_core_written_once(self):
        for height, width in [(1, 1), (1, 7), (5, 9), (53, 71)]:
            with self.subTest(shape=(height, width)):
                rgb = write_rgb(self.input, height, width)
                for workers in (0, 2):
                    self.run_fixture(num_workers=workers)
                    with rasterio.open(self.output) as dst, rasterio.open(
                        self.input
                    ) as src:
                        np.testing.assert_array_equal(
                            dst.read(1), rgb[0] % 3 + 1
                        )
                        self.assertEqual(dst.crs, src.crs)
                        self.assertEqual(dst.transform, src.transform)
                        self.assertEqual(dst.bounds, src.bounds)
                        self.assertEqual(dst.res, src.res)
                        self.assertEqual(dst.nodata, 0)
                        self.assertEqual(
                            dst.tags(ns="IMAGE_STRUCTURE")["LAYOUT"], "COG"
                        )
                        self.assertEqual(
                            dst.tags()["CHECKPOINT_SHA256"], "a" * 64
                        )
                        self.assertTrue(dst.read_masks(1).all())

    def test_reflection_reader_matches_numpy_even_when_larger_than_image(self):
        rgb = write_rgb(self.input, 3, 5)
        expected = np.pad(rgb, ((0, 0), (8, 30), (8, 30)), mode="reflect")[
            :, :32, :32
        ]
        with rasterio.open(self.input) as src:
            patch, valid = inference.read_patch(src, 0, 0, 32, 8)
        np.testing.assert_array_equal(patch, expected)
        self.assertTrue(valid.all())

    def test_external_mask_and_per_band_nodata_are_preserved(self):
        mask = np.full((53, 71), 255, dtype=np.uint8)
        mask[14:19, 15:35] = 0  # crosses patch/core seams
        rgb = write_rgb(self.input, 53, 71, mask=mask)
        self.run_fixture(num_workers=2)
        with rasterio.open(self.output) as dst:
            expected = np.where(mask, rgb[0] % 3 + 1, 0)
            np.testing.assert_array_equal(dst.read(1), expected)
            np.testing.assert_array_equal(dst.read_masks(1), mask)
        # A fresh path avoids carrying over the explicit .msk fixture.
        self.input = self.root / "per_band.tif"
        rgb = write_rgb(self.input, 5, 9, nodata=0)
        self.run_fixture()
        with rasterio.open(self.output) as dst:
            expected = np.where((rgb != 0).all(axis=0), rgb[0] % 3 + 1, 0)
            np.testing.assert_array_equal(dst.read(1), expected)

    def test_normalization_is_imagenet_without_clipping(self):
        rgb = write_rgb(self.input, 32, 32)
        with inference.patch_batches(
            self.input, [(0, 0)], 1, 32, 0, torch.device("cpu"), 0, 2
        ) as batches:
            images, _, _ = next(batches)
        expected = (
            rgb.astype(np.float32) / 255
            - np.array([0.485, 0.456, 0.406], dtype=np.float32)[:, None, None]
        ) / np.array([0.229, 0.224, 0.225], dtype=np.float32)[:, None, None]
        np.testing.assert_allclose(images[0].numpy(), expected, atol=1e-6)
        self.assertLess(images.min().item(), 0)
        self.assertGreater(images.max().item(), 1)

    def test_zero_padding_and_categorical_overviews(self):
        rgb = write_rgb(self.input, 520, 529)
        self.run_fixture(patch_size=512, padding=0)
        with rasterio.open(self.output) as dst:
            np.testing.assert_array_equal(dst.read(1), rgb[0] % 3 + 1)
            self.assertTrue(dst.overviews(1))
            overview = dst.read(
                1, out_shape=(260, 265), resampling=Resampling.nearest
            )
            self.assertTrue(set(np.unique(overview)) <= {1, 2, 3})

    def test_bad_rgb_and_missing_crs_rejected_before_model(self):
        for crs, interp in [
            (None, (ColorInterp.red, ColorInterp.green, ColorInterp.blue)),
            (
                "EPSG:32610",
                (ColorInterp.blue, ColorInterp.green, ColorInterp.red),
            ),
        ]:
            write_rgb(self.input, 32, 32, crs=crs)
            with rasterio.open(self.input, "r+") as dst:
                dst.colorinterp = interp
            with mock.patch.object(inference, "load_model") as loader:
                with self.assertRaises(ValueError):
                    inference.run_inference(
                        self.input,
                        "unused.ckpt",
                        self.output,
                        "unused.json",
                        "a" * 64,
                        "b" * 64,
                        device="cpu",
                    )
                loader.assert_not_called()

    def test_cuda_absence_and_invalid_settings_fail_explicitly(self):
        write_rgb(self.input, 3, 5)
        with mock.patch.object(torch.cuda, "is_available", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "CUDA"):
                self.run_fixture(device="cuda:0")
        for options in [
            {"patch_size": 31},
            {"padding": 16},
            {"batch_size": 0},
            {"num_workers": -1},
            {"prefetch_factor": 0},
            {"padding": 1.5},
        ]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.run_fixture(**options)

    def test_extra_bands_and_non_uint8_are_not_silently_coerced(self):
        for count, dtype in [(1, "uint8"), (4, "uint8"), (3, "uint16")]:
            with self.subTest(count=count, dtype=dtype):
                with rasterio.open(
                    self.input,
                    "w",
                    driver="GTiff",
                    width=3,
                    height=5,
                    count=count,
                    dtype=dtype,
                    crs="EPSG:32610",
                    transform=from_origin(500000, 4200000, 2, 2),
                ) as dst:
                    dst.write(np.ones((count, 5, 3), dtype=dtype))
                with rasterio.open(self.input) as src:
                    with self.assertRaisesRegex(ValueError, "8-bit"):
                        inference.validate_source(src)

    def test_nonfinite_model_output_leaves_no_published_raster(self):
        write_rgb(self.input, 3, 5)
        with mock.patch.object(
            FakeClassifier,
            "forward",
            return_value=torch.full((1, 3, 32, 32), float("nan")),
        ), self.assertRaisesRegex(RuntimeError, "non-finite"):
            self.run_fixture()
        self.assertFalse(self.output.exists())

    def test_yaml_uses_rgb_explicit_name_defaults_and_no_training_fields(self):
        config = {
            "experiment_dir": str(self.root),
            "imagery": {"rgb_fn": "processed.tif", "raw_fn": "native.tif"},
            "inference": {
                "adapter": "dinov3_upernet",
                "checkpoint_fn": "model.ckpt",
                "backbone_config_fn": "config.json",
                "checkpoint_sha256": "a" * 64,
                "backbone_config_sha256": "b" * 64,
                "predictions_filename": "chosen_predictions.tif",
            },
        }
        config_fn = self.root / "experiment.yml"
        config_fn.write_text(yaml.safe_dump(config))
        with mock.patch.object(
            sys,
            "argv",
            ["inference_dinov3.py", "--config", str(config_fn), "--overwrite"],
        ), mock.patch.object(inference, "run_inference") as run:
            inference.main()
        args, kwargs = run.call_args
        self.assertEqual(args[0], "processed.tif")
        self.assertEqual(args[1], self.root / "model.ckpt")
        self.assertEqual(
            args[2], self.root / "inference/chosen_predictions.tif"
        )
        self.assertEqual(kwargs["device"], "cuda:0")


class StrictModelFixtureTest(unittest.TestCase):
    """Real torch/HF module with generated weights/config, NOT public asset acceptance."""

    @classmethod
    def setUpClass(cls):
        from transformers import DINOv3ViTConfig

        cls.threads = torch.get_num_threads()
        torch.set_num_threads(2)
        cls.config = DINOv3ViTConfig(
            hidden_size=32,
            intermediate_size=64,
            num_hidden_layers=4,
            num_attention_heads=4,
            num_register_tokens=4,
        ).to_dict()
        torch.manual_seed(42)
        cls.model = DINOv3UPerNet("dinov3_vits16", cls.config).eval()

    @classmethod
    def tearDownClass(cls):
        del cls.model
        torch.set_num_threads(cls.threads)

    def test_exact_structure_and_forward_offline(self):
        with mock.patch(
            "socket.socket.connect", side_effect=AssertionError("network")
        ):
            model = DINOv3UPerNet("dinov3_vits16", self.config).eval()
            model.load_state_dict(self.model.state_dict(), strict=True)
            with torch.inference_mode():
                output = model(torch.zeros(1, 3, 32, 32))
        self.assertEqual(output.shape, (1, 3, 32, 32))
        self.assertTrue(torch.isfinite(output).all())
        self.assertIn(
            "backbone.vit.model.layer.0.attention.q_proj.weight",
            model.state_dict(),
        )
        self.assertEqual(model.backbone.out_indices, [1, 2, 3, 4])
        self.assertEqual(model.backbone.num_prefix_tokens, 5)

    @unittest.skipUnless(
        torch.cuda.is_available(), "CUDA fixture requires GPU"
    )
    def test_generated_model_cuda_fp16_forward(self):
        model = DINOv3UPerNet("dinov3_vits16", self.config).eval().cuda()
        model.load_state_dict(self.model.state_dict(), strict=True)
        classifier_dtypes = []
        handle = model.decode_head.classifier.register_forward_hook(
            lambda module, inputs, output: classifier_dtypes.append(
                output.dtype
            )
        )
        self.addCleanup(handle.remove)
        with torch.inference_mode(), torch.autocast(
            "cuda", dtype=torch.float16
        ):
            output = model(torch.zeros(1, 3, 32, 32, device="cuda"))
        self.assertEqual(output.shape, (1, 3, 32, 32))
        # CUDA autocast promotes the final bilinear interpolation to FP32.
        # Check the convolution, not the returned interpolated tensor.
        self.assertEqual(classifier_dtypes, [torch.float16])
        self.assertTrue(torch.isfinite(output).all())

    def test_incomplete_or_remote_config_is_not_guessed(self):
        for change in [
            {"rope_theta": None},
            {"auto_map": {"AutoModel": "remote.code"}},
        ]:
            config = dict(self.config)
            if "rope_theta" in change:
                del config["rope_theta"]
            else:
                config.update(change)
            with self.assertRaises(ValueError):
                DINOv3UPerNet("dinov3_vits16", config)

    def test_hashes_restricted_load_and_strict_state_dictionary(self):
        with tempfile.TemporaryDirectory() as tmp:
            ckpt, config = (
                Path(tmp) / "fixture.ckpt",
                Path(tmp) / "config.json",
            )
            config.write_text(json.dumps(self.config))
            state = {
                "model." + k: v for k, v in self.model.state_dict().items()
            }
            checkpoint = {
                "hyper_parameters": {
                    "model": "upernet",
                    "in_channels": 3,
                    "num_classes": 3,
                    "backbone": "dinov3_vits16",
                },
                "state_dict": state,
            }

            def load():
                torch.save(checkpoint, ckpt)
                return inference.load_model(
                    ckpt,
                    config,
                    hashlib.sha256(ckpt.read_bytes()).hexdigest(),
                    hashlib.sha256(config.read_bytes()).hexdigest(),
                    torch.device("cpu"),
                )

            with mock.patch.object(torch, "load", wraps=torch.load) as loader:
                model = load()
                self.assertTrue(loader.call_args.kwargs["weights_only"])
            self.assertFalse(model.training)
            self.assertTrue(
                all(not p.requires_grad for p in model.parameters())
            )
            del state["model.decode_head.classifier.bias"]
            with self.assertRaises(RuntimeError):
                load()
            checkpoint["hyper_parameters"]["num_classes"] = 4
            with self.assertRaises(ValueError):
                load()
            checkpoint["unapproved_pickle_type"] = Path("not-executed")
            with self.assertRaises(Exception) as error:
                load()
            self.assertIn("Weights only load failed", str(error.exception))

    def test_invalid_hashes_and_unsafe_torch_versions_fail_closed(self):
        for digest in (None, "", "a" * 64):
            with self.assertRaises(ValueError):
                inference.verify_sha256(
                    io.BytesIO(b"asset"), digest, "checkpoint"
                )
        for version in ("2.5.1", "2.6.0", "2.8.0+cu128", "2.9.1", "2.10.0rc1"):
            with self.subTest(version=version), mock.patch.object(
                torch, "__version__", version
            ), mock.patch.object(torch, "load") as load:
                with self.assertRaisesRegex(RuntimeError, r"torch>=2\.10\.0"):
                    inference.load_model("x", "y", "a" * 64, "b" * 64, "cpu")
                load.assert_not_called()

    def test_config_only_source_does_not_call_affected_transformers_apis(self):
        sources = [
            Path(CODE_DIR) / "bda" / "dinov3_upernet.py",
            Path(CODE_DIR).parents[2]
            / "validation"
            / "prepare_dinov3_asset.py",
        ]
        forbidden = {
            "save_pretrained",
            "AutoTokenizer",
            "AutoProcessor",
            "PreTrainedTokenizerBase",
            "ProcessorMixin",
        }
        for source in sources:
            syntax = ast.parse(source.read_text())
            called = {
                (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else node.func.id
                )
                for node in ast.walk(syntax)
                if isinstance(node, ast.Call)
                and isinstance(node.func, (ast.Attribute, ast.Name))
            }
            self.assertFalse(called & forbidden, str(source))


@unittest.skipUnless(
    os.getenv("HASTE_DINOV3_CHECKPOINT")
    and os.getenv("HASTE_DINOV3_BACKBONE_CONFIG")
    and os.getenv("HASTE_DINOV3_BACKBONE_CONFIG_SHA256"),
    "Real asset acceptance requires an authorized local config and its known SHA-256",
)
class RealAssetAcceptanceTest(unittest.TestCase):
    def test_real_checkpoint_strict_load_and_cuda_forward(self):
        if not torch.cuda.is_available():
            self.skipTest("CUDA required for real asset acceptance")
        model = inference.load_model(
            os.environ["HASTE_DINOV3_CHECKPOINT"],
            os.environ["HASTE_DINOV3_BACKBONE_CONFIG"],
            "d3c351c9822665359f78e835ece81d4ff518f8ceb736b5a815e1d72e2dc2c92f",  # pragma: allowlist secret
            os.environ["HASTE_DINOV3_BACKBONE_CONFIG_SHA256"],
            torch.device("cuda:0"),
        )
        with torch.inference_mode(), torch.autocast(
            "cuda", dtype=torch.float16
        ):
            output = model(torch.zeros(1, 3, 512, 512, device="cuda:0"))
        self.assertEqual(output.shape, (1, 3, 512, 512))
        self.assertTrue(torch.isfinite(output).all())


if __name__ == "__main__":
    unittest.main()
