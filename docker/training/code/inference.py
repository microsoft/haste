# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Script for running inference on a satellite image with a torchgeo segmentation model."""

import argparse
import contextlib
import math
import os
import time
from typing import Optional

import numpy as np
import rasterio
import torch
import tqdm
from bda.config import get_args
from bda.datasets import TileDataset, stack_samples
from bda.preprocess import Preprocessor
from bda.samplers import GridGeoSampler
from bda.trainers import CustomSemanticSegmentationTask, maybe_channels_last
from rasterio.enums import ColorInterp
from torch.utils.data import DataLoader


def add_inference_parser(
    parser: argparse.ArgumentParser,
) -> argparse.ArgumentParser:
    """Adds the arguments for the inference.py script to the base parser."""
    parser.add_argument(
        "--inference.checkpoint_fn",
        type=str,
        help="Model checkpoint to load, defaults to `last.ckpt` in the training checkpoints directory",
    )
    parser.add_argument(
        "--inference.output_subdir",
        type=str,
        help="Subdirectory to save outputs in, defaults to `outputs/` in the experiment directory",
    )
    parser.add_argument("--inference.gpu_id", type=int, help="GPU id to use")
    parser.add_argument(
        "--inference.patch_size",
        type=int,
        help="Size of patch to use for inference",
    )
    parser.add_argument("--inference.batch_size", type=int, help="Batch size")
    parser.add_argument(
        "--imagery.raw_fn",
        type=str,
        help="Path to the input raster (.tif or .vrt)",
    )
    parser.add_argument(
        "--inference.padding",
        type=int,
        help="Number of pixels to throw away from each side of the patch after inference",
    )  # TODO: better description
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrites the outputs if they exist",
    )
    # NOTE: we don't include some flags like `--imagery.normalization_means` or
    # `--imagery.normalization_stds` here because we assume that you won't want to
    # change them

    return parser


def inference_autocast_dtype(
    device: torch.device, cuda
) -> Optional[torch.dtype]:
    """Return the autocast dtype for the inference forward pass, if any.

    Inference is a pure forward pass whose output is an argmax, so bf16
    activations change the predicted class on vanishingly few pixels while
    roughly halving the memory traffic of every convolution. bf16 needs
    Ampere or later: HASTE's Batch pools are not homogeneous (T4s are Turing
    and have no bf16 tensor cores), so ask the device rather than assuming.
    Like ``bda.config.select_precision``, this asks for *native* support
    (``including_emulation=False``); the default ``is_bf16_supported()`` is
    also true for emulated bf16 on a T4.

    Args:
        device: The device inference will run on.
        cuda: The ``torch.cuda`` module, passed in so the Turing and Ampere
            branches can be tested without that hardware.

    Returns:
        ``torch.bfloat16`` on a CUDA device with native bf16 support,
        otherwise ``None`` (keep fp32: CPU and pre-Ampere GPUs behave as
        before).
    """
    if device.type != "cuda":
        return None
    if cuda.get_device_capability(device)[0] < 8:
        return None
    if not cuda.is_bf16_supported(including_emulation=False):
        return None
    return torch.bfloat16


