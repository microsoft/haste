# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Helper script for running the entire workflow."""

import argparse
import glob
import os
import subprocess
import sys
import traceback
from datetime import datetime, timezone

import yaml


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
        run_subprocess(
            ["python", "inference.py", "--config", args.config, "--overwrite"],
            "inference.py",
        )

        inference_dir = os.path.join(
            config.get("experiment_dir"),
            config.get("inference", {}).get("output_subdir"),
        )
        log_progress("Calculating building bounds")
        input_fn = config.get("imagery").get("raw_fn")
        extracted_mask_fn = os.path.join(
            inference_dir,
            os.path.basename(input_fn).replace(".tif", ".geojson"),
        )
        run_subprocess(
            [
                "python",
                "extract_data_mask_from_geotiff.py",
                "--input_fn",
                input_fn,
                "--output_fn",
                extracted_mask_fn,
                "--overwrite",
            ],
            "extract_data_mask_from_geotiff.py",
        )

        log_progress("Downloading building footprints")
        # TODO: make --source configurable from UI?
        # source = config.get("inference", {}).get("building_footprints_source")
        # country_alpha2_iso_code = config.get("inference", {}).get(
        #     "country_alpha2_iso_code"
        # )
        downloaded_footprints_fn = os.path.join(
            inference_dir, "AOI_buildings_footprints.gpkg"
        )

        run_subprocess(
            [
                "python",
                "download_building_footprints.py",
                "--input_fn",
                extracted_mask_fn,
                "--output_fn",
                downloaded_footprints_fn,
                "--overwrite",
            ],
            "download_building_footprints.py",
        )
        # Merge with inferred damage layer
        # Assumes there's only one *_predictions.tif

        log_progress("Merging predictions")

        predictions_files = glob.glob(
            os.path.join(inference_dir, "*_predictions.tif")
        )
        if not predictions_files:
            log_progress("Error running inference: no predictions files found")
            raise RuntimeError(
                "Something went wrong, no predictions files found in "
                f"{inference_dir}. Please download all artifacts for this model"
                " and check the stderr and stdout files for more information."
            )
        predicted_damage_fn = predictions_files[0]
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
