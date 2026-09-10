# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Helper script for running the entire workflow."""

import argparse
import glob
import os
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

import yaml

INFERENCE_ADAPTERS = {
    "legacy_haste": "inference.py",
    "dinov3_upernet": "inference_dinov3.py",
}


def prediction_path(config, inference_dir):
    """Explicit catalog identity, deterministic legacy fallback (never first glob)."""
    inference = config["inference"]
    filename = inference.get("predictions_filename")
    if filename is not None:
        if Path(filename).name != filename or not filename.endswith(
            "_predictions.tif"
        ):
            raise ValueError(
                "predictions_filename must be a basename ending _predictions.tif"
            )
        path = os.path.join(inference_dir, filename)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Expected predictions missing at {path}")
        return path
    if inference.get("adapter") == "dinov3_upernet":
        raise ValueError("DINOv3 requires inference.predictions_filename")
    files = sorted(glob.glob(os.path.join(inference_dir, "*_predictions.tif")))
    if len(files) != 1:
        raise RuntimeError(
            f"Expected exactly one legacy prediction raster in {inference_dir}; "
            f"found {len(files)}. Set inference.predictions_filename explicitly."
        )
    return files[0]


def ensure_prediction_cog(filename):
    """Publish legacy GTiff predictions as COG without changing classifier semantics."""
    import rasterio
    import rasterio.shutil

    with rasterio.open(filename) as src:
        if src.crs is None:
            raise ValueError("Predictions must have a CRS")
        if src.tags(ns="IMAGE_STRUCTURE").get("LAYOUT") == "COG":
            return
    with tempfile.TemporaryDirectory(
        prefix=".prediction-cog-", dir=os.path.dirname(filename)
    ) as tmp:
        cog = os.path.join(tmp, "predictions.tif")
        rasterio.shutil.copy(
            filename,
            cog,
            driver="COG",
            compress="LZW",
            blocksize=512,
            BIGTIFF="IF_SAFER",
            overview_resampling="NEAREST",
            resampling="NEAREST",
            overviews="IGNORE_EXISTING",
        )
        os.replace(cog, filename)


