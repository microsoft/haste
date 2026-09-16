# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Shared optional telemetry reads and timestamped workflow history."""

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Iterable, Optional, Union

if TYPE_CHECKING:
    from ..runners.base import BaseRunner

TrainingOutput = Optional[Union[str, Iterable[bytes]]]


def read_training_output(
    runner: "BaseRunner",
    *,
    job_id: str,
    task_id: str,
    filename: str,
    logger: logging.Logger,
    as_chunks: bool = False,
) -> tuple[TrainingOutput, bool]:
    """Return optional output and whether a provider read failed."""
    try:
        return (
            runner.get_filecontent_from_task(
                job_id=job_id,
                task_id=task_id,
                filename=filename,
                as_chunk=as_chunks,
            ),
            False,
        )
    except Exception as error:
        logger.warning(
            "Training telemetry %s is unavailable for task %s (%s)",
            filename,
            task_id,
            type(error).__name__,
        )
        return None, True


def workflow_progress_updates(
    content: str,
    status_message: Optional[str],
    *,
    logger: logging.Logger,
) -> tuple[bool, list[tuple[str, str]]]:
    """Return whether progress exists and its unseen timestamped records."""
    have_progress = False
    recorded = set((status_message or "").splitlines())
    updates = []
    for line in content.splitlines():
        if not line:
            continue
        timestamp, separator, message = line.partition("|")
        try:
            if not separator or not message.strip():
                raise ValueError("missing progress message")
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            logger.warning("Ignoring malformed workflow progress line")
            continue
        have_progress = True
        entry = f"{timestamp}: {message}"
        if entry not in recorded:
            updates.append((timestamp, message))
            recorded.add(entry)
    return have_progress, updates
