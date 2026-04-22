# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import os
from zipfile import ZipFile


def main():
    """
    Main function to zip artifacts.
    """
    # Setup directories
    output_dir = "outputs"
    temp_dir = "temp"

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(temp_dir, exist_ok=True)

    INPUT_DIR = os.getenv("INPUT_DIR", "inputs")
    OUTPUT_ZIP_NAME = os.getenv("OUTPUT_ZIP_NAME", "model_outputs")

    # Create a ZIP file of each input directory
    for dir_to_zip in os.listdir(INPUT_DIR):
        input_dir_path = os.path.join(INPUT_DIR, dir_to_zip)
        temp_zip_path = os.path.join(temp_dir, dir_to_zip + ".zip")
        with ZipFile(temp_zip_path, "w") as zipf:
            for root, dirs, files in os.walk(input_dir_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    zipf.write(
                        file_path, os.path.relpath(file_path, input_dir_path)
                    )

    # Make a final zip of all zips in the temp directory
    if not OUTPUT_ZIP_NAME.endswith(".zip"):
        OUTPUT_ZIP_NAME += ".zip"
    output_zip_path = os.path.join(output_dir, OUTPUT_ZIP_NAME)
    with ZipFile(output_zip_path, "w") as zipf:
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                file_path = os.path.join(root, file)
                zipf.write(file_path, os.path.relpath(file_path, temp_dir))


if __name__ == "__main__":
    main()
