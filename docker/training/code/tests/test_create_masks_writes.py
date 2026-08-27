# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for BigTIFF-safe raster writes in ``create_masks.py``."""

import ast
import os
import unittest
from typing import Optional

import numpy as np

CODE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREATE_MASKS_PATH = os.path.join(CODE_DIR, "create_masks.py")


class _FakeWriter:
    def __init__(self):
        self.write_calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def write(self, *args):
        self.write_calls.append(args)


class _FakeRasterio:
    def __init__(self):
        self.open_calls = []
        self.writer = _FakeWriter()

    def open(self, *args, **kwargs):
        self.open_calls.append((args, kwargs))
        return self.writer


def _load_write_training_raster(rasterio_module):
    """Load the writer without importing create_masks' GDAL dependencies."""
    with open(CREATE_MASKS_PATH) as source_file:
        source = source_file.read()

    start = source.index("def write_training_raster(")
    end = source.index("def get_class_names_from_labels(")
    namespace = {
        "np": np,
        "Optional": Optional,
        "rasterio": rasterio_module,
    }
    exec(compile(source[start:end], CREATE_MASKS_PATH, "exec"), namespace)
    return namespace["write_training_raster"]


def _get_training_raster_calls():
    """Find helper calls inside ``create_mask_for_labels``."""
    with open(CREATE_MASKS_PATH) as source_file:
        tree = ast.parse(source_file.read())

    create_masks = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "create_mask_for_labels"
    )
    return [
        node
        for node in ast.walk(create_masks)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "write_training_raster"
    ]


def _get_bigtiff_assignment_and_write_lines(filename):
    """Find the BigTIFF profile assignment and rasterio write calls."""
    path = os.path.join(CODE_DIR, filename)
    with open(path) as source_file:
        tree = ast.parse(source_file.read())

    assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Name)
            and target.value.id == "profile"
            and target.slice.value == "BIGTIFF"
            for target in node.targets
        )
        and node.value.value == "IF_SAFER"
    ]
    write_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "rasterio"
        and node.func.attr == "open"
        and any(
            isinstance(argument, ast.Constant) and argument.value == "w"
            for argument in node.args
        )
    ]
    return assignments, write_calls


class TestWriteTrainingRaster(unittest.TestCase):
    def setUp(self):
        self.rasterio = _FakeRasterio()
        self.write_training_raster = _load_write_training_raster(self.rasterio)

    def test_applies_if_safer_without_mutating_input_profile(self):
        profile = {
            "driver": "GTiff",
            "compress": "lzw",
            "BIGTIFF": "NO",
        }
        data = np.zeros((3, 2, 2), dtype=np.uint8)

        self.write_training_raster("image.tif", data, profile)

        args, output_profile = self.rasterio.open_calls[0]
        self.assertEqual(args, ("image.tif", "w"))
        self.assertEqual(output_profile["BIGTIFF"], "IF_SAFER")
        self.assertEqual(output_profile["compress"], "lzw")
        self.assertEqual(profile["BIGTIFF"], "NO")

    def test_writes_multiband_image_without_band_index(self):
        data = np.zeros((3, 2, 2), dtype=np.uint8)

        self.write_training_raster("image.tif", data, {"driver": "GTiff"})

        self.assertEqual(self.rasterio.writer.write_calls, [(data,)])

    def test_writes_mask_to_requested_band(self):
        mask = np.zeros((2, 2), dtype=np.uint8)

        self.write_training_raster(
            "mask.tif", mask, {"driver": "GTiff"}, band=1
        )

        self.assertEqual(self.rasterio.writer.write_calls, [(mask, 1)])


class TestCreateMaskWritePaths(unittest.TestCase):
    def test_cropped_image_uses_bigtiff_writer(self):
        calls = _get_training_raster_calls()

        image_call = next(
            call
            for call in calls
            if isinstance(call.args[0], ast.Name)
            and call.args[0].id == "output_cropped_image_fn"
        )

        self.assertEqual(
            [argument.id for argument in image_call.args],
            ["output_cropped_image_fn", "data", "profile"],
        )
        self.assertEqual(image_call.keywords, [])

    def test_buffered_mask_uses_bigtiff_writer(self):
        calls = _get_training_raster_calls()

        mask_call = next(
            call
            for call in calls
            if isinstance(call.args[0], ast.Name)
            and call.args[0].id == "output_buffered_mask_fn"
        )

        self.assertEqual(
            [argument.id for argument in mask_call.args],
            ["output_buffered_mask_fn", "mask", "mask_profile"],
        )
        self.assertEqual(len(mask_call.keywords), 1)
        self.assertEqual(mask_call.keywords[0].arg, "band")
        self.assertEqual(mask_call.keywords[0].value.value, 1)


class TestWorkflowBigTiffProfiles(unittest.TestCase):
    def _assert_bigtiff_precedes_raster_write(self, filename):
        assignments, write_calls = _get_bigtiff_assignment_and_write_lines(
            filename
        )

        self.assertEqual(len(assignments), 1)
        self.assertEqual(len(write_calls), 1)
        self.assertLess(assignments[0].lineno, write_calls[0].lineno)

    def test_inference_predictions_use_if_safer(self):
        self._assert_bigtiff_precedes_raster_write("inference.py")

    def test_visualizer_output_uses_if_safer(self):
        self._assert_bigtiff_precedes_raster_write("output2visualizer.py")

    def test_raw_mask_rasterizer_uses_bigtiff(self):
        with open(CREATE_MASKS_PATH) as source_file:
            tree = ast.parse(source_file.read())

        rasterize_commands = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.List)
            and node.value.elts
            and isinstance(node.value.elts[0], ast.Constant)
            and node.value.elts[0].value == "gdal_rasterize"
        ]

        self.assertTrue(
            any(
                any(
                    isinstance(argument, ast.Constant)
                    and argument.value == "BIGTIFF=YES"
                    for argument in command.elts
                )
                for command in rasterize_commands
            )
        )


if __name__ == "__main__":
    unittest.main()
