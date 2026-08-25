# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import asyncio
import json
import os
import traceback
from typing import Optional

import azure.functions as func  # type: ignore
from hastegeo.core.config import Config
from hastegeo.core.models.projects import (
    ImageLayer,
    LabelProject,
    Model,
    ModelArtifacts,
    Project,
)
from hastegeo.core.models.publishing import PublishQueueMessage
from hastegeo.core.models.stats import ProjectsSummary, StatsRequest
from hastegeo.core.models.training import ExperimentConfig
from hastegeo.core.processors.artifacts import ArtifactProcessor
from hastegeo.core.processors.embedding import EmbeddingPostprocessor
from hastegeo.core.processors.imagery import ImageryPostProcessor
from hastegeo.core.processors.inference import (
    InferencePostprocessor,
    InferencePreprocessor,
)
from hastegeo.core.processors.labels import LabelTaskGenerator
from hastegeo.core.processors.metadata import MetadataProcessor
from hastegeo.core.processors.prediction_tiles import (
    PredictionTilesPostprocessor,
    needs_preparation,
    versions_needing_attrs,
)
from hastegeo.core.processors.publishing import PublishingProcessor
from hastegeo.core.processors.stats import StatsPostProcessor
from hastegeo.core.processors.train import TrainPostprocessor
from hastegeo.core.utils.data import convert_json_to_geojson
from hastegeo.core.utils.errors import describe_exception
from hastegeo.core.utils.logs import Logger
from hastegeo.core.utils.metadata import MetadataUtils
from pydantic import ValidationError  # type: ignore

config = Config()
process_id = MetadataUtils.generate_short_int_id()
short_date_stamp = MetadataUtils.get_short_date()
log_dir = os.path.join(config.DATA_DIR, "logs", short_date_stamp)
logger = Logger.get_logger(
    __name__, f"{__name__}_pid_{process_id}.log", log_dir=log_dir
)
app = func.FunctionApp()


