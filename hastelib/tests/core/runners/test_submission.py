# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import pytest
from azure.batch import BatchServiceClient
from azure.batch.models import TaskAddParameter
from azure.core.exceptions import (
    ClientAuthenticationError,
    SerializationError,
    ServiceRequestError,
    ServiceResponseError,
)
from hastegeo.core.runners.base import BaseRunner
from hastegeo.core.runners.submission import (
    TaskSubmissionPendingError,
    submit_task,
)
from msrest.exceptions import (
    AuthenticationError,
    ClientRequestError,
    ValidationError,
)
from requests import exceptions as request_errors
from urllib3.exceptions import MaxRetryError, NewConnectionError, ResponseError

from hastelib.tests.core.runners.test_azure_batch_node_errors import (
    _batch_error,
    _retry_error,
)


@pytest.fixture(autouse=True)
def no_network(mocker) -> None:
    mocker.patch(
        "requests.sessions.Session.request",
        side_effect=AssertionError("Unit test attempted network access"),
    )


@pytest.mark.parametrize(
    "error",
    [
        ConnectionResetError("connection reset"),
        TimeoutError("acceptance timed out"),
        request_errors.ConnectTimeout("connection timed out"),
        request_errors.ReadTimeout("response lost"),
        request_errors.ConnectionError("connection lost"),
        request_errors.ChunkedEncodingError("response truncated"),
        request_errors.ContentDecodingError("response unreadable"),
        ClientRequestError(
            "request failed", request_errors.ReadTimeout("response lost")
        ),
        ServiceRequestError("transport unavailable"),
        ServiceRequestError(
            "connection failed", error=NewConnectionError(None, "unavailable")
        ),
        ServiceResponseError("response lost"),
        ServiceResponseError(
            "response lost", error=request_errors.ReadTimeout("response lost")
        ),
        ClientRequestError(
            "request failed",
            request_errors.RetryError(
                MaxRetryError(
                    None,
                    "https://batch.example.invalid",
                    ResponseError("server response retries exhausted"),
                )
            ),
        ),
        _batch_error("InternalServerError", 500),
        _retry_error(_batch_error("ServerBusy", 503)),
    ],
)
def test_transport_and_ambiguous_acceptance_failures_retain_identity(
    mocker, error: Exception
) -> None:
    runner = mocker.Mock(spec=BaseRunner)
    runner.add_task.side_effect = error

    with pytest.raises(TaskSubmissionPendingError) as caught:
        submit_task(runner, "job", "task", command="run")

    assert caught.value.__cause__ is error
    runner.add_task.assert_called_once_with(
        job_id="job", task_id="task", command="run"
    )


@pytest.mark.parametrize(
    "error",
    [
        ValueError("Local execution identity already has another request"),
        KeyError("batch_url"),
        RuntimeError("legacy task has no receipt"),
        OSError("unspecified local I/O failure"),
        PermissionError("receipt directory is not writable"),
        request_errors.RequestException("unspecified request failure"),
        request_errors.InvalidURL("invalid provider URL"),
        request_errors.SSLError("invalid certificate"),
        request_errors.ProxyError("proxy configuration rejected"),
        request_errors.HTTPError("forbidden"),
        request_errors.RetryError("unspecified retry failure"),
        ClientRequestError("unspecified client failure"),
        ClientRequestError(
            "request failed", request_errors.InvalidURL("invalid provider URL")
        ),
        ClientRequestError(
            "request failed", request_errors.SSLError("invalid certificate")
        ),
        ClientRequestError(
            "request failed", AuthenticationError("credentials rejected")
        ),
        ServiceRequestError(
            "request failed", error=request_errors.SSLError("bad certificate")
        ),
        ServiceResponseError(
            "request failed", error=request_errors.InvalidURL("invalid URL")
        ),
        ValidationError("required", "task_id", ""),
        ClientAuthenticationError("credentials rejected"),
        SerializationError("invalid task parameters"),
        _batch_error("InvalidPropertyValue", 400),
        _batch_error("AuthenticationFailed", 401),
        _batch_error("AuthorizationFailure", 403),
        _batch_error("TaskExists", 409),
        _retry_error(_batch_error("AuthorizationFailure", 403)),
        _retry_error(ValueError("invalid provider configuration")),
    ],
)
def test_deterministic_and_unclassified_failures_propagate_unchanged(
    mocker, error: Exception
) -> None:
    runner = mocker.Mock(spec=BaseRunner)
    runner.add_task.side_effect = error

    with pytest.raises(type(error)) as caught:
        submit_task(runner, "job", "task")

    assert caught.value is error
    runner.add_task.assert_called_once_with(job_id="job", task_id="task")


def test_explicit_pending_error_is_not_wrapped_again(mocker) -> None:
    runner = mocker.Mock(spec=BaseRunner)
    error = TaskSubmissionPendingError("receipt persisted; response lost")
    runner.add_task.side_effect = error

    with pytest.raises(TaskSubmissionPendingError) as caught:
        submit_task(runner, "job", "task")

    assert caught.value is error


def test_success_preserves_the_routed_two_string_identity(mocker) -> None:
    runner = mocker.Mock(spec=BaseRunner)
    runner.add_task.return_value = ("routed-job", "task")

    assert submit_task(runner, "job", "task", command="run") == (
        "routed-job",
        "task",
    )
    runner.add_task.assert_called_once_with(
        job_id="job", task_id="task", command="run"
    )


@pytest.mark.parametrize(
    "cause,expected_type",
    [
        (
            request_errors.ReadTimeout("response lost"),
            TaskSubmissionPendingError,
        ),
        (request_errors.InvalidURL("invalid URL"), ClientRequestError),
        (request_errors.SSLError("invalid certificate"), ClientRequestError),
    ],
)
def test_track_one_batch_transport_is_classified_by_its_inner_exception(
    mocker, cause: Exception, expected_type: type[Exception]
) -> None:
    request = mocker.patch(
        "requests.sessions.Session.request", side_effect=cause
    )
    runner = mocker.Mock(spec=BaseRunner)
    with BatchServiceClient(
        mocker.Mock(), batch_url="https://batch.example.invalid"
    ) as client:

        def add_task(job_id: str, task_id: str) -> tuple[str, str]:
            client.task.add(
                job_id, TaskAddParameter(id=task_id, command_line="run")
            )
            return job_id, task_id

        runner.add_task.side_effect = add_task
        with pytest.raises(expected_type) as caught:
            submit_task(runner, "job", "task")

    sdk_error = (
        caught.value.__cause__
        if expected_type is TaskSubmissionPendingError
        else caught.value
    )
    assert isinstance(sdk_error, ClientRequestError)
    assert sdk_error.inner_exception is cause
    request.assert_called_once()
