# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import importlib
import logging

from ..config import Config


class UnifiedRunner:
    def __init__(self, runner_type, config: Config = None, **kwargs):
        self.config = config or Config()

        # Debug logging
        logger = logging.getLogger(__name__)
        logger.info(
            f"[PIPELINE-TRACE] UnifiedRunner creating runner of type: {runner_type}"
        )

        # Dictionary to map runner types to their respective modules and class names
        # Supports both "azure_batch" for cloud/remote runs and "local" for Docker-based local runs
        runner_class_map = {
            "azure_batch": (
                "azure_batch",
                "AzureBatchRunner",
            ),
            "local": (
                "local",
                "LocalRunner",
            ),
        }

        if runner_type in runner_class_map:
            module_name, class_name = runner_class_map[runner_type]
            logger.info(
                f"[PIPELINE-TRACE] Loading {class_name} from module {module_name}"
            )
            module = importlib.import_module(f"{__package__}.{module_name}")
            runner_class = getattr(module, class_name)
            self.runner = runner_class(config=self.config, **kwargs)
            logger.info(
                f"[PIPELINE-TRACE] Successfully created runner: {type(self.runner)}"
            )
        else:
            raise ValueError(f"Unsupported runner type: {runner_type}")

    def get_filecontent_from_task(
        self, job_id, task_id, filename, as_chunk=False
    ):
        return self.runner.get_filecontent_from_task(
            job_id, task_id, filename, as_chunk=as_chunk
        )

    def get_task_status(self, job_id, task_id):
        return self.runner.get_task_status(job_id, task_id)

    def add_task(self, job_id, task_id, **kwargs):
        # Debug logging to see what parameters are being passed through
        logger = logging.getLogger(__name__)
        logger.info(
            f"UnifiedRunner.add_task called with job_id={job_id}, task_id={task_id}, kwargs keys={list(kwargs.keys())}"
        )
        if "resource_files_for_upload" in kwargs:
            logger.info(
                f"resource_files_for_upload present: {kwargs['resource_files_for_upload']}"
            )
        else:
            logger.info("resource_files_for_upload NOT present in kwargs")
        return self.runner.add_task(job_id, task_id, **kwargs)

    def cleanup_task(self, job_id, task_id):
        return self.runner.cleanup_task(job_id, task_id)

    def cancel_task(self, job_id, task_id):
        return self.runner.cancel_task(job_id, task_id)