@app.function_name(name="GetProcessImageLayerQueueTrigger")
@app.queue_trigger(
    arg_name="msg",
    queue_name=config.get_queue_config()["image_queue_name"],
    connection="AzureWebJobsStorage",
)
async def GetProcessImageLayerQueueMessage(msg: func.QueueMessage) -> None:
    """
    Process image layer queue messages for geospatial imagery preprocessing.

    This function handles asynchronous processing of uploaded image layers, including:
    - Geospatial transformation and projection corrections
    - Image tiling and pyramid generation for efficient viewing
    - Metadata extraction and validation
    - Thumbnail generation for preview purposes
    - Integration with storage systems and databases

    The processing pipeline includes:
    1. Message validation and deserialization
    2. Existence check to prevent duplicate processing
    3. Geospatial processing using GDAL operations
    4. Tile generation for web mapping interfaces
    5. Metadata storage and indexing
    6. Status updates and progress tracking

    Args:
        msg (func.QueueMessage): Azure Queue message containing:
            - ImageLayer JSON payload with:
                - imageLayerId (str): Unique identifier for the image layer
                - projectId (str): Associated project identifier
                - filePath (str): Path to the uploaded image file
                - processingConfig (dict): Processing parameters and options
                - bounds (dict): Geographic bounds of the imagery
                - projection (str): Source coordinate reference system

    Returns:
        None: This is a queue trigger function with no return value.
              Status is tracked through logging and metadata updates.

    Raises:
        ValidationError: If message payload is invalid or corrupted
        ProcessingError: If geospatial processing operations fail
        StorageError: If file operations or metadata storage fails
        GeospatialError: If coordinate transformations or projections fail

    Processing Flow:
        1. Deserialize queue message to ImageLayer object
        2. Check if layer already exists to prevent reprocessing
        3. Execute geospatial preprocessing pipeline
        4. Generate tiles and thumbnails for visualization
        5. Update processing status and metadata
        6. Handle errors with appropriate retry logic
    """
    logger.info(
        f'GetProcessImageLayerQueueTrigger function processed a message: {msg.get_body().decode("utf-8")}'
    )
    try:
        image_data = ImageLayer(**json.loads(msg.get_body().decode("utf-8")))
        try:
            # This check is to ensure deleted layer does not get recreated here
            existing_image_layer = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().IMAGELAYER.value,
                    partition_key=image_data.projectId,
                ).load,
                image_data.imageLayerId,
            )
        except FileNotFoundError:
            existing_image_layer = None

        if not existing_image_layer:
            logger.info(
                f"ImageLayer {image_data.imageLayerId} not found, likely deleted, skipping processing."
            )
            return

        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().IMAGELAYER.value,
                partition_key=image_data.projectId,
            ).save,
            image_data.imageLayerId,
            image_data.dict(),
        )
        output = await asyncio.to_thread(
            ImageryPostProcessor(image_data).process
        )
        if output.status == config.get_status_types().COMPLETED.value:
            logger.info(
                f"ImageryPostProcessor processed image layer: {output.imageLayerId}"
            )
            label_project = await asyncio.to_thread(
                LabelTaskGenerator(output).generate_task_files
            )
            logger.info(
                f"LabelTaskGenerator generated task files for image layer: {output.imageLayerId}"
            )
            # Save LabelProject
            await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().LABELS.value,
                    partition_key=output.projectId,
                ).save,
                label_project.labelprojectId,
                label_project.dict(),
            )
            output.labelProjectId = label_project.labelprojectId

            labels_geojson = convert_json_to_geojson(
                label_project.model_dump(by_alias=True)
            )

            artifact_processor = ArtifactProcessor(
                partition_key=output.projectId,
            )

            # Create the labels geojson artifact
            await asyncio.to_thread(
                artifact_processor.store_artifact,
                artifact_name=f"{config.get_metadata_types().LABELS.value}_{output.labelProjectId}.geojson",
                data=labels_geojson,
                # Note: short term solution is to store them in a separate folder,
                # long term - separate artifacts into their own container
                namespace="artifacts",
            )

            output.labelsUrl = await asyncio.to_thread(
                artifact_processor.get_download_url,
                identifier=f"{config.get_metadata_types().LABELS.value}_{output.labelProjectId}.geojson",
                extra_partition_keys="artifacts",
            )
            # Save ImageLayer completed status
            await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().IMAGELAYER.value,
                    partition_key=output.projectId,
                ).save,
                output.imageLayerId,
                output.dict(),
            )
        else:
            # Only save the ImageLayer status reflecting the failure
            output.labelsUrl = None
            await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().IMAGELAYER.value,
                    partition_key=output.projectId,
                ).save,
                output.imageLayerId,
                output.dict(),
            )
        logger.info(
            f'GetProcessImageLayerQueueTrigger function processed a message: {msg.get_body().decode("utf-8")}'
        )
    except Exception as e:
        if isinstance(e, ValueError):
            logger.error(
                f"GetProcessImageLayerQueueTrigger: Invalid JSON: {e}\n{traceback.format_exc()}"
            )
        elif isinstance(e, ValidationError):
            logger.error(
                f"GetProcessImageLayerQueueTrigger: Validation error: {e}\n{traceback.format_exc()}"
            )
        else:
            logger.error(
                f"GetProcessImageLayerQueueTrigger: Error processing queue message: {e}\n{traceback.format_exc()}",
                stack_info=True,
            )
            logger.error(traceback.format_exc())
        try:
            if "output" in locals():
                output.status = config.get_status_types().FAILED.value
                # Append rather than assign: the status dialog shows this
                # field, and overwriting it discards the whole progress
                # history the user needs to see what actually ran.
                output.statusMessage = MetadataUtils.append_status_message(
                    output.statusMessage,
                    f"Image layer processing failed: {describe_exception(e)}",
                )
                await asyncio.to_thread(
                    MetadataProcessor(
                        data_type=config.get_metadata_types().IMAGELAYER.value,
                        partition_key=output.projectId,
                    ).save,
                    output.imageLayerId,
                    output.dict(),
                )
            elif "image_data" in locals():
                image_data.status = config.get_status_types().FAILED.value
                image_data.statusMessage = MetadataUtils.append_status_message(
                    image_data.statusMessage,
                    f"Image layer processing failed: {describe_exception(e)}",
                )
                await asyncio.to_thread(
                    MetadataProcessor(
                        data_type=config.get_metadata_types().IMAGELAYER.value,
                        partition_key=image_data.projectId,
                    ).save,
                    image_data.imageLayerId,
                    image_data.dict(),
                )
        except Exception as inner_e:
            logger.error(
                f"Error saving failed status: {inner_e}\n{traceback.format_exc()}",
                stack_info=True,
            )


