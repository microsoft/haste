# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json
from datetime import datetime, timedelta, timezone

from hastegeo.core.config import Config
from hastegeo.core.models.projects import Model, TrainingJob
from hastegeo.core.processors.train import (
    TRAINING_IN_PROGRESS_MESSAGE,
    TrainPostprocessor,
)
from hastegeo.core.utils.metadata import (
    STATUS_HISTORY_TRIMMED,
    MetadataUtils,
    queued_message_size,
)

STATUS = Config.get_status_types()
# Azure Storage rejects larger queue messages with RequestBodyTooLarge.
QUEUE_MESSAGE_LIMIT_BYTES = 64 * 1024
# The monitor polls about every 32 seconds, so this is nearly nine hours.
POLLS = 1000
SECONDS_PER_POLL = 32


def _epoch_logs(epochs: int) -> str:
    """Per-epoch TensorBoard summaries, shaped like parse_tb_event_logs."""
    return json.dumps(
        [
            {
                "epoch": epoch,
                "step": (epoch + 1) * 1024 - 1,
                "timestamp": f"2026-09-22T19:{epoch % 60:02d}:00+00:00",
                "train_loss": 0.1234567 + epoch,
                "val_loss": 0.2345678 + epoch,
                "train_MulticlassAccuracy": 0.8765432,
                "val_MulticlassAccuracy": 0.7654321,
                "train_MulticlassJaccardIndex": 0.6543210,
                "val_MulticlassJaccardIndex": 0.5432109,
            }
            for epoch in range(epochs)
        ]
    )


def _submitted_model() -> Model:
    history = MetadataUtils.append_status_message("", "Queued for training")
    history = MetadataUtils.append_status_message(
        history, "Submitting training job"
    )
    history = MetadataUtils.append_status_message(
        history, "Training submitted with task id trn-1"
    )
    return Model(
        modelId="6283",
        projectId="project-1",
        imageLayerId="layer-1",
        name="Spokane-Standard---Training-Demonstration",
        maxEpochs="3",
        totalSteps=4,
        status=STATUS.IN_PROGRESS.value,
        statusMessage=history,
        trainingJob=TrainingJob(
            jobId="job-1", taskId="trn-1", status=STATUS.IN_PROGRESS.value
        ),
    )


