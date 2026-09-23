# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json

from hastegeo.core.config import Config
from hastegeo.core.models.projects import ModelArtifacts, ZipJob
from hastegeo.core.processors.artifacts import (
    ZIP_IN_PROGRESS_MESSAGE,
    ArtifactProcessor,
)
from hastegeo.core.utils.metadata import MetadataUtils

STATUS = Config.get_status_types()


class TestArtifactProcessor:
    def test_in_progress_polls_keep_one_progress_entry(self, mocker):
        processor = ArtifactProcessor.__new__(ArtifactProcessor)
        processor.config = mocker.Mock()
        processor.config.get_status_types.return_value = STATUS
        processor.logger = mocker.Mock()
        processor.runner = mocker.Mock()
        processor.runner.get_task_status.return_value = (
            STATUS.IN_PROGRESS.value
        )
        processor.queue_client = mocker.Mock()
        payload = json.dumps(
            ModelArtifacts(
                modelId="6283",
                projectId="project-1",
                zipStatus=STATUS.IN_PROGRESS.value,
                currentZipJobUid="zip-1",
                zipJobs=[ZipJob(jobId="job-1", taskId="zip-1")],
                zipStatusMessage=MetadataUtils.append_status_message(
                    "", "Submitting zip task"
                ),
            ).dict()
        )

        for _ in range(1000):
            # Each poll starts from the message the previous one queued.
            processor.model_artifacts = ModelArtifacts(**json.loads(payload))
            processor.process_zip()
            payload = processor.queue_client.put_message.call_args.args[0]

        queued = json.loads(payload)
        assert queued["zipStatusMessage"].count(ZIP_IN_PROGRESS_MESSAGE) == 1
        assert queued["zipJobs"][0]["logs"] == queued["zipStatusMessage"]
        assert "Submitting zip task" in queued["zipStatusMessage"]

    def test_a_new_zip_job_drops_earlier_jobs_logs(self, mocker):
        processor = ArtifactProcessor.__new__(ArtifactProcessor)
        processor.config = mocker.Mock()
        processor.config.get_status_types.return_value = STATUS
        processor.config.get_azure_batch_config.return_value = {
            "artifact_batch_job_id": "artifacts",
            "imageprep_docker_image": "image",
        }
        processor.logger = mocker.Mock()
        processor.runner = mocker.Mock()
        processor.runner.add_task.return_value = ("artifacts", "zip-3")
        processor.queue_client = mocker.Mock()
        processor.training_zip_name = "training.zip"
        processor.inference_zip_name = "inference.zip"
        mocker.patch.object(processor, "prepare_zip_job", return_value={})
        processor.model_data = mocker.Mock(
            trainingOutputPath="training", inferenceOutputPath=None
        )
        finished_run = MetadataUtils.append_status_message(
            "", "Zipping artifacts completed successfully"
        )
        processor.model_artifacts = ModelArtifacts(
            modelId="6283",
            projectId="project-1",
            zipJobs=[
                ZipJob(
                    taskId=f"zip-{run}", status="Completed", logs=finished_run
                )
                for run in (1, 2)
            ],
        )

        processor.submit_zip_job()

        jobs = processor.model_artifacts.zipJobs
        assert [job.taskId for job in jobs] == ["zip-1", "zip-2", "zip-3"]
        assert [job.status for job in jobs[:2]] == ["Completed", "Completed"]
        assert [job.logs for job in jobs[:2]] == ["", ""]
        assert processor.model_artifacts.currentZipJobUid == "zip-3"

    def test_fetch_artifact_delegates_to_storage(self, mocker):
        processor = ArtifactProcessor.__new__(ArtifactProcessor)
        processor.storage = mocker.Mock()
        processor.storage.fetch_artifact.return_value = "/tmp/output"

        result = processor.fetch_artifact(
            identifier="artifact",
            extra_partition_keys=["model"],
            src_path="source",
            dst_path="/tmp/output",
        )

        assert result == "/tmp/output"
        processor.storage.fetch_artifact.assert_called_once_with(
            identifier="artifact",
            extra_partition_keys=["model"],
            src_path="source",
            dst_path="/tmp/output",
        )
