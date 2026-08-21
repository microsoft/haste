# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Script for fine-tuning a segmentation model to detect damage in satellite imagery."""

import argparse
import glob
import os

import lightning.pytorch as pl
import torch
from bda.config import get_args, normalize_gpu_ids, resolve_constraint_indices
from bda.datamodules import SegmentationDataModule
from bda.trainers import CustomSemanticSegmentationTask
from lightning.pytorch.callbacks import ModelCheckpoint
from lightning.pytorch.loggers import TensorBoardLogger


def add_fine_tune_parser(
    parser: argparse.ArgumentParser,
) -> argparse.ArgumentParser:
    """Adds the arguments for the fine_tune.py script to the base parser."""
    parser.add_argument(
        "--experiment_dir",
        type=str,
        help="Directory that contains an `images/` and `masks/` directory",
    )
    parser.add_argument(
        "--experiment_name",
        type=str,
        help="Name of the experiment (used for TensorBoard logging)",
    )
    parser.add_argument("--training.gpu_id", type=int, help="GPU id to use")
    parser.add_argument(
        "--training.gpu_ids",
        type=int,
        nargs="+",
        help=(
            "One or more GPU ids for multi-GPU (DDP) training, e.g."
            " `--training.gpu_ids 0 1 2 3`. Overrides `--training.gpu_id`."
        ),
    )
    parser.add_argument("--training.batch_size", type=int, help="Batch size")
    parser.add_argument(
        "--training.preload",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Read all tiles into memory instead of reading each patch from"
        " disk (much faster, but the tiles must fit in RAM)",
    )
    parser.add_argument(
        "--training.learning_rate",
        type=float,
        help="Learning rate for optimizer",
    )
    parser.add_argument(
        "--training.max_epochs",
        type=int,
        help="Maximum number of epochs to train for",
    )
    parser.add_argument(
        "--training.log_dir",
        type=str,
        help="Directory to write TensorBoard logs to",
    )
    parser.add_argument(
        "--training.checkpoint_subdir",
        type=str,
        help="Directory to write model checkpoints to",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Whether to overwrite the output dataset if it already exists",
    )
    # NOTE: we don't include `--labels.classes` here because we assume that the classes
    # are the same as the ones used to create the masks.
    # NOTE: we don't include `--imagery.num_channels`, `--imagery.normalization_means`,
    # or `--imagery.normalization_stds` here either because we assume that you won't
    # want to change that

    return parser


