# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

from abc import ABC, abstractmethod

from hastegeo.core.config import Config


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
        pass

    @abstractmethod
    def add_task(self, job_id, task_id, **kwargs):
        pass

    @abstractmethod
    def cleanup_task(self, job_id, task_id):
        pass

    @abstractmethod
    def cancel_task(self, job_id, task_id):
        pass