def _monitor(mocker) -> TrainPostprocessor:
    processor = TrainPostprocessor.__new__(TrainPostprocessor)
    processor.config = mocker.Mock()
    processor.config.get_status_types.return_value = STATUS
    processor.logger = mocker.Mock()
    processor.runner = mocker.Mock()
    processor.runner.get_task_status.return_value = STATUS.IN_PROGRESS.value
    processor.queue_client = mocker.Mock()
    epoch_logs = json.dumps(
        [{"epoch": epoch, "train_loss": 0.5} for epoch in range(3)]
    )
    mocker.patch.object(
        processor,
        "_get_training_logs",
        return_value=("2026-09-22T19:24:47+00:00", epoch_logs),
    )

    def update_metrics(job_completed=False):
        poll = processor.queue_client.put_message.call_count + 1
        job = processor.model_data.trainingJob
        job.completedEpochs = str(min(2, poll // 400))
        job.approxMinutesToComplete = str(max(1, 600 - poll // 2))
        job.totalElapsedTime = f"{poll * SECONDS_PER_POLL / 60:.2f}"
        return True

    mocker.patch.object(
        processor,
        "_calculate_upsert_training_metrics",
        side_effect=update_metrics,
    )
    return processor


class TestTrainingMonitorQueueMessage:
    def test_long_training_stays_under_the_queue_message_limit(self, mocker):
        processor = _monitor(mocker)
        payload = json.dumps(_submitted_model().dict())

        for _ in range(POLLS):
            # Each poll starts from the message the previous one queued,
            # exactly as the queue trigger hands it over.
            processor.model_data = Model(**json.loads(payload))
            processor.process()
            payload = processor.queue_client.put_message.call_args.args[0]
            assert len(payload.encode("utf-8")) < QUEUE_MESSAGE_LIMIT_BYTES

        assert processor.queue_client.put_message.call_count == POLLS
        history = json.loads(payload)["statusMessage"]
        assert history.count(TRAINING_IN_PROGRESS_MESSAGE) == 1
        latest = f"{POLLS * SECONDS_PER_POLL / 60:.2f}"
        assert f"elapsedDurationInMinutes: {latest}\n" in history
        assert "Training submitted with task id trn-1" in history

    def test_completion_follows_the_latest_progress(self, mocker):
        processor = _monitor(mocker)
        processor.runner.get_task_status.side_effect = [
            STATUS.IN_PROGRESS.value,
            STATUS.IN_PROGRESS.value,
            STATUS.COMPLETED.value,
        ]
        processor.model_data = _submitted_model()

        for _ in range(3):
            processor.process()

        history = processor.model_data.statusMessage
        assert processor.model_data.status == STATUS.COMPLETED.value
        assert history.count(TRAINING_IN_PROGRESS_MESSAGE) == 1
        assert history.index(TRAINING_IN_PROGRESS_MESSAGE) < history.index(
            "Training job completed successfully"
        )

    def test_non_ascii_history_still_fits_the_queue_message(self, mocker):
        # Under 16 KiB of characters, but json.dumps escapes each of these to
        # six bytes: counted by characters it would stay and overflow.
        processor = _monitor(mocker)
        model = _submitted_model()
        model.statusMessage += "".join(
            f"\n2026-09-22T19:{minute:02d}:00+00:00: " + "训练失败" * 75
            for minute in range(45)
        )
        processor.model_data = model

        processor.process()

        payload = processor.queue_client.put_message.call_args.args[0]
        assert len(payload.encode("utf-8")) < QUEUE_MESSAGE_LIMIT_BYTES
        history = json.loads(payload)["statusMessage"]
        assert STATUS_HISTORY_TRIMMED in history
        assert history.count(TRAINING_IN_PROGRESS_MESSAGE) == 1

    def test_oversized_legacy_history_is_trimmed_without_new_logs(
        self, mocker
    ):
        # A record queued before the limit existed, with an update appended
        # on every poll, and a poll that finds no new training logs to add.
        processor = _monitor(mocker)
        processor._get_training_logs.return_value = (None, None)
        started = datetime(2026, 9, 22, 19, 20, tzinfo=timezone.utc)
        model = _submitted_model()
        for poll in range(500):
            timestamp = (
                started + timedelta(seconds=poll * SECONDS_PER_POLL)
            ).isoformat()
            message = (
                f"{TRAINING_IN_PROGRESS_MESSAGE}\n"
                "trainStartTime: 2026-09-22T19:24:47+00:00\n"
                "epoch: 1\n"
                f"elapsedDurationInMinutes: {poll * SECONDS_PER_POLL / 60:.2f}\n"
                "approxMinutesToComplete: 120"
            )
            model.statusMessage = MetadataUtils.append_status_message(
                model.statusMessage, message, timestamp=timestamp
            )
        newest_entry = f"\n{timestamp}: {message}"
        legacy = json.dumps(model.dict())
        assert len(legacy.encode("utf-8")) > QUEUE_MESSAGE_LIMIT_BYTES
        processor.model_data = model

        processor.process()

        payload = processor.queue_client.put_message.call_args.args[0]
        assert len(payload.encode("utf-8")) < QUEUE_MESSAGE_LIMIT_BYTES
        history = json.loads(payload)["statusMessage"]
        assert STATUS_HISTORY_TRIMMED in history
        assert history.endswith(newest_entry)

    def test_large_training_logs_leave_less_room_for_history(self, mocker):
        processor = _monitor(mocker)
        logs = _epoch_logs(epochs=180)
        processor._get_training_logs.return_value = (
            "2026-09-22T19:24:47+00:00",
            logs,
        )
        model = _submitted_model()
        model.statusMessage += "".join(
            f"\n2026-09-22T19:{n // 60:02d}:{n % 60:02d}+00:00: "
            f"Epoch {n} checkpoint saved to checkpoint/epoch={n}.ckpt"
            for n in range(300)
        )
        processor.model_data = model

        processor.process()

        # The saved record keeps a 16 KiB history, which together with these
        # logs is over the limit: the queued copy must make room.
        unfitted = json.dumps(processor.model_data.dict())
        assert queued_message_size(unfitted) > QUEUE_MESSAGE_LIMIT_BYTES
        payload = processor.queue_client.put_message.call_args.args[0]
        assert queued_message_size(payload) <= QUEUE_MESSAGE_LIMIT_BYTES
        queued = json.loads(payload)
        assert queued["trainingJob"]["logs"] == logs
        assert STATUS_HISTORY_TRIMMED in queued["statusMessage"]
        assert queued["statusMessage"].count(TRAINING_IN_PROGRESS_MESSAGE) == 1

    def test_oversized_training_logs_are_left_out_of_the_queue(self, mocker):
        processor = _monitor(mocker)
        logs = _epoch_logs(epochs=400)
        assert len(logs) > QUEUE_MESSAGE_LIMIT_BYTES
        processor._get_training_logs.return_value = (
            "2026-09-22T19:24:47+00:00",
            logs,
        )
        processor.model_data = _submitted_model()

        processor.process()

        payload = processor.queue_client.put_message.call_args.args[0]
        assert queued_message_size(payload) <= QUEUE_MESSAGE_LIMIT_BYTES
        assert json.loads(payload)["trainingJob"]["logs"] is None
        # The record the trigger saves keeps them; the next poll re-reads
        # them from the task anyway.
        assert processor.model_data.trainingJob.logs == logs
