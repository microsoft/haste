# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json
import math
from datetime import datetime, timezone
from typing import Optional, Union

from hastegeo.core.utils.logs import Logger
from tensorboard.backend.event_processing.event_accumulator import (  # type: ignore
    EventAccumulator,
)

logger = Logger.get_logger(__name__)


def _finite_number(value: object) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _metric_value(event, tag: str) -> Optional[float]:
    if event is None:
        return None
    value = _finite_number(event.value)
    if value is None:
        logger.warning("TensorBoard metric %s is non-finite; unavailable", tag)
        return None
    return round(value, 6)


def parse_tb_event_logs(log_file_path: str) -> tuple[Optional[str], str]:
    """
    Parses TensorBoard event logs to extract epoch, accuracy, and loss information.

    Args:
        log_file_path (str): The file path to the TensorBoard event log file.

    Returns:
        tuple: A tuple containing:
            - start_timestamp (str): The start timestamp of the events in UTC formatted as '%Y-%m-%d %H:%M:%S'.
            - result (str): A JSON string containing a list of dictionaries, each representing an epoch with the following keys:
                - 'epoch' (int): The epoch number.
                - 'elapsedDurationInMinutes' (float): The duration of the epoch in minutes.
                - 'multiclassAccuracy' (float): The multiclass accuracy for the epoch.
                - 'loss' (float): The loss for the epoch.
                - 'wallTime' (str): The wall time of the epoch event in UTC formatted as '%Y-%m-%d %H:%M:%S'.
    """

    # Load events (merged load_events)
    ea = EventAccumulator(log_file_path)
    ea.Reload()
    events_by_tag = {}
    all_events = []
    for tag in ea.Tags().get("scalars", []):
        scalar_events = []
        for event in ea.Scalars(tag):
            wall_time = _finite_number(event.wall_time)
            try:
                if wall_time is None:
                    raise ValueError("non-finite timestamp")
                datetime.fromtimestamp(wall_time, timezone.utc)
            except (ValueError, OverflowError, OSError):
                logger.warning(
                    "TensorBoard metric %s has an invalid timestamp; ignored",
                    tag,
                )
                continue
            scalar_events.append(event)
        events_by_tag[tag] = {event.step: event for event in scalar_events}
        all_events.extend(scalar_events)
    start_timestamp = (
        min(e.wall_time for e in all_events) if all_events else None
    )

    # Process epoch events (as in original parse_tf_event_logs)
    epoch_events = events_by_tag.get("epoch", {})
    latest_epoch_events = {}
    for step, event in epoch_events.items():
        epoch_value = _finite_number(event.value)
        if (
            epoch_value is None
            or epoch_value < 0
            or not epoch_value.is_integer()
        ):
            logger.warning("TensorBoard epoch value is invalid; ignored")
            continue
        if (
            epoch_value not in latest_epoch_events
            or step > latest_epoch_events[epoch_value].step
        ):
            latest_epoch_events[epoch_value] = event

    accuracy_events = events_by_tag.get("train_MulticlassAccuracy", {})
    loss_events = events_by_tag.get("train_loss", {})

    result = []
    sorted_epochs = sorted(latest_epoch_events)
    prev_wall_time = None

    for epoch in sorted_epochs:
        epoch_event = latest_epoch_events[epoch]
        step = epoch_event.step

        # Inline the logic of find_latest_event_at_or_before for accuracy_events
        acc_event = None
        for ev_step, event in accuracy_events.items():
            if ev_step <= step and (
                acc_event is None or ev_step > acc_event.step
            ):
                acc_event = event

        # Inline the logic of find_latest_event_at_or_before for loss_events
        loss_event = None
        for ev_step, event in loss_events.items():
            if ev_step <= step and (
                loss_event is None or ev_step > loss_event.step
            ):
                loss_event = event

        # Calculate duration from the previous epoch or from start timestamp
        if prev_wall_time is not None:
            epoch_duration = epoch_event.wall_time - prev_wall_time
        else:
            epoch_duration = epoch_event.wall_time - start_timestamp

        record = {
            "epoch": int(epoch_event.value),
            "elapsedDurationInMinutes": (
                round(epoch_duration / 60, 2)
                if epoch_duration is not None
                else None
            ),
            "multiclassAccuracy": (
                _metric_value(acc_event, "train_MulticlassAccuracy")
            ),
            "loss": _metric_value(loss_event, "train_loss"),
            "wallTime": datetime.fromtimestamp(
                epoch_event.wall_time, timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S"),
        }
        result.append(record)
        prev_wall_time = epoch_event.wall_time

    if start_timestamp is not None:
        start_timestamp = datetime.fromtimestamp(
            start_timestamp, timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S")

    return start_timestamp, json.dumps(result, allow_nan=False)


def calculate_metrics(
    logs: Optional[str],
    maxEpochs: Union[str, int, None],
    time_field: str = "elapsedDurationInMinutes",
    epoch_field: str = "epoch",
    *,
    job_completed: bool = False,
) -> Optional[dict]:
    """
    Calculate completion metrics from TensorBoard logs.

    Args:
        logs (str): JSON string of logs containing epoch and time information.
        maxEpochs (int): Maximum number of epochs.
        time_field (str): The field name in logs that contains elapsed time information. Default is 'elapsedDurationInMinutes'.
        epoch_field (str): The field name in logs that contains epoch information. Default is 'epoch'.

    Returns:
        dict: A dictionary containing the following keys:
            - 'completed_epochs' (int): The number of completed epochs.
            - 'approx_time_to_complete' (float): The approximate time to complete the remaining epochs.
            - 'total_elapsed_time' (float): The total elapsed time.
            - 'time_per_epoch' (float): The average time per epoch.
    """
    if logs is None:
        return None
    try:
        records = json.loads(logs)
        target = int(maxEpochs) if maxEpochs not in (None, "") else None
    except (TypeError, ValueError):
        logger.warning("Training progress has invalid JSON or epoch target")
        return None
    if not isinstance(records, list) or (target is not None and target < 1):
        logger.warning("Training progress has invalid records or epoch target")
        return None
    if not records:
        return None

    durations = {}
    for record in records:
        if not isinstance(record, dict):
            logger.warning("Training progress record is not an object")
            return None
        epoch = _finite_number(record.get(epoch_field))
        duration = _finite_number(record.get(time_field))
        if (
            epoch is None
            or epoch < 0
            or not epoch.is_integer()
            or duration is None
            or duration < 0
        ):
            logger.warning(
                "Training progress has an invalid epoch or duration"
            )
            return None
        durations[int(epoch)] = duration

    current_epoch = max(durations)
    completed_epochs = current_epoch + (1 if job_completed else 0)
    if target is not None:
        completed_epochs = min(completed_epochs, target)
    completed_durations = [
        duration
        for epoch, duration in durations.items()
        if (job_completed or epoch < current_epoch) and duration > 0
    ]
    time_per_epoch = (
        sum(completed_durations) / len(completed_durations)
        if completed_durations
        else None
    )
    elapsed = sum(durations.values())
    if not math.isfinite(elapsed) or (
        time_per_epoch is not None and not math.isfinite(time_per_epoch)
    ):
        logger.warning("Training progress duration exceeds numeric limits")
        return None
    remaining = None
    if job_completed:
        remaining = 0.0
    elif time_per_epoch is not None and target is not None:
        current_duration = durations[current_epoch]
        try:
            remaining = max(
                0.0,
                (target - completed_epochs) * time_per_epoch
                - current_duration,
            )
        except OverflowError:
            logger.warning("Training ETA exceeds numeric limits; unavailable")
            remaining = None
        if remaining is not None and not math.isfinite(remaining):
            logger.warning("Training ETA exceeds numeric limits; unavailable")
            remaining = None
    return {
        "completed_epochs": completed_epochs,
        "approx_time_to_complete": (
            round(remaining, 2) if remaining is not None else None
        ),
        "total_elapsed_time": round(elapsed, 2),
        "time_per_epoch": (
            round(time_per_epoch, 2) if time_per_epoch is not None else None
        ),
    }
