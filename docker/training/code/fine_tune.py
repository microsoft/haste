# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Script for fine-tuning a segmentation model to detect damage in satellite imagery."""

import argparse
import os

import lightning.pytorch as pl
import torch
from bda.config import get_args
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
    parser.add_argument("--training.batch_size", type=int, help="Batch size")
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

    experiment_dir = args["experiment_dir"]
    assert os.path.exists(os.path.join(experiment_dir, "images/"))
    assert os.path.exists(os.path.join(experiment_dir, "masks/"))

    checkpoint_dir = os.path.join(
        experiment_dir, args["training"]["checkpoint_subdir"]
    )
    if os.path.exists(checkpoint_dir) and not args["overwrite"]:
        print(
            "Experiment output files already exist, use --overwrite to overwrite them."
            + " Exiting."
        )
        return
    os.makedirs(checkpoint_dir, exist_ok=True)

    datamodule = SegmentationDataModule(
        os.path.join(experiment_dir, "images/"),
        os.path.join(experiment_dir, "masks/"),
        batch_size=args["training"]["batch_size"],
        num_workers=int(os.environ.get("HASTE_DATALOADER_WORKERS", "4")),
        train_batches_per_epoch=1024,
        means=args["imagery"]["normalization_means"],
        stds=args["imagery"]["normalization_stds"],
    )

    # we include +1 to account for our 0 "not labeled" class
    num_classes = len(args["labels"]["classes"]) + 1

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
        task = CustomSemanticSegmentationTask(
            model="unet",
            backbone="resnext50_32x4d",
            weights=False,  # Don't use ImageNet weights when loading custom checkpoint
            in_channels=args["imagery"]["num_channels"],
            num_classes=num_classes,
            loss="ce",
            ignore_index=0,
            lr=args["training"]["learning_rate"],
            patience=10,
            use_constraint_loss=args["training"]["use_constraint_loss"],
        )

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
    else:
        print("Using ImageNet pre-trained weights for model initialization.")

        task = CustomSemanticSegmentationTask(
            model="unet",
            backbone="resnext50_32x4d",
            weights=True,  # use ImageNet pre-trained weights
            in_channels=args["imagery"]["num_channels"],
            num_classes=num_classes,
            loss="ce",
            ignore_index=0,  # we use 0 as a "not labeled" class by convention
            lr=args["training"]["learning_rate"],
            patience=10,
            use_constraint_loss=args["training"]["use_constraint_loss"],
        )

    checkpoint_callback = ModelCheckpoint(
        monitor="val_loss",
        dirpath=checkpoint_dir,
        save_top_k=2,
        save_last=True,
    )

    tb_logger = TensorBoardLogger(
        save_dir=args["training"]["log_dir"], name=args["experiment_name"]
    )

    accelerator = "gpu" if torch.cuda.is_available() else "cpu"
    print(f"Using accelerator: {accelerator}")

    devices = [args["training"]["gpu_id"]] if torch.cuda.is_available() else 1
    print(f"Using devices: {devices}")

    trainer = pl.Trainer(
        callbacks=[checkpoint_callback],
        logger=[tb_logger],
        min_epochs=10,
        max_epochs=args["training"]["max_epochs"],
        accelerator=accelerator,
        devices=devices,
    )

    trainer.fit(model=task, datamodule=datamodule)


if __name__ == "__main__":
    main()
