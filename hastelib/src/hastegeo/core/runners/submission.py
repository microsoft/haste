# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

from typing import Any

from azure.batch.models import BatchErrorException
from azure.core.exceptions import ServiceRequestError, ServiceResponseError
from msrest.exceptions import ClientRequestError
from requests import exceptions as request_errors
from tenacity import RetryError
from urllib3 import exceptions as http_errors

from ..utils.logs import Logger
from .azure_batch import is_server_error, unwrap_retry_error
from .base import BaseRunner
from .unified_runner import UnifiedRunner


class TaskSubmissionPendingError(RuntimeError):
    """Submission may have been accepted; reconcile the same pending identity."""


def _is_ambiguous_submission_error(error: BaseException | None) -> bool:
    error = unwrap_retry_error(error)
    # Track-1 Batch also wraps invalid URLs and OAuth failures in this type.
    if isinstance(error, ClientRequestError):
        return _is_ambiguous_submission_error(error.inner_exception)
    if isinstance(error, (ServiceRequestError, ServiceResponseError)):
        return error.inner_exception is None or _is_ambiguous_submission_error(
            error.inner_exception
        )
    if isinstance(error, (request_errors.SSLError, request_errors.ProxyError)):
        return False
    if isinstance(error, request_errors.RetryError):
        # Requests wraps exhausted HTTP-status retries in this specific shape.
        cause = error.args[0] if error.args else None
        return isinstance(cause, http_errors.MaxRetryError) and isinstance(
            cause.reason, http_errors.ResponseError
        )
    return isinstance(
        error,
        (
            ConnectionError,
            TimeoutError,
            request_errors.ConnectionError,
            request_errors.Timeout,
            request_errors.ChunkedEncodingError,
            request_errors.ContentDecodingError,
            http_errors.ProtocolError,
            http_errors.TimeoutError,
        ),
    ) or is_server_error(error)


def submit_task(
    runner: BaseRunner | UnifiedRunner,
    job_id: str,
    task_id: str,
    **kwargs: Any,
) -> tuple[str, str]:
    try:
        return runner.add_task(job_id=job_id, task_id=task_id, **kwargs)
    except (
        ConnectionError,
        TimeoutError,
        request_errors.RequestException,
        ClientRequestError,
        ServiceRequestError,
        ServiceResponseError,
        BatchErrorException,
        RetryError,
    ) as error:
        if not _is_ambiguous_submission_error(error):
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
