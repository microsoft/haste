# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import asyncio
import json
import os
import traceback

import azure.functions as func  # type: ignore
from hastegeo.core.config import Config
from hastegeo.core.models.footprint_tiles import parse_tiles_request
from hastegeo.core.models.publishing import PublishQueueMessage
from hastegeo.core.models.stats import ProjectsSummary, StatsRequest
from hastegeo.core.processors.footprint_tiles import process_tiles_request
from hastegeo.core.processors.job_queue import (
    JobQueueProcessor,
    reconcile_local_tasks,
)
from hastegeo.core.processors.job_state import JobStateRepository, Workload
from hastegeo.core.processors.metadata import MetadataProcessor
from hastegeo.core.processors.publishing import PublishingProcessor
from hastegeo.core.processors.stats import StatsPostProcessor
from hastegeo.core.utils.gdal_security import (
    max_download_bytes,
    max_upload_bytes,
)
from hastegeo.core.utils.logs import Logger
from hastegeo.core.utils.metadata import MetadataUtils

config = Config()
process_id = MetadataUtils.generate_short_int_id()
short_date_stamp = MetadataUtils.get_short_date()
log_dir = os.path.join(config.DATA_DIR, "logs", short_date_stamp)
logger = Logger.get_logger(
    __name__, f"{__name__}_pid_{process_id}.log", log_dir=log_dir
)
app = func.FunctionApp()


@app.route(
    route="GetEffectiveLimits",
    auth_level=func.AuthLevel.FUNCTION,
    methods=["GET"],
)
def GetEffectiveLimits(req: func.HttpRequest) -> func.HttpResponse:
    """
    Report the size caps as this app's HTTP worker sees them.

    Mirrors the identically-named route on the api app. This app is otherwise
    queue-triggered only, but it owns HASTE_MAX_IMAGERY_DOWNLOAD_BYTES -- it is
    ImageryPostProcessor that forwards the cap to the imageryprep Batch task --
    but Flex Consumption scales HTTP and queue triggers separately. This route
    cannot verify queue-worker state or Batch download enforcement.

    Returns:
        func.HttpResponse: 200 with the effective limits in bytes.
    """
    return func.HttpResponse(
        json.dumps(
            {
                "maxUploadBytes": max_upload_bytes(),
                "maxImageryDownloadBytes": max_download_bytes(),
                "publishAssessmentMaxTotalBytes": (
                    config.get_assessment_max_total_bytes()
                ),
                "instanceId": os.environ.get("WEBSITE_INSTANCE_ID", "local"),
            }
        ),
        status_code=200,
        mimetype="application/json",
    )


@app.function_name(name="GetProcessImageLayerQueueTrigger")
@app.queue_trigger(
    arg_name="msg",
    queue_name=config.get_queue_config()["image_queue_name"],
    connection="AzureWebJobsStorage",
)
async def GetProcessImageLayerQueueMessage(msg: func.QueueMessage) -> None:
    await asyncio.to_thread(
        JobQueueProcessor(config).process_message,
        Workload.IMAGERY,
        msg.get_body(),
    )


@app.function_name(name="GetCreateModelRunQueueTrigger")
@app.queue_trigger(
    arg_name="msg",
    queue_name=config.get_queue_config()["train_queue_name"],
    connection="AzureWebJobsStorage",
)
async def GetCreateModelRunQueueMessage(msg: func.QueueMessage) -> None:
    await asyncio.to_thread(
        JobQueueProcessor(config).process_message,
        Workload.TRAINING,
        msg.get_body(),
    )


@app.function_name(name="GetRunEmbeddingQueueTrigger")
@app.queue_trigger(
    arg_name="msg",
    queue_name=config.get_queue_config()["embedding_queue_name"],
    connection="AzureWebJobsStorage",
)
async def GetRunEmbeddingQueueMessage(msg: func.QueueMessage) -> None:
    await asyncio.to_thread(
        JobQueueProcessor(config).process_message,
        Workload.EMBEDDING,
        msg.get_body(),
    )


