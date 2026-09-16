# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from hastegeo.core.config import Config
from hastegeo.core.models.compute import ComputeWorkload
from hastegeo.core.runners.base import split_destination_uri


class TestLocalComposeOutputStorage(unittest.TestCase):
    def test_every_workload_writes_to_the_configured_azurite_container(
        self,
    ) -> None:
        path = (
            Path(__file__).resolve().parents[4]
            / "docker"
            / "docker-compose.yml"
        )
        services = yaml.safe_load(path.read_text(encoding="utf-8"))["services"]
        for service in ("hastefuncapi", "hastefuncqueues"):
            environment = services[service]["environment"]
            account = environment["BLOB_ACCOUNT_URL"].rstrip("/")
            container = environment["BLOB_CONTAINER"]
            expected = f"{account}/{container}"
            with patch.dict(os.environ, environment, clear=True):
                for workload in ComputeWorkload:
                    with self.subTest(service=service, workload=workload):
                        runtime = Config.get_compute_runtime_config(workload)
                        self.assertEqual(
                            runtime["output_container_url"], expected
                        )
                        self.assertEqual(
                            split_destination_uri(
                                f"{expected}/project/task",
                                account_url=account,
                            ),
                            (expected, container, "project/task"),
                        )
