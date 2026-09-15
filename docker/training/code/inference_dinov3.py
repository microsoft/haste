# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Offline, post-event RGB8 DINOv3 inference producing HASTE prediction COGs.

Adapted from microsoft/building-damage-assessment at
4d0d1925dc3a5a63566f047102f8dd474dbbcf80 (MIT). DINOv3 backbone assets retain
their separate Meta DINOv3 license; see bda/dinov3_upernet.py.

Reference classes 0/1/2/255 map to HASTE 1/2/3/0. The damaged class's
training grouping must be established by catalog provenance, not its filename.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import re
import tempfile
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from itertools import islice, product
from pathlib import Path

import numpy as np
import rasterio
import rasterio.shutil
import torch
import yaml
from bda.dinov3_upernet import DINOv3UPerNet
from packaging.version import Version
from rasterio.enums import ColorInterp, MaskFlags
from rasterio.windows import Window
from tqdm import tqdm

SOURCE_REVISION = (
    "4d0d1925dc3a5a63566f047102f8dd474dbbcf80"  # pragma: allowlist secret
)
# Algebraically (RGB / 255 - mean) / std, matching the reference, no clipping.
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32) * 255.0
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32) * 255.0


def verify_sha256(stream, expected, label):
    """Verify a local asset on the same file handle used to deserialize it."""
    if not isinstance(expected, str) or not re.fullmatch(
        "[0-9a-fA-F]{64}", expected
    ):
        raise ValueError(f"{label}_sha256 must be an explicit SHA-256 digest")
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    actual = digest.hexdigest()
    if not hmac.compare_digest(actual, expected.lower()):
        raise ValueError(f"{label} SHA-256 mismatch")
    stream.seek(0)
    return actual


def load_model(
    checkpoint_fn,
    backbone_config_fn,
    checkpoint_sha256,
    backbone_config_sha256,
    device,
):
    """No Lightning, Hub, remote code, key rewriting, or unsafe pickle fallback."""
    # CVE-2026-24747 / GHSA-63cw-57p8-fm3p affects even weights_only=True.
    # Hash verification and the older 2.6 security floor do not replace this.
    if Version(torch.__version__.split("+")[0]) < Version("2.10.0"):
        raise RuntimeError(
            "DINOv3 restricted checkpoint loading requires torch>=2.10.0 "
            "(CVE-2026-24747)"
        )
    with Path(backbone_config_fn).open("rb") as stream:
        verify_sha256(stream, backbone_config_sha256, "backbone_config")
        config = json.load(stream)
    if not isinstance(config, dict):
        raise ValueError("Backbone configuration must be a JSON object")
    with Path(checkpoint_fn).open("rb") as stream:
        verify_sha256(stream, checkpoint_sha256, "checkpoint")
        checkpoint = torch.load(stream, map_location="cpu", weights_only=True)
    hparams = checkpoint["hyper_parameters"]
    expected = {"model": "upernet", "in_channels": 3, "num_classes": 3}
    if any(hparams.get(key) != value for key, value in expected.items()):
        raise ValueError(
            "Expected a three-class, three-channel UPerNet checkpoint"
        )
    model = DINOv3UPerNet(backbone=hparams["backbone"], backbone_config=config)
    state = {
        key.removeprefix("model."): value
        for key, value in checkpoint["state_dict"].items()
        if key.startswith("model.")
    }
    model.load_state_dict(state, strict=True)
    return model.eval().requires_grad_(False).to(device)


def remap_classes(prediction, valid):
    """Keep valid background; reserve zero exclusively for missing observation."""
    if not np.isin(prediction, [0, 1, 2, 255]).all():
        raise ValueError("Unexpected DINOv3 class (expected 0, 1, 2, 255)")
    return np.where(
        valid & (prediction != 255), prediction.astype(np.uint16) + 1, 0
    ).astype(np.uint8)


def _reflect_indices(start: int, size: int, limit: int) -> np.ndarray:
    if limit == 1:
        return np.zeros(size, dtype=np.int64)
    period = 2 * (limit - 1)
    indices = np.arange(start, start + size) % period
    return np.minimum(indices, period - indices)


def read_patch(src, y: int, x: int, patch_size: int, padding: int):
    """Reflect image and per-band validity beyond edges, even for 1-pixel images."""
    top, left = y - padding, x - padding
    masked = not all(
        MaskFlags.all_valid in flags for flags in src.mask_flag_enums
    )
    if (
        top >= 0
        and left >= 0
        and top + patch_size <= src.height
        and left + patch_size <= src.width
    ):
        image = src.read(
            window=Window(left, top, patch_size, patch_size), masked=masked
        )
    else:
        rows = _reflect_indices(top, patch_size, src.height)
        cols = _reflect_indices(left, patch_size, src.width)
        y0, x0 = int(rows.min()), int(cols.min())
        y1, x1 = int(rows.max()) + 1, int(cols.max()) + 1
        image = src.read(
            window=Window(x0, y0, x1 - x0, y1 - y0), masked=masked
        )
        image = image[:, rows[:, None] - y0, cols[None, :] - x0]
    if not masked:
        return image, np.ones((patch_size, patch_size), dtype=bool)
    return image.filled(0), ~np.ma.getmaskarray(image).any(axis=0)


