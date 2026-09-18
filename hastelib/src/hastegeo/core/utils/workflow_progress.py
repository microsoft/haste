# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Shared optional telemetry reads and timestamped workflow history."""

import logging
from datetime import datetime
from typing import Callable, Iterable, Optional, Union

TrainingOutput = Optional[Union[str, Iterable[bytes]]]


def read_training_output(
    reader: Callable[[], TrainingOutput],
    *,
    task_id: str,
    filename: str,
    logger: logging.Logger,
) -> tuple[TrainingOutput, bool]:
    """Use a caller-bound reader and report whether optional output failed."""
    try:
        return reader(), False
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
