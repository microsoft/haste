# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Opt-in, actual-checkpoint GPU parity against hash-pinned original code.

Only AutoConfig's Hub lookup is redirected to the authorized official JSON.
Neither classifier, loader, model layers nor tiling calculations are faked.
Reference training infrastructure is never imported.
"""

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from itertools import product
from pathlib import Path
from unittest import mock

import numpy as np
import rasterio
import rasterio.shutil
import torch
import transformers
from rasterio.enums import ColorInterp
from rasterio.transform import from_origin
from transformers import DINOv3ViTConfig

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "docker" / "training" / "code"))
sys.path.insert(0, str(ROOT / "validation"))

import inference_dinov3 as runtime  # noqa: E402
import prepare_dinov3_asset as assets  # noqa: E402


def import_verified_reference(name, path, expected_sha):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha:
        raise ValueError("Reference source differs from the pinned version")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_fixture(path, height, width):
    y, x = np.indices((height, width))
    image = np.stack(
        [
            ((x // 8 * 17 + y // 8 * 3) % 200 + 30),
            ((x // 8 * 5 + y // 8 * 11) % 200 + 30),
            ((x // 8 * 13 + y // 8 * 7) % 200 + 30),
        ]
    ).astype(np.uint8)
    valid = np.full((height, width), 255, dtype=np.uint8)
    if height > 384:
        valid[373:399, 360:407] = 0  # spans two central-core seams
        valid[:7, :13] = 0
        valid[-9:, -17:] = 0
    else:
        valid[0, 0] = 0
    with rasterio.open(
        path,
        "w",
        driver="COG",
        width=width,
        height=height,
        count=3,
        dtype="uint8",
        crs="EPSG:32610",
        transform=from_origin(500000, 4200000, 0.5, 0.5),
        compress="LZW",
        blocksize=512,
        overview_resampling="NEAREST",
    ) as dst:
        dst.colorinterp = (
            ColorInterp.red,
            ColorInterp.green,
            ColorInterp.blue,
        )
        dst.write(image)
        dst.write_mask(valid)
    return valid


@unittest.skipUnless(
    os.getenv("HASTE_DINOV3_REFERENCE_ACCEPTANCE") == "1",
    "Opt-in comparison requires real checkpoint, authorized config and GPU",
)
class RealReferenceParityTest(unittest.TestCase):
    def test_actual_checkpoint_matches_reference_model_and_tiling(self):
        self.assertTrue(torch.cuda.is_available(), "CUDA is required")
        directory = assets.asset_directory()
        config = Path(os.environ["HASTE_DINOV3_BACKBONE_CONFIG"])
        config_sha = os.environ["HASTE_DINOV3_BACKBONE_CONFIG_SHA256"]
        official = config.parent / "config.json"
        source_record, _ = assets.read_json_asset(
            config.parent / "config.provenance.json"
        )
        official_json, official_sha = assets.read_json_asset(official)
        self.assertEqual(official_sha, source_record["officialConfigSha256"])
        checkpoint = Path(os.environ["HASTE_DINOV3_CHECKPOINT"])
        evidence = assets.inspect_checkpoint(checkpoint)
        reference = directory / "reference" / assets.SOURCE_REVISION
        ref_model = import_verified_reference(
            "pinned_dinov3_model",
            reference / "bda/dinov3_upernet.py",
            assets.REFERENCE_HASHES["bda/dinov3_upernet.py"],
        )
        with mock.patch.dict(sys.modules, {"bda.dinov3_upernet": ref_model}):
            ref_runtime = import_verified_reference(
                "pinned_dinov3_inference",
                reference / "inference_dinov3.py",
                assets.REFERENCE_HASHES["inference_dinov3.py"],
            )

        def official_lookup(name, *args, **kwargs):
            self.assertEqual(name, assets.BACKBONE_REPOSITORY)
            return DINOv3ViTConfig.from_dict(official_json)

        report = {
            "status": "validated",
            "checkpointSha256": evidence["sha256"],
            "backboneConfigSha256": config_sha,
            "officialConfigSha256": official_sha,
            "huggingFaceRevision": source_record["revision"],
            "sourceRevision": assets.SOURCE_REVISION,
            "referenceSourceHashes": {
                name: assets.REFERENCE_HASHES[name]
                for name in ("inference_dinov3.py", "bda/dinov3_upernet.py")
            },
            "comparisonMethod": (
                "Unmodified pinned runtime/model; only AutoConfig Hub lookup "
                "redirected to hash-verified official local JSON. Actual "
                "checkpoint strictly loaded by each implementation."
            ),
            "device": "cuda:0",
            "gpu": torch.cuda.get_device_name(0),
            "torchVersion": str(torch.__version__),
            "transformersVersion": transformers.__version__,
            "patchSize": 512,
            "padding": 64,
            "batchSize": 8,
            "numWorkers": 2,
            "prefetchFactor": 2,
            "fixtures": [],
        }
        if os.getenv("HASTE_DINOV3_TEST_IMAGE_ID"):
            report["container"] = {
                "imageId": os.environ["HASTE_DINOV3_TEST_IMAGE_ID"],
                "pythonVersion": sys.version.split()[0],
                "visibleCudaDevices": torch.cuda.device_count(),
            }
            self.assertEqual(torch.cuda.device_count(), 1)
        # Retain older-stack evidence rather than overwriting it after a
        # security-driven dependency change. A nested writable output mount
        # permits hermetic acceptance with all source/input assets read-only.
        output_root = Path(
            os.environ.get("HASTE_DINOV3_ACCEPTANCE_OUTPUT_DIR", directory)
        )
        if not output_root.resolve().is_relative_to(directory.resolve()):
            raise ValueError(
                "Acceptance output must stay inside pretrained-assets"
            )
        torch_release = str(torch.__version__).split("+")[0]
        output_dir = (
            output_root / "reference-acceptance" / f"torch-{torch_release}"
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        with mock.patch.object(
            transformers.AutoConfig,
            "from_pretrained",
            side_effect=official_lookup,
        ), mock.patch(
            "socket.socket.connect", side_effect=AssertionError("network")
        ):
            target = torch.device("cuda:0")
            model = runtime.load_model(
                checkpoint, config, assets.SHA256, config_sha, target
            )
            original = ref_runtime.load_model(checkpoint, target)
            current_state = model.state_dict()
            original_state = original.state_dict()
            self.assertEqual(list(current_state), list(original_state))
            for key in current_state:
                torch.testing.assert_close(
                    current_state[key], original_state[key], rtol=0, atol=0
                )
            report["identicalModelTensors"] = len(current_state)
            for height, width in [(769, 777), (1, 7)]:
                fixture = output_dir / f"rgb_{height}x{width}.tif"
                valid = write_fixture(fixture, height, width)
                parameters = (
                    fixture,
                    product(range(0, height, 384), range(0, width, 384)),
                    8,
                    512,
                    64,
                    target,
                    2,
                    2,
                )
                other_parameters = (
                    fixture,
                    product(range(0, height, 384), range(0, width, 384)),
                    8,
                    512,
                    64,
                    target,
                    2,
                    2,
                )
                max_delta = 0.0
                patch_count = 0
                with runtime.patch_batches(*parameters) as current_batches:
                    with ref_runtime.patch_batches(
                        *other_parameters
                    ) as original_batches:
                        for a, b in zip(
                            current_batches, original_batches, strict=True
                        ):
                            images, masks, coordinates = a
                            self.assertTrue(torch.equal(images, b[0]))
                            self.assertEqual(coordinates, b[2])
                            for first, second in zip(masks, b[1], strict=True):
                                np.testing.assert_array_equal(first, second)
                            inputs = images.to(target)
                            with torch.inference_mode(), torch.autocast(
                                "cuda", dtype=torch.float16
                            ):
                                logits = model(inputs)
                                expected_logits = original(inputs)
                            self.assertTrue(torch.isfinite(logits).all())
                            torch.testing.assert_close(
                                logits, expected_logits, rtol=0, atol=0
                            )
                            max_delta = max(
                                max_delta,
                                (logits - expected_logits).abs().max().item(),
                            )
                            patch_count += len(coordinates)
                prediction = (
                    output_dir / f"rgb_{height}x{width}_predictions.tif"
                )
                runtime.run_inference(
                    fixture,
                    checkpoint,
                    prediction,
                    config,
                    assets.SHA256,
                    config_sha,
                    overwrite=True,
                )
                with tempfile.TemporaryDirectory(dir=output_dir) as tmp:
                    reference_prediction = Path(tmp) / "reference_raw.tif"
                    ref_runtime.run_inference(
                        fixture,
                        checkpoint,
                        reference_prediction,
                        overwrite=True,
                    )
                    with rasterio.open(reference_prediction) as src:
                        reference_classes = src.read(1)
                    rasterio.shutil.copy(
                        reference_prediction,
                        output_dir / f"rgb_{height}x{width}_reference.tif",
                        driver="COG",
                        compress="LZW",
                        overview_resampling="NEAREST",
                    )
                expected = runtime.remap_classes(
                    reference_classes, reference_classes != 255
                )
                with rasterio.open(prediction) as src, rasterio.open(
                    fixture
                ) as rgb:
                    actual = src.read(1)
                    np.testing.assert_array_equal(actual, expected)
                    np.testing.assert_array_equal(src.read_masks(1), valid)
                    self.assertEqual(src.crs, rgb.crs)
                    self.assertEqual(src.transform, rgb.transform)
                    self.assertEqual(src.bounds, rgb.bounds)
                    self.assertEqual(src.res, rgb.res)
                    self.assertEqual(src.nodata, 0)
                    self.assertEqual(
                        src.tags(ns="IMAGE_STRUCTURE")["LAYOUT"], "COG"
                    )
                    if height > 512:
                        self.assertTrue(src.overviews(1))
                values, counts = np.unique(actual, return_counts=True)
                report["fixtures"].append(
                    {
                        "shape": [height, width],
                        "patches": patch_count,
                        "modelLogitMaxAbsoluteDifference": max_delta,
                        "predictionPixelDifferences": int(
                            np.count_nonzero(actual != expected)
                        ),
                        "maskPixelDifferences": int(
                            np.count_nonzero((actual != 0) != (valid != 0))
                        ),
                        "classCounts": {
                            str(k): int(v) for k, v in zip(values, counts)
                        },
                        "predictionGridSha256": hashlib.sha256(
                            actual.tobytes()
                        ).hexdigest(),
                        "crsTransformBoundsResolutionPreserved": True,
                    }
                )
        assets.write_recipe(
            output_root
            / f"reference-parity-torch-{torch_release}-report.json",
            report,
            directory,
        )
        print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
