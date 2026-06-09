# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json
import os
from zipfile import ZipFile


def _aggregate_dirs_into_zip(src_dirs, zip_path):
    """Zip the union of files under each src_dir into zip_path.

    Archive names are prefixed with os.path.basename(src_dir) so that
    same-relative-path files in different src_dirs do not collide.
    """
    with ZipFile(zip_path, "w") as zipf:
        for src_dir in src_dirs:
            prefix = os.path.basename(os.path.normpath(src_dir))
            for root, _dirs, files in os.walk(src_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    rel = os.path.relpath(file_path, src_dir)
                    zipf.write(file_path, os.path.join(prefix, rel))


def main():
    """Create separate training and inference zip archives.

    Reads subdirectories from INPUT_DIR, classifies them by ``trn-`` /
    ``inf-`` prefix, and produces one zip per category.  A
    ``manifest.json`` is written alongside the zips so the orchestrator
    can read back file sizes without extra blob API calls.
    """
    output_dir = "outputs"
    os.makedirs(output_dir, exist_ok=True)

    input_dir = os.getenv("INPUT_DIR", "inputs")
    training_zip_name = os.getenv(
        "OUTPUT_TRAINING_ZIP_NAME", "training_artifacts"
    )
    inference_zip_name = os.getenv(
        "OUTPUT_INFERENCE_ZIP_NAME", "inference_artifacts"
    )

    if not training_zip_name.endswith(".zip"):
        training_zip_name += ".zip"
    if not inference_zip_name.endswith(".zip"):
        inference_zip_name += ".zip"

    training_dirs = []
    inference_dirs = []

    for entry in sorted(os.listdir(input_dir)):
        full_path = os.path.join(input_dir, entry)
        if not os.path.isdir(full_path):
            continue
        if entry.startswith("trn-"):
            training_dirs.append(full_path)
        elif entry.startswith("inf-"):
            inference_dirs.append(full_path)

    manifest = {}

    if training_dirs:
        training_zip_path = os.path.join(output_dir, training_zip_name)
        _aggregate_dirs_into_zip(training_dirs, training_zip_path)
        manifest["training_zip"] = {
            "filename": training_zip_name,
            "size_bytes": os.path.getsize(training_zip_path),
        }

    if inference_dirs:
        inference_zip_path = os.path.join(output_dir, inference_zip_name)
        _aggregate_dirs_into_zip(inference_dirs, inference_zip_path)
        manifest["inference_zip"] = {
            "filename": inference_zip_name,
            "size_bytes": os.path.getsize(inference_zip_path),
        }

    manifest_path = os.path.join(output_dir, "zip_manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)


if __name__ == "__main__":
    main()
