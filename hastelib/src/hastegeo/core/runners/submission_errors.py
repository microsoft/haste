# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Submission classification shared by legacy and backend-neutral adapters."""

from azure.batch.models import BatchErrorException
from azure.core.exceptions import ServiceRequestError, ServiceResponseError
from msrest.exceptions import ClientRequestError
from requests import exceptions as request_errors
from tenacity import RetryError
from urllib3 import exceptions as http_errors

SUBMISSION_ERRORS = (
    ConnectionError,
    TimeoutError,
    request_errors.RequestException,
    ClientRequestError,
    ServiceRequestError,
    ServiceResponseError,
    BatchErrorException,
    RetryError,
)


def is_server_error(exception: BaseException | None) -> bool:
    if not isinstance(exception, BatchErrorException):
        return False
    status = getattr(getattr(exception, "response", None), "status_code", None)
    return isinstance(status, int) and 500 <= status < 600


def unwrap_retry_error(
    exception: BaseException | None,
) -> BaseException | None:
    """Inspect an exhausted retry without restarting an outer retry budget."""
    if isinstance(exception, RetryError):
        attempt = exception.last_attempt
        if attempt is not None and attempt.failed:
            return attempt.exception()
    return exception


def is_ambiguous_submission_error(error: BaseException | None) -> bool:
    error = unwrap_retry_error(error)
    if isinstance(error, ClientRequestError):
        return is_ambiguous_submission_error(error.inner_exception)
    if isinstance(error, (ServiceRequestError, ServiceResponseError)):
        return error.inner_exception is None or is_ambiguous_submission_error(
            error.inner_exception
        )
    if isinstance(error, (request_errors.SSLError, request_errors.ProxyError)):
        return False
    if isinstance(error, request_errors.RetryError):
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