@app.function_name(name="GetPrepareFootprintTilesQueueTrigger")
@app.queue_trigger(
    arg_name="msg",
    queue_name=config.get_queue_config()["footprint_tiles_queue_name"],
    connection="AzureWebJobsStorage",
)
async def GetPrepareFootprintTilesQueueMessage(
    msg: func.QueueMessage,
) -> None:
    """Build an image layer's shared building-footprint vector tiles.

    Message schema (identifiers only)::

        {"projectId": "...", "imageLayerId": "...", "force": false}

    Manually enqueue this to recover fresh/failed layers; set force=true
    to rebuild a ready layer. Active jobs are never reset. Optional
    requestId deduplicates redelivery (defaults to the Azure message ID);
    internal polls also carry taskId and never start a rebuild.
    Invalid requests and unexpected failures raise sanitized exceptions
    for Functions retry/poison handling. Deleted layers are a no-op.
    """
    try:
        request = parse_tiles_request(msg.get_body(), msg.id)
        await asyncio.to_thread(process_tiles_request, request, config=config)
    except Exception as error:
        # Legacy bodies and SDK/Pydantic errors may contain SAS credentials.
        # Do not log payloads, error text, or an unsanitized exception chain.
        message = (
            "Footprint tile queue processing failed "
            f"({type(error).__name__}); retry/poison handling will apply"
        )
        logger.error(message)
        raise RuntimeError(message) from None


@app.function_name(name="GetRunInferenceQueueTrigger")
@app.queue_trigger(
    arg_name="msg",
    queue_name=config.get_queue_config()["inference_queue_name"],
    connection="AzureWebJobsStorage",
)
async def GetRunInferenceQueueMessage(msg: func.QueueMessage) -> None:
    await asyncio.to_thread(
        JobQueueProcessor(config).process_message,
        Workload.INFERENCE,
        msg.get_body(),
    )


@app.function_name(name="ArtifactsZipQueueTrigger")
@app.queue_trigger(
    arg_name="msg",
    queue_name=config.get_queue_config()["zip_queue_name"],
    connection="AzureWebJobsStorage",
)
async def GetArtifactsZipQueueMessage(msg: func.QueueMessage) -> None:
    await asyncio.to_thread(
        JobQueueProcessor(config).process_message, Workload.ZIP, msg.get_body()
    )


@app.function_name(name="ImagePoisonQueueTrigger")
@app.queue_trigger(
    arg_name="msg",
    queue_name=f'{config.get_queue_config()["image_queue_name"]}-poison',
    connection="AzureWebJobsStorage",
)
async def ImagePoisonQueueHandler(msg: func.QueueMessage) -> None:
    await asyncio.to_thread(
        JobQueueProcessor(config).process_message,
        Workload.IMAGERY,
        msg.get_body(),
        poison=True,
    )


@app.function_name(name="TrainingPoisonQueueTrigger")
@app.queue_trigger(
    arg_name="msg",
    queue_name=f'{config.get_queue_config()["train_queue_name"]}-poison',
    connection="AzureWebJobsStorage",
)
async def TrainingPoisonQueueHandler(msg: func.QueueMessage) -> None:
    await asyncio.to_thread(
        JobQueueProcessor(config).process_message,
        Workload.TRAINING,
        msg.get_body(),
        poison=True,
    )


@app.function_name(name="EmbeddingPoisonQueueTrigger")
@app.queue_trigger(
    arg_name="msg",
    queue_name=f'{config.get_queue_config()["embedding_queue_name"]}-poison',
    connection="AzureWebJobsStorage",
)
async def EmbeddingPoisonQueueHandler(msg: func.QueueMessage) -> None:
    await asyncio.to_thread(
        JobQueueProcessor(config).process_message,
        Workload.EMBEDDING,
        msg.get_body(),
        poison=True,
    )


@app.function_name(name="InferencePoisonQueueTrigger")
@app.queue_trigger(
    arg_name="msg",
    queue_name=f'{config.get_queue_config()["inference_queue_name"]}-poison',
    connection="AzureWebJobsStorage",
)
async def InferencePoisonQueueHandler(msg: func.QueueMessage) -> None:
    await asyncio.to_thread(
        JobQueueProcessor(config).process_message,
        Workload.INFERENCE,
        msg.get_body(),
        poison=True,
    )


@app.function_name(name="ArtifactsZipPoisonQueueTrigger")
@app.queue_trigger(
    arg_name="msg",
    queue_name=f'{config.get_queue_config()["zip_queue_name"]}-poison',
    connection="AzureWebJobsStorage",
)
async def ArtifactsZipPoisonQueueHandler(msg: func.QueueMessage) -> None:
    await asyncio.to_thread(
        JobQueueProcessor(config).process_message,
        Workload.ZIP,
        msg.get_body(),
        poison=True,
    )


