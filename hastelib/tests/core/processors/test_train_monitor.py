# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json

from hastegeo.core.config import Config
from hastegeo.core.models.projects import Model, TrainingJob
from hastegeo.core.processors.train import (
    TRAINING_IN_PROGRESS_MESSAGE,
    TrainPostprocessor,
)
from hastegeo.core.utils.metadata import STATUS_HISTORY_TRIMMED, MetadataUtils

STATUS = Config.get_status_types()
# Azure Storage rejects larger queue messages with RequestBodyTooLarge.
QUEUE_MESSAGE_LIMIT_BYTES = 64 * 1024
# The monitor polls about every 32 seconds, so this is nearly nine hours.
POLLS = 1000
SECONDS_PER_POLL = 32


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
