# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

from .base import BaseRunner
from .unified_runner import UnifiedRunner


class DeferredCleanupRunner(BaseRunner):
    """Keep task files until the queue's fenced metadata commit succeeds."""

    def __init__(self, runner: UnifiedRunner) -> None:
        super().__init__(runner.config)
        self.runner = runner
        self.cleanup: list[tuple[str, str]] = []

    def get_filecontent_from_task(
        self, job_id: str, task_id: str, filename: str, as_chunk: bool = False
    ):
        return self.runner.get_filecontent_from_task(
            job_id, task_id, filename, as_chunk=as_chunk
        )

    def get_task_status(self, job_id: str, task_id: str) -> str:
        return self.runner.get_task_status(job_id, task_id)

    def add_task(self, job_id: str, task_id: str, **kwargs) -> tuple[str, str]:
        return self.runner.add_task(job_id, task_id, **kwargs)

    def cleanup_task(self, job_id: str, task_id: str) -> None:
        identity = (job_id, task_id)
        if identity not in self.cleanup:
            self.cleanup.append(identity)

    def cancel_task(self, job_id: str, task_id: str):
        return self.runner.cancel_task(job_id, task_id)
