# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

from abc import ABC, abstractmethod

from hastegeo.core.config import Config


class TaskMissingError(LookupError):
    """An accepted task, or the job holding it, no longer exists.

    Nothing can report the task's outcome any more, so the workload ends
    instead of being retried.
    """


class BaseRunner(ABC):
    def __init__(self, config: Config = None):
        self.config = config or Config()

    @abstractmethod
    def get_filecontent_from_task(
        self, job_id, task_id, filename, as_chunk=False
    ):
        pass

    @abstractmethod
    def get_task_status(self, job_id, task_id):
        """Return the task's status.

        Raise ``TaskMissingError`` when an accepted task, or its job, no
        longer exists.
        """
        pass

    @abstractmethod
    def add_task(self, job_id, task_id, **kwargs):
        pass

    @abstractmethod
    def cleanup_task(self, job_id, task_id):
        pass

    @abstractmethod
    def cancel_task(self, job_id, task_id) -> bool:
        """Stop a task if it can still run.

        Return ``False`` only when the task had already finished; callers
        then record its terminal status instead of a cancellation.
        """
        pass
