# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

from pathlib import Path
from types import SimpleNamespace

import pytest
from hastegeo.core.config import Config
from hastegeo.core.processors.job_state import JobStateRepository


@pytest.fixture
def state(tmp_path: Path, mocker) -> SimpleNamespace:
    mocker.patch(
        "requests.sessions.Session.request",
        side_effect=AssertionError("Unit test attempted network access"),
    )
    mocker.patch.dict(
        "os.environ",
        {
            "METADATA_STORAGE_TYPE": "local",
            "ARTIFACT_STORAGE_TYPE": "local",
            "RUNNER_TYPE": "local",
            "DATA_PATH": str(tmp_path),
        },
    )
    config = Config()
    now = SimpleNamespace(value=1000.0)
    repository = JobStateRepository(config, clock=lambda: now.value)
    queue = mocker.patch.object(repository, "enqueue")
    return SimpleNamespace(
        config=config,
        repository=repository,
        now=now,
        queue=queue,
        root=tmp_path,
    )
