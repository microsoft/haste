# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Opt-in actual-checkpoint CPU/GPU parity against the pinned PR18 source.

Set HASTE_DINOV2_REFERENCE_ACCEPTANCE=1 and HASTE_DINOV2_ASSET_DIR to the
authorized local assets, including reference/ from SOURCE_REVISION. No test
downloads assets or executes training infrastructure. Run with networking off.
"""

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import rasterio
import torch
import transformers
import yaml
from rasterio.enums import Resampling

CODE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_DIR))

import inference_dinov2 as runtime  # noqa: E402
from bda.dinov2_upernet import SOURCE_REVISION  # noqa: E402
from tests.test_real_dinov3_reference import write_fixture  # noqa: E402

MANIFEST_SHA256 = "cbe9a4baec53e8a4f40fd27e5aacddb659836a1828dee3f0fe605adf1ad2d250"  # pragma: allowlist secret
REFERENCE_HASHES = {
    "bda/dino_upernet.py": "b365b82c30fcac824f099f74ed5733ced8d29d1709ca30f55ca51ca00d585a4a",  # pragma: allowlist secret
    "bda/dinov3_upernet.py": "b5c401a7650f7f50d35522c5ae3a45ed171f9e8c9d702648409ed913018c57d6",  # pragma: allowlist secret
    "bda/model_factory.py": "e55f91c89f50d2bd95caff0aca80a31f210766a4d79c073febdd517c8fe9da84",  # pragma: allowlist secret
    "inference_dino.py": "465f6008614b5c271cd5bf67d9f441920f28b153bc95f2c09db9a8b66ba93ed5",  # pragma: allowlist secret
    "inference_dinov3.py": "38a610b4ad3083ab718aa4011c1c6ebacaabafc05d3ba0f0a7c510ed1adc02b5",  # pragma: allowlist secret
    "xview2_any.json": "358f38f3ffb862fd5e971ec79a8a869ee632432be76f2b452a6262960976c51c",  # pragma: allowlist secret
    "checkpoints.json": "1455bc523d60e88de5571010c5ac8d811f05ac838b96810c20351d38edaea535",  # pragma: allowlist secret
}

# A fresh isolated interpreter prevents the reference's legacy module names
# from binding to production modules. It runs the unmodified reference loader,
# reader and tiling path, after verifying the checkpoint and source files.
REFERENCE_WORKER = """
import hashlib, json, pathlib, sys, torch
root, checkpoint, digest, image, output, hashes = sys.argv[1:]
root = pathlib.Path(root)
for name, expected in json.loads(hashes).items():
    assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
with open(checkpoint, "rb") as stream:
    actual = hashlib.sha256()
    for block in iter(lambda: stream.read(1048576), b""):
        actual.update(block)
    assert actual.hexdigest() == digest
