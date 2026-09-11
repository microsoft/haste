# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

from typing import Any, Callable

from ..models.compute import (
    ComputeJobHandle,
    ComputeJobSpec,
    ComputeJobState,
    SubmissionIndeterminateError,
)
from .execution_service import ComputeExecutionService


class DeferredCleanupService(ComputeExecutionService):
    """Persist accepted handles and defer finalization until metadata commits."""

    def __init__(
        self,
        service: ComputeExecutionService,
        before_submit: Callable[[ComputeJobSpec], None],
        record_submission: Callable[[ComputeJobHandle], bool],
    ) -> None:
        self.service = service
        self.before_submit = before_submit
        self.record_submission = record_submission
        self.cleanup: list[ComputeJobHandle] = []

    def submit(self, spec: ComputeJobSpec, **kwargs: Any) -> ComputeJobHandle:
        self.before_submit(spec)
        handle = self.service.submit(spec, **kwargs)
        try:
            current = self.record_submission(handle)
        except Exception as error:
            raise SubmissionIndeterminateError(
                "Compute accepted the job, but recording its handle was "
                f"interrupted ({type(error).__name__}); reconciliation required"
            ) from error
        if not current:
            self.service.cancel(handle)
            self.service.finalize(handle)
            raise RuntimeError("The accepted execution was superseded")
        return handle

    def get_status(self, handle: ComputeJobHandle) -> ComputeJobState:
        return self.service.get_status(handle)

    def read_output(
        self, handle: ComputeJobHandle, relative_path: str, **kwargs: Any
    ) -> Any:
        return self.service.read_output(handle, relative_path, **kwargs)

    def cancel(self, handle: ComputeJobHandle) -> None:
        self.service.cancel(handle)

    def finalize(self, handle: ComputeJobHandle) -> None:
        if handle not in self.cleanup:
            self.cleanup.append(handle.model_copy(deep=True))