@app.function_name(name="GetCreateModelRunQueueTrigger")
@app.queue_trigger(
    arg_name="msg",
    queue_name=config.get_queue_config()["train_queue_name"],
    connection="AzureWebJobsStorage",
)
async def GetCreateModelRunQueueMessage(msg: func.QueueMessage) -> None:
    """
    Execute machine learning model training workflows from queue messages.

    This function orchestrates complete model training pipelines including:
    - Training data preparation and validation
    - Model architecture configuration and initialization
    - Distributed training execution with progress monitoring
    - Model validation and performance evaluation
    - Artifact generation and storage (checkpoints, logs, metrics)
    - Integration with Azure Machine Learning services

    The training pipeline supports:
    - Multiple model architectures (CNN, transformer-based, etc.)
    - Distributed training across multiple compute nodes
    - Automatic hyperparameter optimization
    - Real-time progress tracking and logging
    - Checkpoint saving for resumable training
    - Model performance validation and testing

    Args:
        msg (func.QueueMessage): Azure Queue message containing:
            - Model JSON payload with:
                - modelId (str): Unique identifier for the model
                - projectId (str): Associated project identifier
                - imageLayerId (str): Source image layer for training
                - modelConfig (dict): Training configuration parameters including:
                    - architecture (str): Model architecture type
                    - hyperparameters (dict): Training hyperparameters
                    - trainingConfig (dict): Training execution settings
                    - validationConfig (dict): Validation and testing setup
                - computeConfig (dict): Compute resource specifications

    Returns:
        None: This is a queue trigger function with no return value.
              Training progress is tracked through Azure ML and metadata updates.

    Raises:
        ValidationError: If model configuration is invalid
        TrainingError: If model training execution fails
        ResourceError: If required compute resources are unavailable
        DataError: If training data is corrupted or inaccessible
        ModelError: If model architecture configuration is invalid

    Training Flow:
        1. Deserialize and validate model configuration
        2. Check for existing model to prevent duplicate training
        3. Prepare training and validation datasets
        4. Initialize model architecture and training environment
        5. Execute distributed training with monitoring
        6. Validate model performance and generate artifacts
        7. Update model status and store results
    """
    logger.info(
        f'GetCreateModelRunQueueTrigger function processed a message: {msg.get_body().decode("utf-8")}'
    )
    try:
        model_data = Model(**json.loads(msg.get_body().decode("utf-8")))
        try:
            # This check is to ensure deleted model does not get recreated
            existing_model = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().MODEL.value,
                    partition_key=model_data.projectId,
                ).load,
                model_data.modelId,
            )
        except FileNotFoundError:
            existing_model = None

        if existing_model:
            existing_model = Model(**existing_model)
        else:
            logger.info(
                f"Model {model_data.modelId} not found, likely deleted, skipping processing."
            )
            return

        if existing_model.status == config.get_status_types().CANCELLED.value:
            output = await asyncio.to_thread(
                TrainPostprocessor(existing_model).cancel
            )

        else:
            await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().MODEL.value,
                    partition_key=model_data.projectId,
                ).save,
                model_data.modelId,
                model_data.dict(),
            )
            image_layer = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().IMAGELAYER.value,
                    partition_key=model_data.projectId,
                ).load,
                model_data.imageLayerId,
            )

            image_layer = ImageLayer(**image_layer)

            # Also get labels here and pass to processor
            label_projects = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().LABELS.value,
                    partition_key=model_data.projectId,
                ).load_all_from_partition
            )
            match_label_project = next(
                (
                    lp
                    for lp in label_projects
                    if lp["imageLayerId"] == image_layer.imageLayerId
                ),
                None,
            )
            match_label_project = LabelProject(**match_label_project)
            project = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().PROJECT.value,
                    partition_key=model_data.projectId,
                ).load,
                model_data.projectId,
            )
            project = Project(**project)
            output = await asyncio.to_thread(
                TrainPostprocessor(
                    model_data, image_layer, match_label_project, project
                ).process
            )

        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().MODEL.value,
                partition_key=model_data.projectId,
            ).save,
            model_data.modelId,
            output.dict(),
        )
        logger.info(
            f'GetCreateModelRunQueueTrigger function processed a message: {msg.get_body().decode("utf-8")}'
        )
    except ValidationError as e:
        logger.error(
            f"GetCreateModelRunQueueTrigger: Validation error: {e}\n{traceback.format_exc()}"
        )
    except ValueError as e:
        logger.error(
            f"GetCreateModelRunQueueTrigger: Invalid JSON: {e}\n{traceback.format_exc()}"
        )
    except Exception as e:
        logger.error(
            f"GetCreateModelRunQueueTrigger: Error processing queue message: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        try:
            model_data.status = config.get_status_types().FAILED.value
            model_data.statusMessage = MetadataUtils.append_status_message(
                model_data.statusMessage,
                f"Training job failed: {describe_exception(e)}",
            )
            output = model_data
            await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().MODEL.value,
                    partition_key=model_data.projectId,
                ).save,
                model_data.modelId,
                model_data.dict(),
            )
        except Exception as inner_e:
            logger.error(
                f"GetCreateModelRunQueueTrigger: Error saving failed status: {inner_e}\n{traceback.format_exc()}",
                stack_info=True,
            )

    # Send a message to zip artifacts only for failed training jobs
    # This is in preparation for when training and inference will be combined into a single run
    # Running training zip and then inference zip introduces concurrency challenges
    # that may end up not being relevant if training and inference are combined.
    # Separate from upper block because we don't want to fail the model if this fails
    try:
        if (
            output.status == config.get_status_types().FAILED.value
            or output.status == config.get_status_types().CANCELLED.value
        ) and output.trainingOutputPath:
            model_artifacts = ModelArtifacts(
                modelId=model_data.modelId,
                projectId=model_data.projectId,
                imageLayerId=model_data.imageLayerId,
            )
            artifact_output = await asyncio.to_thread(
                ArtifactProcessor(
                    partition_key=model_artifacts.projectId,
                    model_artifacts=model_artifacts,
                ).send_to_zip_queue
            )
            await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().MODEL_ARTIFACTS.value,
                    partition_key=model_artifacts.projectId,
                ).save,
                model_artifacts.modelId,
                artifact_output.dict(),
            )
            logger.info(
                f"GetCreateModelRunQueueTrigger: Successfuly sent zip queue message for model {model_data.modelId}"
            )
    except Exception as e:
        logger.error(
            f"GetCreateModelRunQueueTrigger: Error sending zip queue message: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )

    # Finally, trigger inference if it was selected to do so
    # zipping must occur before triggering inference if the same pool is used for training and all other operations
    if (
        output.status == config.get_status_types().COMPLETED.value
        and output.autoRunInference
    ):
        try:
            output = await asyncio.to_thread(
                InferencePreprocessor(output).send_to_queue
            )
            await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().MODEL.value,
                    partition_key=output.projectId,
                ).save,
                output.modelId,
                output.dict(),
            )
            logger.info(
                f"GetCreateModelRunQueueTrigger: Successfully sent inference queue message for model {output.modelId}"
            )
        except Exception as inner_e:
            logger.error(
                f"GetCreateModelRunQueueTrigger: Error sending inference queue message: {inner_e}\n{traceback.format_exc()}",
                stack_info=True,
            )