torch.set_num_threads(2)
sys.path.insert(0, str(root))
from inference_dino import run_inference
run_inference(
    pathlib.Path(image), pathlib.Path(checkpoint), pathlib.Path(output),
    device="cuda:0", patch_size=512, padding=64, batch_size=8,
    num_workers=2, prefetch_factor=2, overwrite=True,
)
"""


@unittest.skipUnless(
    os.getenv("HASTE_DINOV2_REFERENCE_ACCEPTANCE") == "1",
    "Requires six authorized checkpoints, pinned reference source and GPU",
)
class RealReferenceTest(unittest.TestCase):
    def test_six_checkpoints_and_reference_tiled_cog_parity(self) -> None:
        self.assertTrue(torch.cuda.is_available(), "CUDA acceptance required")
        directory = Path(os.environ["HASTE_DINOV2_ASSET_DIR"])
        reference = directory / "reference"
        for name, expected in REFERENCE_HASHES.items():
            self.assertEqual(
                hashlib.sha256((reference / name).read_bytes()).hexdigest(),
                expected,
                name,
            )
        with (directory / "manifest.json").open("rb") as stream:
            runtime.verify_sha256(stream, MANIFEST_SHA256, "manifest")
            manifest = json.load(stream)
        config = json.loads((reference / "xview2_any.json").read_text())
        catalog = json.loads((reference / "checkpoints.json").read_text())
        self.assertEqual(len(manifest["checkpoints"]), 6)
        self.assertEqual(
            [
                (item["relative_path"], item["sha256"], item["bytes"])
                for item in manifest["checkpoints"]
            ],
            [
                (item["path"], item["sha256"], item["bytes"])
                for item in catalog["checkpoints"]
            ],
        )
        spec = importlib.util.spec_from_file_location(
            "verified_dinov2_reference", reference / "bda/dino_upernet.py"
        )
        reference_model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reference_model)
        report = {
            "sourceRevision": SOURCE_REVISION,
            "referenceHashes": REFERENCE_HASHES,
            "manifestSha256": MANIFEST_SHA256,
            "torch": str(torch.__version__),
            "transformers": transformers.__version__,
            "gpu": torch.cuda.get_device_name(0),
            "comparison": "Unmodified pinned model; same offline runtime",
            "checkpoints": [],
            "rasters": [],
        }
        old_threads = torch.get_num_threads()
        torch.set_num_threads(2)
        self.addCleanup(torch.set_num_threads, old_threads)
        with (
            mock.patch.object(
                transformers.AutoConfig,
                "from_pretrained",
                side_effect=AssertionError("Hub configuration lookup"),
            ),
            mock.patch.object(
                transformers.AutoModel,
                "from_pretrained",
                side_effect=AssertionError("Hub weight download"),
            ),
            torch.inference_mode(),
        ):
            for item in manifest["checkpoints"]:
                path = directory / item["relative_path"]
                self.assertEqual(path.stat().st_size, item["bytes"])
                with path.open("rb") as stream:
                    runtime.verify_sha256(stream, item["sha256"], "checkpoint")
                    checkpoint = torch.load(
                        stream, map_location="cpu", weights_only=True
                    )
                hparams = checkpoint["hyper_parameters"]
                self.assertEqual(
                    hparams["backbone_config"],
                    config["model"]["backbone_config"],
                )
                self.assertEqual(
                    hparams["backbone_revision"],
                    config["model"]["backbone_revision"],
                )
                current = runtime.load_model(path, item["sha256"], "cpu")
                original = (
                    reference_model.DINOv2UPerNet(
                        pretrained=False,
                        backbone=hparams["backbone"],
                        backbone_config=hparams["backbone_config"],
                        backbone_revision=hparams["backbone_revision"],
                    )
                    .eval()
                    .requires_grad_(False)
                )
                original.load_state_dict(
                    {
                        key.removeprefix("model."): value
                        for key, value in checkpoint["state_dict"].items()
                        if key.startswith("model.")
                    },
                    strict=True,
                )
                del checkpoint
                current_state = current.state_dict()
                original_state = original.state_dict()
                self.assertEqual(list(current_state), list(original_state))
                self.assertEqual(len(current_state), 270)
                for name in current_state:
                    torch.testing.assert_close(
                        current_state[name],
                        original_state[name],
                        rtol=0,
                        atol=0,
                    )
                del current_state, original_state
                evidence = {
                    "path": item["relative_path"],
                    "sha256": item["sha256"],
                }
                for device, height, width in (
                    ("cpu", 32, 48),
                    ("cuda:0", 512, 512),
                ):
                    current.to(device)
                    original.to(device)
                    image = (
                        torch.linspace(
                            -2.1,
                            2.6,
                            3 * height * width,
                            device=device,
                        )
                        .reshape(1, 3, height, width)
                        .contiguous(memory_format=torch.channels_last)
                    )
                    with torch.autocast(
                        device_type=torch.device(device).type,
                        dtype=torch.float16,
                        enabled=device != "cpu",
                    ):
                        logits = current(image)
                        expected = original(image)
                    self.assertEqual(logits.shape, (1, 3, height, width))
                    self.assertTrue(torch.isfinite(logits).all())
                    torch.testing.assert_close(
                        logits, expected, rtol=0, atol=0
                    )
                    evidence[device] = {
                        "shape": list(logits.shape),
                        "maxAbsoluteLogitError": (logits - expected)
                        .abs()
                        .max()
                        .item(),
                        "classMismatchPixels": (
                            logits.argmax(1) != expected.argmax(1)
                        )
                        .sum()
                        .item(),
                    }
                report["checkpoints"].append(evidence)
                del current, original, logits, expected, image

        output_dir = os.getenv("HASTE_DINOV2_ACCEPTANCE_OUTPUT_DIR")
        if output_dir:
            output_root = Path(output_dir)
            output_root.mkdir(parents=True, exist_ok=True)
        else:
            temporary = tempfile.TemporaryDirectory()
            self.addCleanup(temporary.cleanup)
            output_root = Path(temporary.name)
        item = manifest["checkpoints"][0]
        checkpoint = directory / item["relative_path"]
        for height, width in ((769, 777), (1, 7)):
            fixture = output_root / f"rgb_{height}x{width}.tif"
            valid = write_fixture(fixture, height, width)
            output = output_root / f"rgb_{height}x{width}_predictions.tif"
            reference_output = output_root / f"reference_{height}x{width}.tif"
            subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    REFERENCE_WORKER,
                    str(reference),
                    str(checkpoint),
                    item["sha256"],
                    str(fixture),
                    str(reference_output),
                    json.dumps(REFERENCE_HASHES),
                ],
                check=True,
                timeout=180,
            )
            configuration = {
                "experiment_dir": str(output_root),
                "imagery": {"rgb_fn": str(fixture)},
                "inference": {
                    "adapter": "dinov2_upernet",
                    "checkpoint_fn": str(checkpoint),
                    "checkpoint_sha256": item["sha256"],
                    "predictions_filename": output.name,
                    "output_subdir": ".",
                },
            }
            config_path = output_root / "config.yml"
            config_path.write_text(yaml.safe_dump(configuration))
            subprocess.run(
                [
                    sys.executable,
                    str(CODE_DIR / "inference_dinov2.py"),
                    "--config",
                    str(config_path),
                    "--overwrite",
                ],
                check=True,
                timeout=180,
            )
            if height > 512:
                with rasterio.open(reference_output, "r+") as expected_raster:
                    expected_raster.build_overviews([2], Resampling.nearest)
            with (
                rasterio.open(fixture) as src,
                rasterio.open(output) as dst,
                rasterio.open(reference_output) as reference_raster,
            ):
                reference_pixels = reference_raster.read(1)
                expected = np.where(
                    reference_pixels == 255,
                    0,
                    reference_pixels.astype(np.uint16) + 1,
                ).astype(np.uint8)
                np.testing.assert_array_equal(dst.read(1), expected)
                np.testing.assert_array_equal(dst.read_masks(1), valid)
                self.assertEqual(dst.crs, src.crs)
                self.assertEqual(dst.transform, src.transform)
                self.assertEqual(dst.bounds, src.bounds)
                self.assertEqual(dst.nodata, 0)
                self.assertEqual(
                    dst.tags(ns="IMAGE_STRUCTURE")["LAYOUT"], "COG"
                )
                if height > 512:
                    self.assertTrue(dst.overviews(1))
                    # Odd-sized overview grids use GDAL's overview decimation,
                    # not RasterIO's arbitrary output-shape sampling grid.
                    raw_nearest = reference_raster.read(
                        1,
                        out_shape=((height + 1) // 2, (width + 1) // 2),
                        resampling=Resampling.nearest,
                    )
                    overview_expected = np.where(
                        raw_nearest == 255,
                        0,
                        raw_nearest.astype(np.uint16) + 1,
                    ).astype(np.uint8)
                    np.testing.assert_array_equal(
                        dst.read(
                            1,
                            out_shape=raw_nearest.shape,
                            resampling=Resampling.nearest,
                        ),
                        overview_expected,
                    )
                report["rasters"].append(
                    {
                        "shape": [height, width],
                        "classMismatchPixels": 0,
                        "maskMismatchPixels": 0,
                        "classes": np.unique(dst.read(1)).tolist(),
                        "overviews": dst.overviews(1),
                    }
                )
        (output_root / "acceptance.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    unittest.main()