def main() -> None:
    """Main function for the fine_tune.py script."""
    args = get_args(description=__doc__, add_extra_parser=add_fine_tune_parser)

    # Use TF32 tensor cores for fp32 matmuls where the GPU has them (Ampere
    # and later). A no-op elsewhere.
    torch.set_float32_matmul_precision("high")

    experiment_dir = args["experiment_dir"]
    assert os.path.exists(os.path.join(experiment_dir, "images/"))
    assert os.path.exists(os.path.join(experiment_dir, "masks/"))

    checkpoint_dir = os.path.join(
        experiment_dir, args["training"]["checkpoint_subdir"]
    )
    # Check for existing *checkpoints*, not just the directory. Under DDP,
    # Lightning re-runs this script in a subprocess per GPU; the main process
    # creates the (empty) checkpoint directory before the workers start, so a
    # bare directory-existence check would make every worker exit early and the
    # run would hang.
    existing_checkpoints = glob.glob(os.path.join(checkpoint_dir, "*.ckpt"))
    if existing_checkpoints and not args["overwrite"]:
        print(
            "Experiment output files already exist, use --overwrite to overwrite them."
            + " Exiting."
        )
        return
    os.makedirs(checkpoint_dir, exist_ok=True)

    gpu_ids = normalize_gpu_ids(
        args["training"].get("gpu_ids"), args["training"].get("gpu_id")
    )
    if not torch.cuda.is_available():
        gpu_ids = []
    world_size = max(1, len(gpu_ids))

    # `train_batches_per_epoch` is per-process under DDP, so divide it by the
    # number of GPUs. This keeps the total batches seen per epoch (and thus the
    # epoch wall-clock time) roughly constant as GPUs are added -- i.e. more
    # GPUs makes each epoch faster instead of just processing proportionally
    # more data.
    train_batches_per_epoch = max(1, 1024 // world_size)

    datamodule = SegmentationDataModule(
        os.path.join(experiment_dir, "images/"),
        os.path.join(experiment_dir, "masks/"),
        batch_size=args["training"]["batch_size"],
        num_workers=int(os.environ.get("HASTE_DATALOADER_WORKERS", "4")),
        train_batches_per_epoch=train_batches_per_epoch,
        means=args["imagery"]["normalization_means"],
        stds=args["imagery"]["normalization_stds"],
        preload=args["training"].get("preload", True) is not False,
    )

    classes = args["labels"]["classes"]

    # Resolve the mask values the constraint loss operates on. "No Damage" is
    # derived from the class list; "Damaged Building" is required to stay at
    # the value the rest of the pipeline hardcodes. See
    # bda.config.resolve_constraint_indices for why they differ.
    use_constraint_loss = args["training"]["use_constraint_loss"]
    no_damage_index, damaged_class_index = resolve_constraint_indices(
        classes, use_constraint_loss
    )
    if use_constraint_loss:
        print(
            f"Constraint loss enabled: penalizing P(Damaged Building="
            f"{damaged_class_index}) at No Damage (={no_damage_index}) pixels"
        )

    # Normally one channel per class plus channel 0 for "not labeled". With
    # the constraint loss, "No Damage" is a weak annotation rather than
    # something the model predicts, so it gets no channel -- the count drops
    # by one and "No Damage" is left as the final mask value with nowhere to
    # land. Channel 0 is still emitted but never supervised, so inference
    # excludes it from the argmax.
    num_classes = len(classes) if use_constraint_loss else len(classes) + 1

    initial_weights_path = args["training"].get("initial_weights_fn", None)
    if initial_weights_path:
        if not os.path.exists(initial_weights_path):
            raise FileNotFoundError(
                f"Checkpoint file for initial weights not found: {initial_weights_path}"
            )

        if not initial_weights_path.endswith((".ckpt", ".pth", ".pt")):
            print(
                f"Warning: Checkpoint file for initial weights doesn't have expected extension: {initial_weights_path}"
            )

        print(f"Loading initial weights from file: {initial_weights_path}")
    else:
        print("Using ImageNet pre-trained weights for model initialization.")

    task = CustomSemanticSegmentationTask(
        model="unet",
        backbone="resnext50_32x4d",
        # Don't use ImageNet weights when loading a custom checkpoint
        weights=not initial_weights_path,
        in_channels=args["imagery"]["num_channels"],
        num_classes=num_classes,
        loss="ce",
        ignore_index=0,  # we use 0 as a "not labeled" class by convention
        lr=args["training"]["learning_rate"],
        patience=10,
        use_constraint_loss=use_constraint_loss,
        no_damage_index=no_damage_index,
        damaged_class_index=damaged_class_index,
    )

    if initial_weights_path:
        # Load the checkpoint
        checkpoint = torch.load(initial_weights_path, map_location="cpu")

        # Filter out incompatible layers (e.g., segmentation_head with different class counts)
        checkpoint_state_dict = checkpoint["state_dict"]
        model_state_dict = task.state_dict()

        # Keep only layers that have matching shapes
        compatible_state_dict = {}
        incompatible_keys = []
        for key, value in checkpoint_state_dict.items():
            if key in model_state_dict:
                if value.shape == model_state_dict[key].shape:
                    compatible_state_dict[key] = value
                else:
                    incompatible_keys.append(
                        f"{key}: checkpoint {value.shape} vs model {model_state_dict[key].shape}"
                    )
            else:
                incompatible_keys.append(f"{key}: not found in current model")

        if incompatible_keys:
            print(f"Skipping {len(incompatible_keys)} incompatible layer(s):")
            for key_info in incompatible_keys:
                print(f"  - {key_info}")

        print(
            f"Loading {len(compatible_state_dict)}/{len(checkpoint_state_dict)} layers from checkpoint"
        )
        task.load_state_dict(compatible_state_dict, strict=False)

    checkpoint_callback = ModelCheckpoint(
        monitor="val_loss",
        dirpath=checkpoint_dir,
        save_top_k=2,
        save_last=True,
    )

    os.makedirs(args["training"]["log_dir"], exist_ok=True)
    tb_logger = TensorBoardLogger(
        save_dir=args["training"]["log_dir"], name=args["experiment_name"]
    )

    # More than one GPU -> data-parallel training via DDP (Lightning's robust
    # multi-GPU strategy). `use_distributed_sampler=False` keeps our custom
    # RandomGeoSampler instead of Lightning injecting a DistributedSampler.
    accelerator = "gpu" if gpu_ids else "cpu"
    devices = gpu_ids if gpu_ids else 1
    strategy = "ddp" if world_size > 1 else "auto"
    # bf16 needs Ampere or later. HASTE's Batch pools are not homogeneous
    # (T4s are Turing and have no bf16), so ask the device rather than
    # assuming, and stay in fp32 on CPU.
    precision = (
        "bf16-mixed"
        if gpu_ids and torch.cuda.is_bf16_supported()
        else "32-true"
    )
    print(
        f"Using accelerator: {accelerator}, device(s): {devices} "
        f"(strategy={strategy}, precision={precision}, "
        f"{train_batches_per_epoch} train batches/epoch/process)"
    )

    trainer = pl.Trainer(
        callbacks=[checkpoint_callback],
        logger=[tb_logger],
        min_epochs=10,
        max_epochs=args["training"]["max_epochs"],
        accelerator=accelerator,
        devices=devices,
        strategy=strategy,
        use_distributed_sampler=False,
        precision=precision,
    )

    trainer.fit(model=task, datamodule=datamodule)


if __name__ == "__main__":
    # GDAL CVE compensating control (docs/known-vulnerabilities.md Root
    # Cause C): restrict GDAL drivers in-process. The GDAL_SKIP env in the
    # training image also covers this; soft-fail if hastegeo is absent.
    try:
        from hastegeo.core.utils.gdal_security import harden_gdal

        harden_gdal()
    except Exception:
        pass
    main()