@app.function_name(name="GetRunEmbeddingQueueTrigger")
@app.queue_trigger(
    arg_name="msg",
    queue_name=config.get_queue_config()["embedding_queue_name"],
    connection="AzureWebJobsStorage",
)
async def GetRunEmbeddingQueueMessage(msg: func.QueueMessage) -> None:
    """Execute a building-embedding job (building labeling workflow).

    Deserializes the embedding Model, loads its image layer, and drives the
    EmbeddingPostprocessor state machine (submit -> poll -> finalize). No
    zip/inference follow-on. Re-enqueues itself while in progress.
    """
    logger.info(
        "GetRunEmbeddingQueueTrigger function processed a message: "
        f'{msg.get_body().decode("utf-8")}'
    )
    model_data = None
    try:
        model_data = Model(**json.loads(msg.get_body().decode("utf-8")))
        try:
            existing_model = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().MODEL.value,
                    partition_key=model_data.projectId,
                ).load,
                model_data.modelId,
            )
        except FileNotFoundError:
            existing_model = None

        if not existing_model:
            logger.info(
                f"Embedding model {model_data.modelId} not found, likely "
                "deleted, skipping processing."
            )
            return

        image_layer = await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().IMAGELAYER.value,
                partition_key=model_data.projectId,
            ).load,
            model_data.imageLayerId,
        )
        image_layer = ImageLayer(**image_layer)

        output = await asyncio.to_thread(
            EmbeddingPostprocessor(model_data, image_layer).process
        )

        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().MODEL.value,
                partition_key=model_data.projectId,
            ).save,
            model_data.modelId,
            output.dict(),
        )
    except ValidationError as e:
        logger.error(
            f"GetRunEmbeddingQueueTrigger: Validation error: {e}\n"
            f"{traceback.format_exc()}"
        )
    except ValueError as e:
        logger.error(
            f"GetRunEmbeddingQueueTrigger: Invalid JSON: {e}\n"
            f"{traceback.format_exc()}"
        )
    except Exception as e:
        logger.error(
            f"GetRunEmbeddingQueueTrigger: Error processing queue message: "
            f"{e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        if model_data is not None:
            try:
                model_data.status = config.get_status_types().FAILED.value
                model_data.statusMessage = MetadataUtils.append_status_message(
                    model_data.statusMessage,
                    f"Embedding job failed: {describe_exception(e)}",
                )
                await asyncio.to_thread(
                    MetadataProcessor(
                        data_type=config.get_metadata_types().MODEL.value,
                        partition_key=model_data.projectId,
                    ).save,
                    model_data.modelId,
                    model_data.dict(),
                )
            except Exception as inner_e:
                logger.error(
                    "GetRunEmbeddingQueueTrigger: Error saving failed "
                    f"status: {inner_e}\n{traceback.format_exc()}",
                    stack_info=True,
                )


async def _save_layer_footprint_tile_state(
    project_id: str, image_layer: ImageLayer
) -> None:
    """Persist only the footprint-tiling fields of an image layer.

    A layer-only tiling job runs alongside (and just after) imagery
    preprocessing, which owns the rest of the document. Re-reading the
    layer and patching just these four fields keeps the tiling job from
    clobbering a concurrent imagery update.
    """
    metadata = MetadataProcessor(
        data_type=config.get_metadata_types().IMAGELAYER.value,
        partition_key=project_id,
    )
    image_layer_id = image_layer.imageLayerId
    latest_layer = await asyncio.to_thread(metadata.load, image_layer_id)
    job = image_layer.footprintTilesJob
    latest_layer.update(
        {
            "footprintPmtilesUrl": image_layer.footprintPmtilesUrl,
            "footprintTilesStatus": image_layer.footprintTilesStatus,
            "footprintTilesStatusMessage": (
                image_layer.footprintTilesStatusMessage
            ),
            "footprintTilesJob": job.dict() if job else None,
        }
    )
    await asyncio.to_thread(metadata.save, image_layer_id, latest_layer)


async def _prepare_layer_footprint_tiles(
    project_id: str, image_layer_id: str, force: bool
) -> None:
    """Build an image layer's shared footprint PMTiles (no model).

    The layer-only half of the prep queue: imagery preprocessing asks
    for this as soon as a layer's building footprints are cached, so the
    prediction editor finds the tiles already built. No model document is
    read or written — the job's state lives on the layer
    (``footprintTilesStatus``/``footprintTilesJob``).
    """
    image_layer = None
    try:
        try:
            layer_record = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().IMAGELAYER.value,
                    partition_key=project_id,
                ).load,
                image_layer_id,
            )
        except FileNotFoundError:
            layer_record = None

        if not layer_record:
            logger.info(
                f"Image layer {image_layer_id} not found, likely deleted, "
                "skipping footprint tile preparation."
            )
            return

        # Metadata is authoritative: the message only routes the work.
        image_layer = ImageLayer(**layer_record)
        statuses = config.get_status_types()
        if image_layer.footprintTilesStatus != statuses.IN_PROGRESS.value:
            if not image_layer.buildingFootprintsUrl:
                logger.info(
                    f"Image layer {image_layer_id} has no cached building "
                    "footprints; nothing to tile."
                )
                return
            if not force and image_layer.footprintPmtilesUrl:
                logger.info(
                    f"Footprint tiles for image layer {image_layer_id} are "
                    "already available; nothing to do."
                )
                image_layer.footprintTilesStatus = statuses.COMPLETED.value
                await _save_layer_footprint_tile_state(project_id, image_layer)
                return
            image_layer.footprintTilesStatus = statuses.PENDING.value

        processor = PredictionTilesPostprocessor(None, image_layer)
        output = await asyncio.to_thread(processor.process)
        await _save_layer_footprint_tile_state(project_id, output)
    except Exception as e:
        logger.error(
            "PreparePredictionTilesQueueTrigger: Error preparing footprint "
            f"tiles for image layer {image_layer_id}: {e}\n"
            f"{traceback.format_exc()}",
            stack_info=True,
        )
        if image_layer is not None:
            try:
                image_layer.footprintTilesStatus = (
                    config.get_status_types().FAILED.value
                )
                image_layer.footprintTilesStatusMessage = (
                    MetadataUtils.append_status_message(
                        image_layer.footprintTilesStatusMessage,
                        "Footprint tile job failed: "
                        f"{describe_exception(e)}",
                    )
                )
                await _save_layer_footprint_tile_state(project_id, image_layer)
            except Exception as inner_e:
                logger.error(
                    "PreparePredictionTilesQueueTrigger: Error saving "
                    f"failed status: {inner_e}\n{traceback.format_exc()}",
                    stack_info=True,
                )