def run_subprocess(command, step_name):
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        log_progress(f"Error running {step_name}")
        print(f"Error running {step_name} (exit code: {result.returncode})")
        if result.stdout:
            print(f"[{step_name}] stdout:\n{result.stdout}")
        if result.stderr:
            print(f"[{step_name}] stderr:\n{result.stderr}")
        raise subprocess.CalledProcessError(
            result.returncode,
            result.args,
            output=result.stdout,
            stderr=result.stderr,
        )
    # Keep successful classifier provenance and timings in the task logs too.
    if result.stdout:
        print(result.stdout, end="", flush=True)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr, flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=str, required=True, help="Path to config file"
    )
    parser.add_argument(
        "--step",
        type=str,
        choices=["training", "inference"],
        default="all",
        help="Step to execute (default: all)",
    )

    args = parser.parse_args()

    with open(args.config, "r") as f:
        config = yaml.safe_load(f)
    adapter = config.get("inference", {}).get("adapter", "legacy_haste")
    if adapter not in INFERENCE_ADAPTERS:
        raise ValueError(f"Unsupported inference adapter: {adapter}")
    if adapter == "dinov3_upernet" and args.step != "inference":
        raise ValueError("DINOv3 is inference-only; use --step inference")

    if args.step == "training" or args.step == "all":
        if not os.path.exists(config.get("labels").get("fn")):
            log_progress("Error running create_masks.py")
            raise RuntimeError(
                f"Labels not found at {config.get('labels').get('fn')}"
            )
        run_subprocess(
            [
                "python",
                "create_masks.py",
                "--config",
                args.config,
                "--overwrite",
            ],
            "create_masks.py",
        )

        run_subprocess(
            ["python", "fine_tune.py", "--config", args.config, "--overwrite"],
            "fine_tune.py",
        )
        # Absence of file is caught by fine_tune.py
        checkpoint_dir = os.path.join(
            config.get("experiment_dir"),
            config.get("training", {}).get("checkpoint_subdir"),
        )
        ckpt_files = glob.glob(os.path.join(checkpoint_dir, "*.ckpt"))
        if not ckpt_files:
            print("No .ckpt files found in checkpoint_subdir.")
            log_progress("Error running fine_tune.py")
            raise RuntimeError(
                "No checkpoint files created. Please download all artifacts for this model"
                " and check the stderr and stdout files for more information"
            )

    if args.step == "inference" or args.step == "all":
        log_progress("Generating predictions")
        classifier = INFERENCE_ADAPTERS[adapter]
        run_subprocess(
            ["python", classifier, "--config", args.config, "--overwrite"],
            classifier,
        )

        inference_dir = os.path.join(
            config.get("experiment_dir"),
            config.get("inference", {}).get("output_subdir"),
        )

        # Building footprints are downloaded once per image layer during the
        # imageryprep workflow and shipped here as inputs/building_footprints.gpkg
        # by the LocalRunner / Azure Batch runner. The previous in-workflow
        # extract_data_mask_from_geotiff.py + download_building_footprints.py
        # steps were removed when imageryprep started caching them.
        log_progress("Using cached building footprints")
        downloaded_footprints_fn = os.path.join(
            os.environ.get("AZ_BATCH_TASK_WORKING_DIR", "."),
            "inputs",
            "building_footprints.gpkg",
        )
        if not os.path.exists(downloaded_footprints_fn):
            log_progress(
                "Cached building footprints not found at "
                f"{downloaded_footprints_fn}; the image layer must be "
                "re-processed through imageryprep to produce them."
            )
            raise RuntimeError(
                f"Cached building footprints missing at {downloaded_footprints_fn}"
            )

        # Merge with inferred damage layer
        log_progress("Merging predictions")

        predicted_damage_fn = prediction_path(config, inference_dir)
        ensure_prediction_cog(predicted_damage_fn)
        gpkg_prefix = config["inference"]["predictions_gpkg_fileprefix"]
        merged_building_predictions_fn = os.path.join(
            inference_dir, f"{gpkg_prefix}.gpkg"
        )
        run_subprocess(
            [
                "python",
                "merge_with_building_footprints.py",
                "--footprints_fn",
                downloaded_footprints_fn,
                "--predictions_fn",
                predicted_damage_fn,
                "--output_fn",
                merged_building_predictions_fn,
                "--overwrite",
                *(
                    ["--preserve_source_identity"]
                    if config["inference"].get(
                        "preserve_source_identity", False
                    )
                    else []
                ),
            ],
            "merge_with_building_footprints.py",
        )

        # Generate visualizer output - same file name, but with a .tif extension
        log_progress("Generating results")
        temp_vis_fn = predicted_damage_fn.replace(
            "_predictions.tif", "_temp_vis.tif"
        )
        run_subprocess(
            [
                "python",
                "output2visualizer.py",
                "--merged_footprints_fn",
                merged_building_predictions_fn,
                "--predictions_fn",
                predicted_damage_fn,
                "--output_fn",
                temp_vis_fn,
                "--overwrite",
            ],
            "output2visualizer.py",
        )

        visualizer_cog_fn = temp_vis_fn.replace(
            "_temp_vis.tif", "_visualizer.tif"
        )

        log_progress("Converting results to COG")

        gdal_translate_params = os.getenv("GDAL_TRANSLATE_PARAMS")
        formatted_gdal_params = []
        if gdal_translate_params:
            if "-co" in gdal_translate_params:
                formatted_gdal_params = gdal_translate_params.split()
            else:
                for op in gdal_translate_params.split():
                    formatted_gdal_params += ["-co", op]
        run_subprocess(
            [
                "gdal_translate",
                "-of",
                "COG",
                *formatted_gdal_params,
                "-co",
                "COMPRESS=LZW",
                "-co",
                "BLOCKSIZE=512",
                "-co",
                "BIGTIFF=IF_SAFER",
                "-co",
                "OVERVIEWS=IGNORE_EXISTING",
                "-co",
                "OVERVIEW_RESAMPLING=NEAREST",
                "-co",
                "RESAMPLING=NEAREST",
                temp_vis_fn,
                visualizer_cog_fn,
            ],
            "gdal_translate",
        )


def log_progress(message):
    """Write progress steps and messages to a file"""
    # Create a directory for logs if it doesn't exist
    log_dir = os.path.join(os.getenv("AZ_BATCH_TASK_WORKING_DIR", "."), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "workflow_progress.log")

    with open(log_file, "a") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()}|{message}\n")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(e)
        traceback.print_exc()
        log_progress(
            f"Error running command (exit code {e.returncode}). See task stderr for details."
        )
        log_progress("Please contact your HASTE website administrator")
        sys.exit(1)
    except Exception as e:
        print(e)
        traceback.print_exc()
        log_progress(
            f"Unexpected error: {type(e).__name__}. See task stderr for details."
        )
        log_progress("Please contact your HASTE website administrator")
        sys.exit(1)
