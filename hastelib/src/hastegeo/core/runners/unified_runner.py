# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Deprecated two-entry runner factory.

Superseded by ``RunnerRegistry`` + ``ComputeExecutionService``
(``hastegeo.core.runners.{registry,execution_service}``), which operate on
the backend-neutral ``ComputeRunner`` contract instead of this class's
``(job_id, task_id)`` methods (see ADR-0005 and
spec/features/aml-compute-backend/design.md).

Superseding is complete: all five processors (``train.py``,
``inference.py``, ``embedding.py``, ``imagery.py``, ``artifacts.py``) now
build a ``ComputeJobSpec`` and submit/dispatch through
``ComputeExecutionService`` (plan.md Phase 8, done) — none of them
construct this class anymore. ``AzureBatchRunner``/``LocalRunner`` are
likewise fully migrated to ``ComputeRunner`` (plan.md Phase 4, done) in
addition to still implementing the legacy ``BaseRunner`` contract this
class wraps. This module is kept only for the deprecation window in case
of an external/out-of-repo caller still constructing it directly; remove
it (and ``BaseRunner``) once that window closes.
"""

import importlib
import logging
import warnings

from ..config import Config


class UnifiedRunner:
    def __init__(self, runner_type, config: Config = None, **kwargs):
        warnings.warn(
            "UnifiedRunner is deprecated; new compute submission should go "
            "through hastegeo.core.runners.execution_service."
            "ComputeExecutionService once the target adapter implements "
            "ComputeRunner (see ADR-0005).",
            DeprecationWarning,
            stacklevel=2,
        )
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
        # Debug logging to see what parameters are being passed through.
        # Never log the raw resource_files_for_upload dict: its values
        # carry input blob URLs (and, depending on caller, a signed query
        # string) — only the destination-relative path keys and a count
        # are safe to log.
        logger = logging.getLogger(__name__)
        logger.info(
            f"UnifiedRunner.add_task called with job_id={job_id}, "
            f"task_id={task_id}, kwargs keys={list(kwargs.keys())}"
        )
        resource_files = kwargs.get("resource_files_for_upload")
        if resource_files:
            logger.info(
                f"resource_files_for_upload present: "
                f"{len(resource_files)} input(s), "
                f"destinations={list(resource_files.keys())}"
            )
        else:
            logger.info("resource_files_for_upload NOT present in kwargs")
        return self.runner.add_task(job_id, task_id, **kwargs)

    def cleanup_task(self, job_id, task_id):
        return self.runner.cleanup_task(job_id, task_id)

    def cancel_task(self, job_id, task_id):
        return self.runner.cancel_task(job_id, task_id)