@contextmanager
def patch_batches(
    input_fn,
    coordinates,
    batch_size,
    patch_size,
    padding,
    device,
    num_workers=2,
    prefetch_factor=2,
):
    """Bounded, ordered prefetch with a separate GDAL handle per reader."""
    coordinates = iter(coordinates)

    def prepare(src, batch_coordinates):
        patches = [
            read_patch(src, y, x, patch_size, padding)
            for y, x in batch_coordinates
        ]
        images = np.stack([image for image, _ in patches]).astype(np.float32)
        images -= IMAGENET_MEAN[None, :, None, None]
        images /= IMAGENET_STD[None, :, None, None]
        images = torch.from_numpy(images).contiguous(
            memory_format=torch.channels_last
        )
        if device.type == "cuda" and num_workers:
            with torch.cuda.device(device):
                images = images.pin_memory()
        return images, [valid for _, valid in patches], batch_coordinates

    def read_batch(batch_coordinates):
        with rasterio.open(input_fn) as src:
            return prepare(src, batch_coordinates)

    def chunks():
        while batch := list(islice(coordinates, batch_size)):
            yield batch

    def prefetched(executor):
        batches = chunks()
        pending = deque(
            executor.submit(read_batch, batch)
            for batch in islice(batches, num_workers * prefetch_factor)
        )
        while pending:
            batch = pending.popleft().result()
            following = next(batches, None)
            if following is not None:
                pending.append(executor.submit(read_batch, following))
            yield batch

    if num_workers:
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            yield prefetched(executor)
    else:
        with rasterio.open(input_fn) as src:
            yield (prepare(src, batch) for batch in chunks())


def validate_source(src):
    if src.crs is None:
        raise ValueError("Input imagery must have a CRS")
    if (
        not all(math.isfinite(v) for v in (*src.transform, *src.bounds))
        or src.transform.determinant == 0
    ):
        raise ValueError("Input imagery has an invalid spatial transform")
    if src.count != 3 or src.dtypes != ("uint8",) * 3:
        raise ValueError("Expected an 8-bit, three-band RGB raster")
    if src.colorinterp != (
        ColorInterp.red,
        ColorInterp.green,
        ColorInterp.blue,
    ):
        raise ValueError("Expected bands in red, green, blue order")


