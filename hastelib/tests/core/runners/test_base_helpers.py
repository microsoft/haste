# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for the shared spec-translation helpers in
``hastegeo.core.runners.base`` (``split_destination_uri``,
``resource_files_from_inputs``, ``require_single_output_destination``,
``require_supported_uri_schemes``, ``truncate_deterministic_id``).

Exercised directly here (in addition to indirectly through
``AzureBatchRunner``/``LocalRunner``'s ``validate()`` in
``test_azure_batch_compute_runner.py``/``test_local_compute_runner.py``) so
the shared logic's behavior is pinned independent of adapter wiring.
"""

import unittest

from hastegeo.core.models.compute import ComputeInput, ComputeOutput, InputKind
from hastegeo.core.runners.base import (
    require_single_output_destination,
    require_supported_uri_schemes,
    resource_files_from_inputs,
    split_destination_uri,
    truncate_deterministic_id,
)


class TestSplitDestinationUri(unittest.TestCase):
    def test_splits_container_and_prefix(self):
        container_url, container_name, prefix = split_destination_uri(
            "https://acct.blob.core.windows.net/data/proj-hash/task-id/"
        )
        self.assertEqual(
            container_url, "https://acct.blob.core.windows.net/data"
        )
        self.assertEqual(container_name, "data")
        self.assertEqual(prefix, "proj-hash/task-id")

    def test_no_prefix_when_container_is_the_whole_path(self):
        container_url, container_name, prefix = split_destination_uri(
            "https://acct.blob.core.windows.net/data"
        )
        self.assertEqual(container_name, "data")
        self.assertEqual(prefix, "")


class TestResourceFilesFromInputs(unittest.TestCase):
    def test_file_input_maps_to_http_url(self):
        inputs = [
            ComputeInput(
                sourceUri="https://a.blob.core.windows.net/c/f.tif",
                kind=InputKind.FILE,
                destinationRelativePath="in/f.tif",
            )
        ]
        result = resource_files_from_inputs(inputs)
        self.assertEqual(
            result,
            {
                "in/f.tif": {
                    "file_path": "in/f.tif",
                    "http_url": "https://a.blob.core.windows.net/c/f.tif",
                }
            },
        )

    def test_folder_input_maps_to_storage_container_url_and_prefix(self):
        inputs = [
            ComputeInput(
                sourceUri="https://a.blob.core.windows.net/c/models/v1/",
                kind=InputKind.FOLDER,
                destinationRelativePath="model",
            )
        ]
        result = resource_files_from_inputs(inputs)
        self.assertEqual(
            result["model"]["storage_container_url"],
            "https://a.blob.core.windows.net/c",
        )
        self.assertEqual(result["model"]["blob_prefix"], "models/v1")
        self.assertEqual(result["model"]["file_path"], "model")

    def test_empty_inputs_returns_empty_dict(self):
        self.assertEqual(resource_files_from_inputs([]), {})

    def test_rejects_duplicate_destination_relative_path(self):
        """A second input silently overwriting the first in the returned
        dict would drop it without any signal — must raise instead."""
        inputs = [
            ComputeInput(
                sourceUri="https://a.blob.core.windows.net/c/f1.tif",
                kind=InputKind.FILE,
                destinationRelativePath="in/f.tif",
            ),
            ComputeInput(
                sourceUri="https://a.blob.core.windows.net/c/f2.tif",
                kind=InputKind.FILE,
                destinationRelativePath="in/f.tif",
            ),
        ]
        with self.assertRaises(ValueError):
            resource_files_from_inputs(inputs)

    def test_distinct_destinations_do_not_raise(self):
        inputs = [
            ComputeInput(
                sourceUri="https://a.blob.core.windows.net/c/f1.tif",
                kind=InputKind.FILE,
                destinationRelativePath="in/f1.tif",
            ),
            ComputeInput(
                sourceUri="https://a.blob.core.windows.net/c/f2.tif",
                kind=InputKind.FILE,
                destinationRelativePath="in/f2.tif",
            ),
        ]
        result = resource_files_from_inputs(inputs)
        self.assertEqual(len(result), 2)


class TestRequireSingleOutputDestination(unittest.TestCase):
    def test_raises_on_empty_outputs(self):
        with self.assertRaises(ValueError):
            require_single_output_destination([])

    def test_single_output_returns_its_container_and_prefix(self):
        outputs = [
            ComputeOutput(
                name="out",
                sourceRelativePattern="outputs/*.tif",
                destinationUri=(
                    "https://a.blob.core.windows.net/data/proj/task/"
                ),
            )
        ]
        (
            container_url,
            container_name,
            prefix,
            patterns,
        ) = require_single_output_destination(outputs)
        self.assertEqual(container_url, "https://a.blob.core.windows.net/data")
        self.assertEqual(container_name, "data")
        self.assertEqual(prefix, "proj/task")
        self.assertEqual(patterns, ["outputs/*.tif"])

    def test_matching_container_and_prefix_allowed(self):
        outputs = [
            ComputeOutput(
                name="a",
                sourceRelativePattern="a/*.tif",
                destinationUri="https://a.blob.core.windows.net/data/p/t/",
            ),
            ComputeOutput(
                name="b",
                sourceRelativePattern="b/*.tif",
                destinationUri="https://a.blob.core.windows.net/data/p/t/",
            ),
        ]
        (
            _container_url,
            _container_name,
            _prefix,
            patterns,
        ) = require_single_output_destination(outputs)
        self.assertEqual(patterns, ["a/*.tif", "b/*.tif"])

    def test_rejects_different_container(self):
        outputs = [
            ComputeOutput(
                name="a",
                sourceRelativePattern="a/*.tif",
                destinationUri="https://a.blob.core.windows.net/data/p/t/",
            ),
            ComputeOutput(
                name="b",
                sourceRelativePattern="b/*.tif",
                destinationUri="https://a.blob.core.windows.net/other/p/t/",
            ),
        ]
        with self.assertRaises(ValueError):
            require_single_output_destination(outputs)

    def test_rejects_same_container_different_prefix(self):
        """Regression test: comparing only the container previously let a
        different prefix through silently, using only the first output's
        prefix for both."""
        outputs = [
            ComputeOutput(
                name="a",
                sourceRelativePattern="a/*.tif",
                destinationUri="https://a.blob.core.windows.net/data/p/t1/",
            ),
            ComputeOutput(
                name="b",
                sourceRelativePattern="b/*.tif",
                destinationUri="https://a.blob.core.windows.net/data/p/t2/",
            ),
        ]
        with self.assertRaises(ValueError):
            require_single_output_destination(outputs)


class TestRequireSupportedUriSchemes(unittest.TestCase):
    def _input(self, uri):
        return ComputeInput(
            sourceUri=uri,
            kind=InputKind.FILE,
            destinationRelativePath="in/f.tif",
        )

    def _output(self, uri):
        return ComputeOutput(
            name="out",
            sourceRelativePattern="outputs/*.tif",
            destinationUri=uri,
        )

    def test_allows_https_input_and_output(self):
        require_supported_uri_schemes(
            inputs=[self._input("https://a.blob.core.windows.net/c/f.tif")],
            outputs=[
                self._output("https://a.blob.core.windows.net/data/p/t/")
            ],
            allowed_schemes=frozenset({"http", "https"}),
            backend_name="test-backend",
        )  # must not raise

    def test_rejects_s3_input(self):
        with self.assertRaises(ValueError):
            require_supported_uri_schemes(
                inputs=[self._input("s3://bucket/key.tif")],
                outputs=[],
                allowed_schemes=frozenset({"http", "https"}),
                backend_name="test-backend",
            )

    def test_rejected_scheme_error_never_includes_the_full_uri(self):
        """A ComputeJobSpec's declared sourceUri/destinationUri is not
        guaranteed free of a signed query string; the raised message must
        name only the rejected scheme, never echo the full URI (which can
        propagate into validate()/execution-service logs)."""
        signed_uri = (
            "azureml://datastores/x/paths/p/t/"
            "?sv=2020-01-01&se=2030-01-01&sig=TOPSECRETSIGNATURE"
        )
        with self.assertRaises(ValueError) as cm:
            require_supported_uri_schemes(
                inputs=[self._input(signed_uri)],
                outputs=[],
                allowed_schemes=frozenset({"http", "https"}),
                backend_name="test-backend",
            )
        message = str(cm.exception)
        self.assertNotIn(signed_uri, message)
        self.assertNotIn("TOPSECRETSIGNATURE", message)
        self.assertIn("azureml", message)  # the rejected scheme itself

    def test_rejects_azureml_output(self):
        with self.assertRaises(ValueError):
            require_supported_uri_schemes(
                inputs=[],
                outputs=[self._output("azureml://datastores/x/paths/p/t/")],
                allowed_schemes=frozenset({"http", "https"}),
                backend_name="test-backend",
            )

    def test_rejects_adl_input(self):
        with self.assertRaises(ValueError):
            require_supported_uri_schemes(
                inputs=[
                    self._input("adl://acct.azuredatalakestore.net/f.tif")
                ],
                outputs=[],
                allowed_schemes=frozenset({"http", "https"}),
                backend_name="test-backend",
            )

    def test_rejects_abfss_when_not_in_allowed_set(self):
        with self.assertRaises(ValueError):
            require_supported_uri_schemes(
                inputs=[
                    self._input("abfss://fs@acct.dfs.core.windows.net/f.tif")
                ],
                outputs=[],
                allowed_schemes=frozenset({"http", "https"}),
                backend_name="test-backend",
            )

    def test_empty_inputs_and_outputs_never_raise(self):
        require_supported_uri_schemes(
            inputs=[],
            outputs=[],
            allowed_schemes=frozenset({"http", "https"}),
            backend_name="test-backend",
        )


class TestTruncateDeterministicId(unittest.TestCase):
    def test_value_at_or_under_max_length_is_returned_unchanged(self):
        self.assertEqual(
            truncate_deterministic_id("training-pool", max_length=64),
            "training-pool",
        )

    def test_value_exactly_at_boundary_is_unchanged(self):
        value = "a" * 64
        self.assertEqual(
            truncate_deterministic_id(value, max_length=64), value
        )

    def test_value_one_over_boundary_is_truncated_to_max_length(self):
        value = "a" * 65
        result = truncate_deterministic_id(value, max_length=64)
        self.assertEqual(len(result), 64)
        self.assertNotEqual(result, value[:64])  # not a raw slice

    def test_longer_value_never_exceeds_max_length(self):
        for length in (64, 65, 100, 500):
            with self.subTest(length=length):
                result = truncate_deterministic_id("j" * length, max_length=64)
                self.assertLessEqual(len(result), 64)

    def test_result_is_deterministic_for_same_input(self):
        value = "training-job-" * 10
        first = truncate_deterministic_id(value, max_length=64)
        second = truncate_deterministic_id(value, max_length=64)
        self.assertEqual(first, second)

    def test_distinct_long_values_sharing_a_prefix_yield_distinct_ids(self):
        """Regression test: a plain slice would collide two long,
        differently-configured job ids that happen to share the same
        first 64 characters into the exact same truncated id."""
        shared_prefix = "a" * 80
        value_a = shared_prefix + "-suffix-one"
        value_b = shared_prefix + "-suffix-two"
        result_a = truncate_deterministic_id(value_a, max_length=64)
        result_b = truncate_deterministic_id(value_b, max_length=64)
        self.assertNotEqual(result_a, result_b)
        self.assertEqual(len(result_a), 64)
        self.assertEqual(len(result_b), 64)

    def test_result_retains_a_readable_prefix_of_the_original_value(self):
        value = "readable-training-job-prefix-" + "z" * 60
        result = truncate_deterministic_id(value, max_length=64)
        self.assertTrue(result.startswith("readable-training-job-prefix-"))

    def test_falls_back_to_hash_only_when_max_length_too_small_for_prefix(
        self,
    ):
        result = truncate_deterministic_id("x" * 100, max_length=5)
        self.assertEqual(len(result), 5)

    def test_empty_value_is_returned_unchanged(self):
        self.assertEqual(truncate_deterministic_id("", max_length=64), "")


if __name__ == "__main__":
    unittest.main()
