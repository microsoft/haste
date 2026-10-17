# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Offline registered DINOv2-S/14 inference with HASTE classes 1/2/3/0.

The hash-verified checkpoint supplies its own backbone configuration.
Only the legacy three-class RGB UPerNet contract from
microsoft/building-damage-assessment at
958ff3d30601ffc3577da81af1ac0a545deb295e is supported.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import torch
import yaml
from bda.dinov2_upernet import (
    BACKBONE,
    BACKBONE_REVISION,
    SOURCE_REVISION,
    DINOv2UPerNet,
)
from inference_dinov3 import run_tiled_inference, verify_sha256
from packaging.version import Version


def load_model(
    checkpoint_fn: str | Path,
    checkpoint_sha256: str,
    device: str | torch.device,
) -> DINOv2UPerNet:
    if Version(torch.__version__.split("+")[0]) < Version("2.10.0"):
        raise RuntimeError(
            "DINOv2 restricted checkpoint loading requires torch>=2.10.0 "
            "(CVE-2026-24747)"
        )
    with Path(checkpoint_fn).open("rb") as stream:
        verify_sha256(stream, checkpoint_sha256, "checkpoint")
        checkpoint = torch.load(stream, map_location="cpu", weights_only=True)
    if not isinstance(checkpoint, dict):
        raise ValueError("Expected a Lightning checkpoint object")
    hparams = checkpoint.get("hyper_parameters")
    expected = {
        "model": "upernet",
        "backbone": BACKBONE,
        "in_channels": 3,
        "num_classes": 3,
        "ignore_index": 255,
        "backbone_revision": BACKBONE_REVISION,
    }
    if not isinstance(hparams, dict) or any(
        type(hparams.get(key)) is not type(value) or hparams[key] != value
        for key, value in expected.items()
    ):
        raise ValueError("Unsupported DINOv2 checkpoint architecture")
    if (
        hparams.get("decoder_variant", "legacy") != "legacy"
        or hparams.get("refinement_channels", 32) != 32
    ):
        raise ValueError("Only the legacy DINOv2 decoder is supported")
    state_dict = checkpoint.get("state_dict")
    if not isinstance(state_dict, dict) or not all(
        isinstance(key, str) and isinstance(value, torch.Tensor)
        for key, value in state_dict.items()
    ):
        raise ValueError("Expected a tensor state dictionary")
    model = DINOv2UPerNet(BACKBONE, hparams.get("backbone_config"))
    state = {
        key.removeprefix("model."): value
        for key, value in state_dict.items()
        if key.startswith("model.")
    }
    model.load_state_dict(state, strict=True)
    return model.eval().requires_grad_(False).to(device)


def run_inference(
    input_fn: str | Path,
    checkpoint_fn: str | Path,
    output_fn: str | Path,
    checkpoint_sha256: str,
    device: str = "cuda:0",
    patch_size: int = 512,
    padding: int = 64,
    batch_size: int = 8,
    overwrite: bool = False,
    num_workers: int = 2,
    prefetch_factor: int = 2,
) -> None:
    run_tiled_inference(
        input_fn,
        output_fn,
        lambda target: load_model(checkpoint_fn, checkpoint_sha256, target),
        (checkpoint_fn,),
        {
            "ADAPTER": "dinov2_upernet",
            "SOURCE_REVISION": SOURCE_REVISION,
            "CHECKPOINT_SHA256": checkpoint_sha256,
            "BACKBONE": BACKBONE,
            "BACKBONE_REVISION": BACKBONE_REVISION,
            "BACKBONE_CONFIG_SOURCE": "checkpoint.hyper_parameters",
            "SPATIAL_PREPROCESSING": "reflect_bottom_right_to_multiple_of_14",
        },
        device=device,
        patch_size=patch_size,
        padding=padding,
        batch_size=batch_size,
        overwrite=overwrite,
        num_workers=num_workers,
        prefetch_factor=prefetch_factor,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--device", help="Explicit override, e.g. cpu")
    args = parser.parse_args()
    with args.config.open() as stream:
        config = yaml.safe_load(stream)
    inference = config["inference"]
    if inference.get("adapter") != "dinov2_upernet":
        raise ValueError(
            "This entrypoint requires inference.adapter=dinov2_upernet"
        )
    if any(
        inference.get(key) is not None
        for key in ("backbone_config_fn", "backbone_config_sha256")
    ):
        raise ValueError("DINOv2 uses only the checkpoint's embedded config")
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
        inference["checkpoint_sha256"],
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
    from hastegeo.core.utils.gdal_security import harden_gdal

    harden_gdal()
    main()
