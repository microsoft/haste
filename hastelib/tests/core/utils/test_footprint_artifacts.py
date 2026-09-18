# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import unittest
from types import SimpleNamespace

from hastegeo.core.models.projects import ImageLayer, TrainingJob
from hastegeo.core.utils.footprint_artifacts import (
    validate_layer_footprint_url,
)
from hastegeo.core.utils.metadata import MetadataUtils


class TestFootprintArtifactNamespace(unittest.TestCase):
    def setUp(self) -> None:
        self.layer = ImageLayer(
            projectId="project",
            imageLayerId="layer",
            footprintTilesJob=TrainingJob(jobId="job", taskId="ftl-task"),
        )
        self.config = SimpleNamespace(
            artifact_storage_type="blob",
            artifact_storage_config={"container": "data"},
            storage_config={"container": "data"},
        )
        self.prefix = MetadataUtils.hash_string("project")

    def test_accepts_only_exact_layer_filename_and_task_output(self) -> None:
        for suffix in (
            "footprints_layer.pmtiles",
            "ftl-task/footprints_layer.pmtiles",
        ):
            validate_layer_footprint_url(
                f"https://acct.blob.core.windows.net/data/{self.prefix}/{suffix}?sig=ignored",
                self.layer,
                self.config,
            )

    def test_rejects_other_container_project_layer_and_traversal(self) -> None:
        for path in (
            f"private/{self.prefix}/footprints_layer.pmtiles",
            "data/another-project/footprints_layer.pmtiles",
            f"data/{self.prefix}/footprints_other.pmtiles",
            f"data/{self.prefix}/ftl-other/footprints_layer.pmtiles",
            f"data/{self.prefix}/%2e%2e/secret.json",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_layer_footprint_url(
                    "https://acct.blob.core.windows.net/" + path,
                    self.layer,
                    self.config,
                )
