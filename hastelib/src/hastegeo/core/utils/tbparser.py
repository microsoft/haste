# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json
from datetime import datetime, timezone

from tensorboard.backend.event_processing.event_accumulator import (  # type: ignore
    EventAccumulator,
)


def parse_tb_event_logs(log_file_path):
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
        scalar_events = ea.Scalars(tag)
        events_by_tag[tag] = {event.step: event for event in scalar_events}
        all_events.extend(scalar_events)
    start_timestamp = (
        min(e.wall_time for e in all_events) if all_events else None
    )

    # Process epoch events (as in original parse_tf_event_logs)
    epoch_events = events_by_tag.get("epoch", {})
    latest_epoch_events = {}
    for step, event in epoch_events.items():
        epoch_value = event.value
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
                round(acc_event.value, 6) if acc_event else None
            ),
            "loss": round(loss_event.value, 6) if loss_event else None,
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

    return start_timestamp, json.dumps(result, default=str)


def calculate_metrics(
    logs, maxEpochs, time_field="elapsedDurationInMinutes", epoch_field="epoch"
):
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
    if logs is not None:
        try:
            logs = json.loads(logs)
        except (TypeError, json.JSONDecodeError):
            return None
        epoch_0_time = None
        for log in logs:
            if time_field in log and log[epoch_field] == 0:
                epoch_0_time = log[time_field]
                break
        if epoch_0_time:
            total_epochs = int(maxEpochs) if maxEpochs else 0
            total_elapsed_time = sum(
                log[time_field] for log in logs if time_field in log
            )
            total_elapsed_time = round(total_elapsed_time, 2)
            completed_epochs_logs = list(
                log for log in logs if log[epoch_field] < total_epochs
            )
            completed_epochs = max(0, len(completed_epochs_logs) - 1)

            if completed_epochs > 0:
                avg_time_per_epoch = round(epoch_0_time, 2)
                total_time = total_epochs * avg_time_per_epoch
                time_to_completion = round(
                    max(0, total_time - total_elapsed_time), 2
                )
                time_per_epoch = round(avg_time_per_epoch, 2)
            else:
                time_to_completion = None
                time_per_epoch = None
            return {
                "completed_epochs": completed_epochs,
                "approx_time_to_complete": time_to_completion,
                "total_elapsed_time": total_elapsed_time,
                "time_per_epoch": time_per_epoch,
            }
    return None
