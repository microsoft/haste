# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Shared optional telemetry reads and timestamped workflow history."""

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterable, Optional, Union

from .metadata import STATUS_HISTORY_TRIMMED

if TYPE_CHECKING:
    from ..runners.base import BaseRunner

TrainingOutput = Optional[Union[str, Iterable[bytes]]]
_TRIMMED_SUFFIX = f": {STATUS_HISTORY_TRIMMED}"


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


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _trimmed_through(status_message: Optional[str]) -> Optional[datetime]:
    """Return the newest history-trim marker time, if history was trimmed.

    Trimming stamps its marker with the oldest retained entry's time, so every
    dropped workflow record is at or before that time.
    """
    newest = None
    for line in (status_message or "").splitlines():
        if not line.endswith(_TRIMMED_SUFFIX):
            continue
        try:
            marker = _parse_timestamp(line[: -len(_TRIMMED_SUFFIX)])
        except ValueError:
            continue
        if newest is None or marker > newest:
            newest = marker
    return newest


def workflow_progress_updates(
    content: str,
    status_message: Optional[str],
    *,
    logger: logging.Logger,
) -> tuple[bool, list[tuple[str, str]]]:
    """Return whether progress exists and its unseen timestamped records.

    Records that history trimming already dropped count as seen; re-adding
    them would evict newer entries on every poll.
    """
    have_progress = False
    recorded = set((status_message or "").splitlines())
    trimmed_through = _trimmed_through(status_message)
    updates = []
    for line in content.splitlines():
        if not line:
            continue
        timestamp, separator, message = line.partition("|")
        try:
            if not separator or not message.strip():
                raise ValueError("missing progress message")
            recorded_at = _parse_timestamp(timestamp)
        except ValueError:
            logger.warning("Ignoring malformed workflow progress line")
            continue
        have_progress = True
        entry = f"{timestamp}: {message}"
        if entry in recorded or (
            trimmed_through is not None and recorded_at <= trimmed_through
        ):
            continue
        updates.append((timestamp, message))
        recorded.add(entry)
    return have_progress, updates