@app.function_name(name="ReconcileLocalTasks")
@app.timer_trigger(
    arg_name="timer",
    schedule="*/15 * * * * *",
    run_on_startup=False,
    use_monitor=True,
)
async def ReconcileLocalTasks(timer: func.TimerRequest) -> None:
    await asyncio.to_thread(reconcile_local_tasks, config)


@app.function_name(name="ReconcileJobQueues")
@app.timer_trigger(
    arg_name="timer",
    # A safety net for lost messages, not the polling path: each run reads
    # every job record, so it stays infrequent.
    schedule="0 */5 * * * *",
    run_on_startup=False,
    use_monitor=True,
)
async def ReconcileJobQueues(timer: func.TimerRequest) -> None:
    await asyncio.to_thread(JobStateRepository(config).reconcile_queues)


@app.function_name(name="UpdateStatsTrigger")
@app.queue_trigger(
    arg_name="msg",
    queue_name=config.get_queue_config()["stats_queue_name"],
    connection="AzureWebJobsStorage",
)
async def UpdateStatsMessage(msg: func.QueueMessage) -> None:
    logger.info(
        f'UpdateStatsTrigger function processed a message: {msg.get_body().decode("utf-8")}'
    )
    try:
        request_data = json.loads(msg.get_body().decode("utf-8"))
        request_obj = StatsRequest(**request_data)
        try:
            stats_data = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().PROJECT.value
                ).load,
                "stats",
            )
        except FileNotFoundError:
            logger.info("Stats file not found, initializing empty summary.")
            stats_data = {"projects": []}
        summary = ProjectsSummary(**stats_data)
        updated_summary = await asyncio.to_thread(
            StatsPostProcessor(request_obj, summary).update
        )
        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().PROJECT.value
            ).save,
            "stats",
            updated_summary.dict(),
        )
        logger.info(
            f'UpdateStatsTrigger function updated summary with contents of message: {msg.get_body().decode("utf-8")}'
        )
    except Exception as e:
        logger.error(
            f"UpdateStatsTrigger: Error processing queue message: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )


@app.function_name(name="PublishDatasetQueueTrigger")
@app.queue_trigger(
    arg_name="msg",
    queue_name=config.get_queue_config()["publish_queue_name"],
    connection="AzureWebJobsStorage",
)
async def GetPublishDatasetQueueMessage(msg: func.QueueMessage) -> None:
    try:
        message = PublishQueueMessage(
            **json.loads(msg.get_body().decode("utf-8"))
        )
        await asyncio.to_thread(
            PublishingProcessor(config=config).run_step, message
        )
    except Exception as error:
        logger.error(
            "PublishDatasetQueueTrigger failed with %s",
            type(error).__name__,
        )
        raise RuntimeError(
            f"Publishing queue step failed: {type(error).__name__}"
        ) from None


@app.function_name(name="PublishDatasetPoisonQueueTrigger")
@app.queue_trigger(
    arg_name="msg",
    queue_name=f'{config.get_queue_config()["publish_queue_name"]}-poison',
    connection="AzureWebJobsStorage",
)
async def GetPublishDatasetPoisonQueueMessage(msg: func.QueueMessage) -> None:
    try:
        message = PublishQueueMessage(
            **json.loads(msg.get_body().decode("utf-8"))
        )
        await asyncio.to_thread(
            PublishingProcessor(config=config).mark_poisoned, message
        )
    except FileNotFoundError:
        logger.info("Ignoring poison message for a removed published dataset")
    except Exception as error:
        logger.error(
            "PublishDatasetPoisonQueueTrigger failed with %s",
            type(error).__name__,
        )
        raise RuntimeError(
            f"Publishing poison step failed: {type(error).__name__}"
        ) from None


@app.function_name(name="ReconcilePublishingOperations")
@app.timer_trigger(
    arg_name="timer",
    schedule="0 */5 * * * *",
    run_on_startup=False,
    use_monitor=True,
)
async def ReconcilePublishingOperations(timer: func.TimerRequest) -> None:
    try:
        requeued = await asyncio.to_thread(
            PublishingProcessor(config=config).reconcile_stale
        )
        if requeued:
            logger.info("Requeued %s stale publishing operations", requeued)
    except Exception as error:
        logger.error(
            "ReconcilePublishingOperations failed with %s",
            type(error).__name__,
        )
        raise RuntimeError(
            f"Publishing reconciliation failed: {type(error).__name__}"
        ) from None