@torch.inference_mode()
def run_inference(
    input_fn,
    checkpoint_fn,
    output_fn,
    backbone_config_fn,
    checkpoint_sha256,
    backbone_config_sha256,
    device="cuda:0",
    patch_size=512,
    padding=64,
    batch_size=8,
    overwrite=False,
    num_workers=2,
    prefetch_factor=2,
):
    """Reflect context, write each central core once, then create a categorical COG."""
    for name, value in {
        "patch_size": patch_size,
        "padding": padding,
        "batch_size": batch_size,
        "num_workers": num_workers,
        "prefetch_factor": prefetch_factor,
    }.items():
        if type(value) is not int:
            raise ValueError(f"{name} must be an integer")
    if patch_size < 32 or patch_size % 16:
        raise ValueError("patch_size must be a multiple of 16 and at least 32")
    if padding < 0 or 2 * padding >= patch_size:
        raise ValueError(
            "padding must be nonnegative and less than half patch_size"
        )
    if batch_size < 1 or num_workers < 0 or prefetch_factor < 1:
        raise ValueError("Invalid batch size, reader count or prefetch factor")
    input_fn, checkpoint_fn, output_fn, backbone_config_fn = map(
        Path, (input_fn, checkpoint_fn, output_fn, backbone_config_fn)
    )
    if output_fn.resolve() in (
        input_fn.resolve(),
        checkpoint_fn.resolve(),
        backbone_config_fn.resolve(),
    ):
        raise ValueError("Output must not overwrite an input asset")
    if output_fn.exists() and not overwrite:
        raise FileExistsError(f"{output_fn} already exists; use --overwrite")
    target_device = torch.device(device)
    if target_device.type not in ("cpu", "cuda"):
        raise ValueError("device must be cpu or cuda:<index>")
    if target_device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError(
            "Requested CUDA is unavailable; use --device cpu explicitly"
        )

    with rasterio.open(input_fn) as src:
        validate_source(src)
        model = load_model(
            checkpoint_fn,
            backbone_config_fn,
            checkpoint_sha256,
            backbone_config_sha256,
            target_device,
        )
        stride = patch_size - 2 * padding
        coordinates = product(
            range(0, src.height, stride), range(0, src.width, stride)
        )
        num_patches = math.ceil(src.height / stride) * math.ceil(
            src.width / stride
        )
        profile = {
            "driver": "GTiff",
            "width": src.width,
            "height": src.height,
            "crs": src.crs,
            "transform": src.transform,
            "count": 1,
            "dtype": "uint8",
            "nodata": 0,
            "compress": "lzw",
            "tiled": True,
            "blockxsize": 512,
            "blockysize": 512,
            "BIGTIFF": "IF_SAFER",
        }
        output_fn.parent.mkdir(parents=True, exist_ok=True)
        print(f"DINOv3 on {device}: {num_patches} patches", flush=True)
        print(f"Checkpoint SHA-256: {checkpoint_sha256}", flush=True)
        print(f"Backbone config SHA-256: {backbone_config_sha256}", flush=True)
        with tempfile.TemporaryDirectory(
            prefix=".dinov3-", dir=output_fn.parent
        ) as tmp:
            temporary_fn = Path(tmp) / "predictions.tif"
            cog_fn = Path(tmp) / "predictions_cog.tif"
            with rasterio.open(temporary_fn, "w", **profile) as dst:
                dst.set_band_description(1, "building_damage_class")
                dst.write_colormap(
                    1,
                    {
                        0: (0, 0, 0, 0),
                        1: (0, 0, 0, 255),
                        2: (0, 200, 0, 255),
                        3: (255, 0, 0, 255),
                    },
                )
                dst.update_tags(
                    ADAPTER="dinov3_upernet",
                    SOURCE_REVISION=SOURCE_REVISION,
                    CHECKPOINT_SHA256=checkpoint_sha256,
                    BACKBONE_CONFIG_SHA256=backbone_config_sha256,
                    CLASS_0="invalid",
                    CLASS_1="background",
                    CLASS_2="undamaged",
                    CLASS_3="damaged",
                    NORMALIZATION="ImageNet RGB8 mean/std; no clipping",
                )
                with patch_batches(
                    input_fn,
                    coordinates,
                    batch_size,
                    patch_size,
                    padding,
                    target_device,
                    num_workers,
                    prefetch_factor,
                ) as batches, tqdm(
                    total=num_patches, unit="patch"
                ) as progress:
                    for images, valid_masks, batch_coordinates in batches:
                        inputs = images.to(
                            target_device,
                            non_blocking=target_device.type == "cuda"
                            and num_workers > 0,
                        )
                        with torch.autocast(
                            device_type=target_device.type,
                            dtype=torch.float16,
                            enabled=target_device.type == "cuda",
                        ):
                            logits = model(inputs)
                        if logits.shape != (
                            len(batch_coordinates),
                            3,
                            patch_size,
                            patch_size,
                        ):
                            raise RuntimeError(
                                "Model produced an unexpected logit shape"
                            )
                        if not torch.isfinite(logits).all().item():
                            raise RuntimeError(
                                "Model produced non-finite predictions"
                            )
                        predictions = (
                            logits.argmax(1).to(torch.uint8).cpu().numpy()
                        )
                        for prediction, valid, (y, x) in zip(
                            predictions, valid_masks, batch_coordinates
                        ):
                            h, w = min(stride, src.height - y), min(
                                stride, src.width - x
                            )
                            core = np.s_[
                                padding : padding + h, padding : padding + w
                            ]
                            output = remap_classes(
                                prediction[core], valid[core]
                            )
                            dst.write(output, 1, window=Window(x, y, w, h))
                        progress.update(len(batch_coordinates))
            rasterio.shutil.copy(
                temporary_fn,
                cog_fn,
                driver="COG",
                compress="LZW",
                blocksize=512,
                BIGTIFF="IF_SAFER",
                overview_resampling="NEAREST",
                resampling="NEAREST",
            )
            if output_fn.exists() and not overwrite:
                raise FileExistsError(
                    f"{output_fn} was created during inference"
                )
            cog_fn.replace(output_fn)
    print(f"Saved {output_fn}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--device", help="Explicit override, e.g. cpu for validation"
    )
    args = parser.parse_args()
    with args.config.open() as stream:
        config = yaml.safe_load(stream)
    inference = config["inference"]
    if inference.get("adapter") != "dinov3_upernet":
        raise ValueError(
            "This entrypoint requires inference.adapter=dinov3_upernet"
        )
    filename = inference["predictions_filename"]
    if Path(filename).name != filename or not filename.endswith(
        "_predictions.tif"
    ):
        raise ValueError(
            "predictions_filename must be a basename ending _predictions.tif"
        )
    gpu_id = inference.get("gpu_id", 0)
    if type(gpu_id) is not int or gpu_id < 0:
        raise ValueError("gpu_id must be a nonnegative integer")
    experiment_dir = Path(config["experiment_dir"])
    run_inference(
        config["imagery"]["rgb_fn"],
        experiment_dir / inference["checkpoint_fn"],
        experiment_dir
        / inference.get("output_subdir", "inference")
        / filename,
        experiment_dir / inference["backbone_config_fn"],
        inference["checkpoint_sha256"],
        inference["backbone_config_sha256"],
        device=args.device or f"cuda:{gpu_id}",
        overwrite=args.overwrite,
        **{
            key: inference[key]
            for key in (
                "patch_size",
                "padding",
                "batch_size",
                "num_workers",
                "prefetch_factor",
            )
            if key in inference
        },
    )


if __name__ == "__main__":
    try:
        from hastegeo.core.utils.gdal_security import harden_gdal
    except ImportError:
        pass
    else:
        harden_gdal()
    main()