def main() -> None:
    """Main function for the inference.py script."""
    args = get_args(description=__doc__, add_extra_parser=add_inference_parser)

    input_model_checkpoint = os.path.join(
        args["experiment_dir"], args["inference"]["checkpoint_fn"]
    )
    print(input_model_checkpoint)
    input_image_fn = args["imagery"]["raw_fn"]
    print("Running on image:", input_image_fn)
    patch_size = args["inference"]["patch_size"]
    padding = args["inference"]["padding"]
    output_dir = os.path.join(
        args["experiment_dir"], args["inference"]["output_subdir"]
    )

    # Sanity checks
    assert os.path.exists(input_model_checkpoint)
    assert input_model_checkpoint.endswith(".ckpt")
    assert os.path.exists(input_image_fn)
    assert input_image_fn.endswith(".tif") or input_image_fn.endswith(".vrt")
    assert int(math.log(patch_size, 2)) == math.log(patch_size, 2)

    image_name = os.path.basename(input_image_fn).replace(".tif", "")
    output_fn = os.path.join(output_dir, f"{image_name}_predictions.tif")
    if os.path.exists(output_fn) and not args["overwrite"]:
        print(
            "Experiment output files already exist, use --overwrite to overwrite them."
            + " Exiting."
        )
        return
    os.makedirs(output_dir, exist_ok=True)

    device = torch.device(
        f"cuda:{args['inference']['gpu_id']}"
        if torch.cuda.is_available()
        else "cpu"
    )

    # Load task and data
    tic = time.time()
    task = CustomSemanticSegmentationTask.load_from_checkpoint(
        input_model_checkpoint, map_location="cpu"
    )
    task.freeze()
    model = task.model
    model = model.eval().to(device)
    # Fixed patch size: let cuDNN benchmark its convolution algorithms once.
    torch.backends.cudnn.benchmark = True
    use_cuda = device.type == "cuda"
    # On CUDA, NHWC weights and inputs keep the convolutions on tensor cores
    # without layout transposes; CPU weights stay NCHW.
    model = maybe_channels_last(model, use_cuda)
    autocast_dtype = inference_autocast_dtype(device, torch.cuda)
    if autocast_dtype is not None:
        print(f"Running the forward pass under {autocast_dtype} autocast")

    preprocess = Preprocessor(
        training_mode=False,
        means=args["imagery"]["normalization_means"],
        stds=args["imagery"]["normalization_stds"],
    )

    with rasterio.open(input_image_fn) as f:
        input_height, input_width = f.shape
        profile = f.profile

    print(f"Input size: {input_height} x {input_width}")
    patch_size_w = (
        int(input_width / 32) * 32 if patch_size > input_width else patch_size
    )

    patch_size_h = (
        int(input_height / 32) * 32
        if patch_size > input_height
        else patch_size
    )

    patch_size = min(patch_size_w, patch_size_h)
    print(f"Patch size used: {patch_size}")
    # Also adjust the padding so that stride is always positive
    padding = min(int(patch_size / 2) - 1, padding)
    print(f"Padding used: {padding}")
    stride = patch_size - padding * 2

    # Clip to the channel count the checkpoint was trained on -- rasters often
    # carry an extra alpha band that would otherwise mismatch `in_channels`.
    dataset = TileDataset(
        [[input_image_fn]],
        mask_fns=None,
        transforms=preprocess,
        num_channels=args["imagery"].get("num_channels"),
    )
    sampler = GridGeoSampler(
        [[input_image_fn]], [0], patch_size=patch_size, stride=stride
    )
    dataloader = DataLoader(
        dataset,
        sampler=sampler,
        batch_size=args["inference"]["batch_size"],
        num_workers=12,
        collate_fn=stack_samples,
        # Pinned host buffers make the non-blocking copies below asynchronous.
        pin_memory=use_cuda,
    )

    # A constraint-loss model has one fewer output channel ("No Damage" gets
    # none) and leaves channel 0 unsupervised, so its argmax needs handling.
    use_constraint_loss = args["training"]["use_constraint_loss"]
    if use_constraint_loss:
        print(
            "Checkpoint was trained with the constraint loss: excluding the"
            " unsupervised channel 0 from predictions."
        )

    # Run inference
    tic = time.time()

    output = np.zeros((input_height, input_width), dtype=np.uint8)

    # NOTE: we can make output quiet by adding a flag to set `dl_enumerator = dataloader`
    dl_enumerator = tqdm.tqdm(dataloader)

    for batch in dl_enumerator:
        images = batch["image"].to(device, non_blocking=True)
        if use_cuda:
            images = images.contiguous(memory_format=torch.channels_last)
        x_coords = batch["x"]
        y_coords = batch["y"]
        batch_size = images.shape[0]
        autocast = (
            torch.autocast(device_type=device.type, dtype=autocast_dtype)
            if autocast_dtype is not None
            else contextlib.nullcontext()
        )
        with torch.inference_mode(), autocast:
            predictions = task(images)
            if use_constraint_loss:
                # Channel 0 ("Unlabeled") is emitted but never supervised
                # under the constraint loss, so its logits are meaningless
                # and it must not be allowed to win. Drop it and shift the
                # indices back onto the 1-based mask values. "No Damage" has
                # no channel at all, so it can't be predicted either.
                predictions = predictions[:, 1:].argmax(axis=1) + 1
            else:
                predictions = predictions.argmax(axis=1)
            predictions = predictions.cpu().numpy().astype(np.uint8)

        for i in range(batch_size):
            height, width = predictions[i].shape
            y = int(y_coords[i])
            x = int(x_coords[i])
            output[
                y + padding : y + height - padding,
                x + padding : x + width - padding,
            ] = predictions[i][padding:-padding, padding:-padding]

    print(f"Finished running model in {time.time()-tic:0.2f} seconds")

    # Save predictions
    tic = time.time()
    profile["driver"] = "GTiff"
    profile["count"] = 1
    profile["dtype"] = "uint8"
    profile["compress"] = "lzw"
    profile["predictor"] = 2
    profile["nodata"] = 0
    profile["blockxsize"] = 512
    profile["blockysize"] = 512
    profile["tiled"] = True
    profile["interleave"] = "pixel"
    profile["BIGTIFF"] = "IF_SAFER"

    with rasterio.open(output_fn, "w", **profile) as f:
        f.write(output, 1)
        f.write_colormap(
            1,
            {
                1: (
                    0,
                    0,
                    0,
                    0,
                ),  # this alpha doesn't work because of a limitation in TIFFs
                2: (0, 255, 0, 255),
                3: (255, 0, 0, 255),
                # Neutral grey for a 4th class (e.g. "No Damage" / "Cloud")
                # when the project defines one; unused otherwise.
                4: (128, 128, 128, 255),
            },
        )
        f.colorinterp = [ColorInterp.palette]

    print(f"Finished saving predictions in {time.time()-tic:0.2f} seconds")


if __name__ == "__main__":
    from hastegeo.core.utils.gdal_security import harden_gdal

    harden_gdal()
    main()
