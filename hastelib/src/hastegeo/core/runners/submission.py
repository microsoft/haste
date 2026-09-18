# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

from typing import Any

from ..utils.logs import Logger
from .base import BaseRunner
from .submission_errors import SUBMISSION_ERRORS, is_ambiguous_submission_error
from .unified_runner import UnifiedRunner


class TaskSubmissionPendingError(RuntimeError):
    """Submission may have been accepted; reconcile the same pending identity."""


def submit_task(
    runner: BaseRunner | UnifiedRunner,
    job_id: str,
    task_id: str,
    **kwargs: Any,
) -> tuple[str, str]:
    try:
        return runner.add_task(job_id=job_id, task_id=task_id, **kwargs)
    except SUBMISSION_ERRORS as error:
        if not is_ambiguous_submission_error(error):
            raise
        Logger.get_logger(__name__).error(
            "Submission of %s/%s interrupted (%s); retaining pending identity",
            job_id,
            task_id,
            type(error).__name__,
        )
        raise TaskSubmissionPendingError(
            "Task submission interrupted; reconcile the pending identity"
        ) from error