async def _prepare_model_prediction_tiles(
    project_id: str,
    image_layer_id: Optional[str],
    model_id: str,
    force: bool,
    backfill_versions: bool = True,
) -> None:
    """Build a model's attribute sidecar (+ the layer's tiles if absent).

    Drives the PredictionTilesPostprocessor state machine (submit ->
    poll -> finalize) for one model. On completion the model gets its
    attribute-sidecar URL and the image layer gets the shared footprint
    PMTiles URL, so both documents are persisted.

    With ``backfill_versions`` the run also rebuilds the sidecar of every
    saved edited version that has none, and records each URL on its
    ``Model.editedPredictions`` entry. Versions that already have one are
    skipped, so this is safe to repeat.
    """
    model_data = None
    try:
        try:
            existing_model = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().MODEL.value,
                    partition_key=project_id,
                ).load,
                model_id,
            )
        except FileNotFoundError:
            existing_model = None

        if not existing_model:
            logger.info(
                f"Model {model_id} not found, likely deleted, "
                "skipping prediction tile preparation."
            )
            return

        # Metadata is authoritative: the message only routes the work.
        model_data = Model(**existing_model)
        image_layer_id = image_layer_id or model_data.imageLayerId
        if not image_layer_id:
            raise ValueError(
                f"Model {model_id} has no imageLayerId; cannot locate "
                "the building footprints to tile."
            )

        image_layer_record = await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().IMAGELAYER.value,
                partition_key=project_id,
            ).load,
            image_layer_id,
        )
        image_layer = ImageLayer(**image_layer_record)
        previous_pmtiles_url = image_layer.footprintPmtilesUrl

        statuses = config.get_status_types()
        if model_data.predictionTilesStatus != statuses.IN_PROGRESS.value:
            needs_pmtiles, needs_attrs = needs_preparation(
                model_data, image_layer
            )
            # A saved version with no sidecar cannot be rendered, so it
            # is outstanding work even when the model's own artifacts
            # are already there.
            pending_versions = (
                versions_needing_attrs(model_data) if backfill_versions else []
            )
            if (
                not force
                and not needs_pmtiles
                and not needs_attrs
                and not pending_versions
            ):
                logger.info(
                    f"Prediction tiles for model {model_id} are already "
                    "available; nothing to do."
                )
                model_data.predictionTilesStatus = statuses.COMPLETED.value
                await asyncio.to_thread(
                    MetadataProcessor(
                        data_type=config.get_metadata_types().MODEL.value,
                        partition_key=project_id,
                    ).save,
                    model_id,
                    model_data.dict(),
                )
                return
            model_data.predictionTilesStatus = statuses.PENDING.value

        processor = PredictionTilesPostprocessor(
            model_data, image_layer, backfill_versions=backfill_versions
        )
        output = await asyncio.to_thread(processor.process)

        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().MODEL.value,
                partition_key=project_id,
            ).save,
            model_id,
            output.dict(),
        )

        # Footprint tiles belong to the layer, not the model. Re-read the
        # layer before writing so a concurrent imagery update isn't lost.
        new_pmtiles_url = processor.image_layer.footprintPmtilesUrl
        if new_pmtiles_url and new_pmtiles_url != previous_pmtiles_url:
            latest_layer = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().IMAGELAYER.value,
                    partition_key=project_id,
                ).load,
                image_layer_id,
            )
            latest_layer["footprintPmtilesUrl"] = new_pmtiles_url
            await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().IMAGELAYER.value,
                    partition_key=project_id,
                ).save,
                image_layer_id,
                latest_layer,
            )
    except Exception as e:
        logger.error(
            "PreparePredictionTilesQueueTrigger: Error preparing prediction "
            f"tiles for model {model_id}: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        if model_data is not None:
            try:
                model_data.predictionTilesStatus = (
                    config.get_status_types().FAILED.value
                )
                model_data.predictionTilesStatusMessage = (
                    MetadataUtils.append_status_message(
                        model_data.predictionTilesStatusMessage,
                        "Prediction tile job failed: "
                        f"{describe_exception(e)}",
                    )
                )
                await asyncio.to_thread(
                    MetadataProcessor(
                        data_type=config.get_metadata_types().MODEL.value,
                        partition_key=model_data.projectId,
                    ).save,
                    model_data.modelId,
                    model_data.dict(),
                )
            except Exception as inner_e:
                logger.error(
                    "PreparePredictionTilesQueueTrigger: Error saving "
                    f"failed status: {inner_e}\n{traceback.format_exc()}",
                    stack_info=True,
                )


@app.function_name(name="PreparePredictionTilesQueueTrigger")
@app.queue_trigger(
    arg_name="msg",
    queue_name=config.get_queue_config()["prediction_edit_prep_queue_name"],
    connection="AzureWebJobsStorage",
)
async def GetPreparePredictionTilesQueueMessage(
    msg: func.QueueMessage,
) -> None:
    """Build the prediction editor's footprint tiles + attribute sidecar.

    Message schema (identifiers only)::

        {"projectId", "imageLayerId", "modelId", "sourceGpkgUrl",
         "sourceFootprintsUrl", "force", "backfillVersions"}

    An empty/absent ``modelId`` selects **layer-only** preparation: build
    the image layer's shared footprint PMTiles and nothing else. Imagery
    preprocessing queues that as soon as a layer's footprints are cached
    so the editor never has to wait for tiling. With a ``modelId`` the
    message is **model-scoped**: build the model's attribute sidecar,
    plus the layer's tiles when they are still missing, and (unless
    ``backfillVersions`` is false) the sidecar of every saved edited
    version that has none.

    The authoritative job state is read from metadata, so a fresh
    request and the postprocessor's own poll messages take the same
    path. The work runs as a task in the training docker image because
    tippecanoe only ships there.
    """
    logger.info(
        "PreparePredictionTilesQueueTrigger function processed a message: "
        f'{msg.get_body().decode("utf-8")}'
    )
    try:
        payload = json.loads(msg.get_body().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Queue message must be a JSON object")
        project_id = payload.get("projectId")
        model_id = payload.get("modelId")
        image_layer_id = payload.get("imageLayerId")
        force = bool(payload.get("force", False))
        backfill_versions = bool(payload.get("backfillVersions", True))
        if not project_id or not (model_id or image_layer_id):
            raise ValueError(
                "Queue message requires projectId plus modelId or "
                f"imageLayerId, got: {sorted(payload.keys())}"
            )

        if model_id:
            await _prepare_model_prediction_tiles(
                project_id,
                image_layer_id,
                model_id,
                force,
                backfill_versions=backfill_versions,
            )
        else:
            await _prepare_layer_footprint_tiles(
                project_id, image_layer_id, force
            )
    except ValidationError as e:
        logger.error(
            f"PreparePredictionTilesQueueTrigger: Validation error: {e}\n"
            f"{traceback.format_exc()}"
        )
    except ValueError as e:
        logger.error(
            "PreparePredictionTilesQueueTrigger: Invalid queue message: "
            f"{e}\n{traceback.format_exc()}"
        )
    except Exception as e:
        logger.error(
            "PreparePredictionTilesQueueTrigger: Error processing queue "
            f"message: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )


@app.function_name(name="GetRunInferenceQueueTrigger")
@app.queue_trigger(
    arg_name="msg",
    queue_name=config.get_queue_config()["inference_queue_name"],
    connection="AzureWebJobsStorage",
)
async def GetRunInferenceQueueMessage(msg: func.QueueMessage) -> None:
    """
    Execute model inference on geospatial imagery for prediction generation.

    This function handles batch inference processing using trained models to generate
    predictions on new imagery data. The inference pipeline includes:
    - Model loading and initialization from stored checkpoints
    - Input imagery preprocessing and tile generation
    - Batch prediction execution with GPU acceleration
    - Post-processing of predictions (confidence scoring, filtering)
    - Result aggregation and visualization preparation
    - Integration with mapping and visualization services

    Inference capabilities:
    - Large-scale imagery processing with tiling strategies
    - Multi-class and multi-label prediction support
    - Confidence threshold filtering and uncertainty quantification
    - Geospatial coordinate alignment and projection handling
    - Output format conversion (raster, vector, tiles)
    - Real-time progress monitoring and status updates

    Args:
        msg (func.QueueMessage): Azure Queue message containing:
            - Model JSON payload with:
                - modelId (str): Unique identifier for the trained model
                - projectId (str): Associated project identifier
                - imageLayerId (str): Target image layer for inference
                - inferenceConfig (dict): Inference parameters including:
                    - batchSize (int): Processing batch size
                    - confidenceThreshold (float): Minimum confidence for predictions
                    - outputFormat (str): Desired output format
                    - tileSize (int): Processing tile dimensions
                    - overlapSize (int): Tile overlap for edge handling
                - outputConfig (dict): Output storage and visualization settings

    Returns:
        None: This is a queue trigger function with no return value.
              Results are stored and status tracked through metadata updates.

    Raises:
        ValidationError: If inference configuration is invalid
        ModelError: If trained model cannot be loaded or is corrupted
        InferenceError: If prediction execution fails
        DataError: If input imagery is inaccessible or corrupted
        GeospatialError: If coordinate transformations fail
        StorageError: If output results cannot be saved

    Inference Flow:
        1. Deserialize inference configuration and validate
        2. Load trained model from checkpoint storage
        3. Prepare input imagery with tiling and preprocessing
        4. Execute batch inference with progress tracking
        5. Post-process predictions and apply confidence filtering
        6. Generate output files and visualization assets
        7. Update inference status and store results metadata
    """
    logger.info(
        f'GetRunInferenceQueueTrigger function processed a message: {msg.get_body().decode("utf-8")}'
    )
    try:
        model_data = Model(**json.loads(msg.get_body().decode("utf-8")))
        try:
            # This check is to ensure deleted model does not get recreated here
            existing_model = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().MODEL.value,
                    partition_key=model_data.projectId,
                ).load,
                model_data.modelId,
            )
        except FileNotFoundError:
            existing_model = None

        if existing_model:
            existing_model = Model(**existing_model)
        else:
            logger.info(
                f"Model {model_data.modelId} not found, likely deleted, skipping processing."
            )
            return

        if (
            existing_model.inferenceStatus
            == config.get_status_types().CANCELLED.value
        ):
            output = await asyncio.to_thread(
                InferencePostprocessor(existing_model).cancel
            )
        else:
            await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().MODEL.value,
                    partition_key=model_data.projectId,
                ).save,
                model_data.modelId,
                model_data.dict(),
            )
            image_layer = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().IMAGELAYER.value,
                    partition_key=model_data.projectId,
                ).load,
                model_data.imageLayerId,
            )
            image_layer = ImageLayer(**image_layer)

            experiment_config_raw = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().EXPERIMENT_CONFIG.value,
                    partition_key=model_data.projectId,
                ).load,
                model_data.modelId,
                data_format="yaml",
            )
            experiment_config = ExperimentConfig(**experiment_config_raw)
            output = await asyncio.to_thread(
                InferencePostprocessor(
                    model_data, image_layer, experiment_config
                ).process
            )

        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().MODEL.value,
                partition_key=output.projectId,
            ).save,
            output.modelId,
            output.dict(),
        )
        logger.info(
            f'GetRunInferenceQueueTrigger function processed a message: {msg.get_body().decode("utf-8")}'
        )
    except ValueError as e:
        logger.error(
            f"GetRunInferenceQueueTrigger: Invalid JSON: {e}\n{traceback.format_exc()}"
        )
    except Exception as e:
        logger.error(
            f"GetRunInferenceQueueTrigger: Error processing queue message: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        logger.error(traceback.format_exc())
        model_data.inferenceStatus = config.get_status_types().FAILED.value
        model_data.inferenceStatusMessage = (
            MetadataUtils.append_status_message(
                model_data.inferenceStatusMessage or "",
                f"Inference job failed: {describe_exception(e)}",
            )
        )
        output = model_data
        try:
            await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().MODEL.value,
                    partition_key=model_data.projectId,
                ).save,
                model_data.modelId,
                model_data.dict(),
            )
        except ValidationError as ve:
            logger.error(
                f"GetRunInferenceQueueTrigger: Validation error: {ve}\n{traceback.format_exc()}"
            )
        except Exception as inner_e:
            logger.error(
                f"GetRunInferenceQueueTrigger: Error saving failed status: {inner_e}\n{traceback.format_exc()}",
                stack_info=True,
            )

    # Send a message to zip artifacts
    # Separate from upper block because we don't want to fail the model if this fails
    try:
        if (
            output.inferenceStatus
            in (
                config.get_status_types().COMPLETED.value,
                config.get_status_types().FAILED.value,
            )
            and output.inferenceOutputPath
        ):
            try:
                model_artifacts = await asyncio.to_thread(
                    MetadataProcessor(
                        data_type=config.get_metadata_types().MODEL_ARTIFACTS.value,
                        partition_key=model_data.projectId,
                    ).load,
                    model_data.modelId,
                )
            except FileNotFoundError:
                model_artifacts = ModelArtifacts(
                    modelId=model_data.modelId,
                    projectId=model_data.projectId,
                    imageLayerId=model_data.imageLayerId,
                )
            artifact_output = await asyncio.to_thread(
                ArtifactProcessor(
                    partition_key=model_artifacts.projectId,
                    model_artifacts=model_artifacts,
                ).send_to_zip_queue
            )
            await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().MODEL_ARTIFACTS.value,
                    partition_key=model_artifacts.projectId,
                ).save,
                model_artifacts.modelId,
                artifact_output.dict(),
            )
    except Exception as e:
        logger.error(
            f"GetCreateModelRunQueueTrigger: Error sending zip queue message: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )


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


@app.function_name(name="ImagePoisonQueueTrigger")
@app.queue_trigger(
    arg_name="msg",
    queue_name=f'{config.get_queue_config()["image_queue_name"]}-poison',
    connection="AzureWebJobsStorage",
)
async def ImagePoisonQueueHandler(msg: func.QueueMessage) -> None:
    logger.info(
        f'ImagePoisonQueueTrigger function processed a message: {msg.get_body().decode("utf-8")}'
    )
    try:
        poisoned_image_layer = ImageLayer(
            **json.loads(msg.get_body().decode("utf-8"))
        )
        try:
            # This check is to ensure deleted layer does not get recreated here
            existing_image_layer = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().IMAGELAYER.value,
                    partition_key=poisoned_image_layer.projectId,
                ).load,
                poisoned_image_layer.imageLayerId,
            )
        except FileNotFoundError:
            existing_image_layer = None

        if not existing_image_layer:
            logger.info(
                f"ImageLayer {poisoned_image_layer.imageLayerId} not found, likely deleted, skipping processing."
            )
            return

        image_data = ImageLayer(**existing_image_layer)
        image_data.status = config.get_status_types().FAILED.value
        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().IMAGELAYER.value,
                partition_key=image_data.projectId,
            ).save,
            image_data.imageLayerId,
            image_data.dict(),
        )
    except Exception as e:
        logger.error(
            f"ImagePoisonQueueTrigger: Error processing queue message: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )


@app.function_name(name="ArtifactsZipQueueTrigger")
@app.queue_trigger(
    arg_name="msg",
    queue_name=config.get_queue_config()["zip_queue_name"],
    connection="AzureWebJobsStorage",
)
async def GetArtifactsZipQueueMessage(msg: func.QueueMessage) -> None:
    logger.info(
        f'ArtifactsZipQueueTrigger function processed a message: {msg.get_body().decode("utf-8")}'
    )
    try:
        model_artifacts = ModelArtifacts(
            **json.loads(msg.get_body().decode("utf-8"))
        )
        try:
            # This check is to ensure artifacts don't get recreated for deleted models
            model_data = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().MODEL.value,
                    partition_key=model_artifacts.projectId,
                ).load,
                model_artifacts.modelId,
            )
        except FileNotFoundError:
            logger.info(
                f"Data for model {model_artifacts.modelId} not found or incomplete, likely deleted, skipping processing."
            )
            return

        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().MODEL_ARTIFACTS.value,
                partition_key=model_artifacts.projectId,
            ).save,
            model_artifacts.modelId,
            model_artifacts.dict(),
        )
        model_data = Model(**model_data)
        output = await asyncio.to_thread(
            ArtifactProcessor(
                partition_key=model_artifacts.projectId,
                model=model_data,
                model_artifacts=model_artifacts,
            ).process_zip
        )
        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().MODEL_ARTIFACTS.value,
                partition_key=output.projectId,
            ).save,
            output.modelId,
            output.dict(),
        )
        logger.info(
            f'ArtifactsZipQueueTrigger function processed a message: {msg.get_body().decode("utf-8")}'
        )
    except ValueError as e:
        logger.error(
            f"ArtifactsZipQueueTrigger: Invalid JSON: {e}\n{traceback.format_exc()}"
        )
    except Exception as e:
        logger.error(
            f"ArtifactsZipQueueTrigger: Error processing queue message: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        logger.error(traceback.format_exc())
        model_artifacts.zipStatus = config.get_status_types().FAILED.value
        try:
            await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().MODEL_ARTIFACTS.value,
                    partition_key=model_artifacts.projectId,
                ).save,
                model_artifacts.modelId,
                model_artifacts.dict(),
            )
        except ValidationError as ve:
            logger.error(
                f"ArtifactsZipQueueTrigger: Validation error: {ve}\n{traceback.format_exc()}"
            )
        except Exception as inner_e:
            logger.error(
                f"ArtifactsZipQueueTrigger: Error saving failed status: {inner_e}\n{traceback.format_exc()}",
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
