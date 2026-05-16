# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class PrimaryClass(BaseModel):
    """Primary classification definition for labeling tasks.

    Defines a primary class used in the labeling tool for categorizing
    damage or features in imagery analysis.

    Attributes:
        name (str, optional): Human-readable name of the classification.
        color (str, optional): Hex color code for visualization (e.g., '#FF0000').
    """

    name: Optional[str] = Field(default=None)
    color: Optional[str] = Field(default=None)


class Geometry(BaseModel):
    """GeoJSON-style geometry definition.

    Represents spatial geometry data following GeoJSON specification.
    Used for defining geographic features and regions of interest.

    Attributes:
        type (str, optional): Geometry type ('Point', 'Polygon', 'LineString', etc.).
        coordinates (List, optional): Coordinate array structure depends on geometry type.
    """

    type: Optional[str] = Field(default=None)
    coordinates: Optional[List] = Field(default=None)


class Properties(BaseModel):
    """Properties associated with a labeled feature.

    Contains metadata and classification information for geographic features
    identified in imagery analysis and labeling tasks.

    Attributes:
        azureMapsShapeId (str, optional): Azure Maps shape identifier.
        primaryClass (str, optional): Primary classification of the feature.
            Aliased as 'class' for serialization compatibility.
        source (str, optional): Source system or method of creation.
        subType (str, optional): Sub-classification or additional type information.
        radius (float, optional): Radius in meters for circular features.

    Note:
        The primaryClass field is serialized as 'class' to maintain compatibility
        with training systems while avoiding Python reserved keyword conflicts.
    """

    azureMapsShapeId: Optional[str] = Field(default=None)
    primaryClass: Optional[str] = Field(default=None, alias="class")
    source: Optional[str] = Field(default=None)
    subType: Optional[str] = Field(default=None)
    radius: Optional[float] = Field(default=None)

    # This in combination with the field alias above will allow the field
    # to be serialized as 'class' as expected by model training, but
    # deserialized as 'primaryClass' to avoid conflicts with the reserved keyword 'class'
    class Config:
        populate_by_name = True


class Label(BaseModel):
    """Individual label annotation for imagery analysis.

    Represents a single labeled feature within an image, containing both
    geometric and semantic information about identified objects or areas.

    Attributes:
        type (str, optional): Label type identifier.
        properties (Properties, optional): Feature properties and classification.
        id (str, optional): Unique identifier for the label.
        geometry (Geometry, optional): Spatial geometry of the labeled feature.
    """

    type: Optional[str] = Field(default=None)
    properties: Optional[Properties] = Field(default=None)
    id: Optional[str] = Field(default=None)
    geometry: Optional[Geometry] = Field(default=None)


class LabelingImagery(BaseModel):
    """Configuration for imagery display in the labeling tool.

    Defines how imagery should be displayed and accessed within the labeling
    interface, including tile server configurations and display parameters.

    Attributes:
        enabled (bool, optional): Whether imagery display is enabled.
        type (str, optional): Type of imagery service or format.
        tileSize (int, optional): Size of image tiles in pixels.
        tileUrl (str, optional): Base URL for tile service (deprecated).
        preEventTileUrl (str, optional): URL for pre-event imagery tiles.
        postEventTileUrl (str, optional): URL for post-event imagery tiles.
        bounds (List[float], optional): Geographic bounds [minLon, minLat, maxLon, maxLat].
    """

    enabled: Optional[bool] = Field(default=None)
    type: Optional[str] = Field(default=None)
    tileSize: Optional[int] = Field(default=None)
    tileUrl: Optional[str] = Field(default=None)  # Deprecate
    preEventTileUrl: Optional[str] = Field(default=None)
    postEventTileUrl: Optional[str] = Field(default=None)
    bounds: Optional[List[float]] = Field(default=None)


class Feature(BaseModel):
    """Geographic feature definition for labeling tasks.

    Represents a geographic feature that can be assigned to labeling tasks,
    typically corresponding to areas or regions of interest within imagery.

    Attributes:
        type (str, optional): Feature type, defaults to 'Feature' (GeoJSON standard).
        featureId (str, optional): Unique identifier for the feature.
        geometry (Geometry, optional): Spatial geometry of the feature.
        bbox (List[float], optional): Bounding box [minLon, minLat, maxLon, maxLat].
        assignedCount (int, optional): Number of times this feature has been assigned.
    """

    type: Optional[str] = Field(default="Feature")
    featureId: Optional[str] = Field(default=None)
    geometry: Optional[Geometry] = Field(default=None)
    bbox: Optional[List[float]] = Field(default=None)
    assignedCount: Optional[int] = Field(default=0)


class LabelProject(BaseModel):
    """Labeling project containing features, labels, and imagery configuration.

    Represents a complete labeling project that groups together imagery,
    features to be labeled, existing labels, and configuration for the
    labeling interface.

    Attributes:
        projectId (str, optional): Parent project identifier.
        labelprojectId (str, optional): Unique labeling project identifier.
        imageLayerId (str, optional): Associated image layer identifier.
        name (str, optional): Human-readable project name.
        creationDate (str, optional): ISO format creation timestamp.
        labels (List[Label], optional): Collection of existing labels.
        imagery (LabelingImagery, optional): Imagery display configuration.
        features (List[Feature], optional): Features available for labeling.
        dependsOn (tuple, optional): Dependency specification for data relationships.
    """

    projectId: Optional[str] = Field(default=None)
    labelprojectId: Optional[str] = Field(default=None)
    imageLayerId: Optional[str] = Field(default=None)
    name: Optional[str] = Field(default=None)
    creationDate: Optional[str] = Field(default=None)
    labels: Optional[List[Label]] = Field(default_factory=list)
    imagery: Optional[LabelingImagery] = Field(default=None)
    features: Optional[List[Feature]] = Field(default=None)
    dependsOn: Optional[tuple[str, str]] = Field(
        default=("ImageLayer", "imageLayerId")
    )


class TrainingJob(BaseModel):
    """
    Represents a machine learning model training job in the HASTE system.

    This model captures comprehensive training job metadata including execution status,
    timing information, and resource dependencies. Training jobs are managed through
    Azure Batch services and produce trained model artifacts for inference.

    Args:
        trainingjobUid: Unique identifier for the training job instance
        jobId: Azure Batch job identifier for job management and monitoring
        taskId: Azure Batch task identifier within the job
        modelId: Reference to the model configuration being trained
        projectId: Reference to the parent project containing training data
        status: Current execution status (e.g., 'running', 'completed', 'failed')
        trainStartTime: ISO formatted timestamp when training began
        completedEpochs: Number of training epochs completed as string
        approxMinutesToComplete: Estimated remaining training time in minutes
        totalElapsedTime: Total time elapsed since training started
        timePerEpoch: Average time per training epoch for progress estimation
        logs: Training logs and output messages from the job execution
        artifactZipJobUid: Reference to zip job for packaging training artifacts
        creationDate: ISO formatted timestamp when job was created
        completedDate: ISO formatted timestamp when job finished
        dependsOn: Dependency tuple specifying parent resource type and ID

    Example:
        ```python
        training_job = TrainingJob(
            trainingjobUid="train_123",
            modelId="model_456",
            projectId="proj_789",
            status="running",
            completedEpochs="5"
        )
        ```
    """

    trainingjobUid: Optional[str] = Field(default=None)
    jobId: Optional[str] = Field(default=None)
    taskId: Optional[str] = Field(default=None)
    modelId: Optional[str] = Field(default=None)
    projectId: Optional[str] = Field(default=None)
    status: Optional[str] = Field(default=None)
    trainStartTime: Optional[str] = Field(default=None)
    completedEpochs: Optional[str] = Field(default="0")
    approxMinutesToComplete: Optional[str] = Field(default="")
    totalElapsedTime: Optional[str] = Field(default="")
    timePerEpoch: Optional[str] = Field(default="")
    logs: Optional[str] = Field(default=None)
    artifactZipJobUid: Optional[str] = Field(default=None)
    creationDate: Optional[str] = Field(default=None)
    completedDate: Optional[str] = Field(default=None)
    dependsOn: Optional[tuple[str, str]] = Field(default=("Model", "modelId"))


class InferenceJob(BaseModel):
    """
    Represents a machine learning model inference job in the HASTE system.

    This model captures inference job execution metadata for applying trained models
    to new imagery data. Inference jobs run on Azure Batch services and generate
    prediction outputs for analysis and visualization.

    Args:
        uid: Unique identifier for the inference job instance, DEPRECATED
        jobId: Azure Batch job identifier for job management and monitoring
        taskId: Azure Batch task identifier within the job
        modelId: Reference to the trained model used for inference
        projectId: Reference to the parent project containing input imagery
        status: Current execution status (e.g., 'running', 'completed', 'failed')
        creationDate: ISO formatted timestamp when job was created
        completedDate: ISO formatted timestamp when job finished
        logs: Inference logs and output messages from the job execution
        artifactZipJobUid: Reference to zip job for packaging inference results
        dependsOn: Dependency tuple specifying parent resource type and ID

    Example:
        ```python
        inference_job = InferenceJob(
            uid="inf_123",
            modelId="model_456",
            projectId="proj_789",
            status="queued"
        )
        ```
    """

    uid: Optional[str] = Field(default=None)
    jobId: Optional[str] = Field(default=None)
    taskId: Optional[str] = Field(default=None)
    modelId: Optional[str] = Field(default=None)
    projectId: Optional[str] = Field(default=None)
    status: Optional[str] = Field(default=None)
    creationDate: Optional[str] = Field(default=None)
    completedDate: Optional[str] = Field(default=None)
    logs: Optional[str] = Field(default="")
    artifactZipJobUid: Optional[str] = Field(default=None)
    dependsOn: Optional[tuple[str, str]] = Field(default=("Model", "modelId"))


# TODO - is this necessary, given checkpoint files will be a dir?
class Checkpoint(BaseModel):
    """
    Represents a model checkpoint saved during training in the HASTE system.

    This model captures checkpoint metadata for model state persistence during
    training processes. Checkpoints enable training resumption and provide
    access to intermediate model states for evaluation and deployment.

    Args:
        checkpointId: Unique identifier for the checkpoint instance
        checkpointUrl: URL location of the checkpoint file in storage
        checkpointPath: File system path to the checkpoint data
        modelId: Reference to the model that generated this checkpoint
        projectId: Reference to the parent project containing the model
        creationDate: ISO formatted timestamp when checkpoint was created
        dependsOn: Dependency tuple specifying parent resource type and ID

    Note:
        Checkpoints may be stored as directories containing multiple files
        rather than single checkpoint files, depending on the model framework.

    Example:
        ```python
        checkpoint = Checkpoint(
            checkpointId="ckpt_123",
            modelId="model_456",
            checkpointPath="/models/checkpoint_epoch_10.pth"
        )
        ```
    """

    checkpointId: Optional[str] = Field(default=None)
    checkpointUrl: Optional[str] = Field(default=None)
    checkpointPath: Optional[str] = Field(default=None)
    modelId: Optional[str] = Field(default=None)
    projectId: Optional[str] = Field(default=None)
    creationDate: Optional[str] = Field(default=None)
    dependsOn: Optional[tuple[str, str]] = Field(default=("Model", "modelId"))


class ModelRequest(BaseModel):
    """
    Represents a request to create or configure a model in the HASTE system.

    This model captures the parameters needed to initiate model creation,
    linking together project data, imagery layers, and labeling information
    required for training setup.

    Args:
        modelId: Unique identifier for the requested model
        projectId: Reference to the parent project containing training data
        imageLayerId: Reference to the imagery layer for model input
        labelProjectId: Reference to the labeling project providing ground truth
        status: Current status of the model request (e.g., 'pending', 'approved')

    Example:
        ```python
        model_request = ModelRequest(
            modelId="model_123",
            projectId="proj_456",
            imageLayerId="layer_789",
            labelProjectId="labels_101"
        )
        ```
    """

    modelId: Optional[str] = Field(default=None)
    projectId: Optional[str] = Field(default=None)
    imageLayerId: Optional[str] = Field(default=None)
    labelProjectId: Optional[str] = Field(default=None)
    status: Optional[str] = Field(default=None)


class Model(BaseModel):
    """
    Represents a machine learning model configuration and state in the HASTE system.

    This comprehensive model captures all aspects of ML model lifecycle including
    training configuration, execution state, inference results, and output artifacts.
    Models are trained on labeled imagery data and deployed for damage detection.

    Args:
        modelId: Unique identifier for the model instance
        projectId: Reference to the parent project containing model data
        imageLayerId: Reference to the imagery layer used for training
        labelprojectId: Reference to the labeling project providing ground truth data
        name: Human-readable name for the model
        labelsCount: Number of training labels available for the model
        baseModel: Base model architecture (e.g., 'ResNet50', 'EfficientNet')
        baseModelWeightsUrl: URL to pre-trained base model weights
        outputModelWeightsUrl: URL to trained model weights after completion
        learningRate: Training learning rate parameter as string
        batchSize: Training batch size parameter as string
        maxEpochs: Maximum training epochs parameter as string
        userId: Identifier of the user who created the model
        creationDate: ISO formatted timestamp when model was created
        trainDate: ISO formatted timestamp when training began
        status: Current model status (e.g., 'training', 'completed', 'failed')
        currentStep: Current training step number for progress tracking
        progressPct: Training progress percentage (0.0 to 100.0)
        totalSteps: Total number of training steps expected
        statusMessage: Detailed status message for current model state
        autoRunInference: Whether to automatically run inference after training
        checkpointPath: File path to saved model checkpoint
        initialWeightsUrl: URL to initial weights file for model initialization
        trainingOutputPath: Directory path for training output artifacts
        inferenceOutputPath: Directory path for inference output artifacts
        trainingJob: Associated training job execution details
        inferenceJobs: List of inference jobs run with this model
        inferenceStatus: Current status of inference execution
        inferenceCurrentStep: Current inference step for progress tracking
        inferenceProgressPct: Inference progress percentage (0.0 to 100.0)
        inferenceTotalSteps: Total number of inference steps expected
        inferenceUid: Unique identifier for current inference execution, DEPRECATED
        currentInferenceTaskId: Current inference task identifier
        inferenceStatusMessage: Detailed inference status message
        predictedDamageLayerUrl: URL to predicted damage layer output
        gpkgUrl: URL to GeoPackage output file with predictions
        labelsUrl: URL to labels file used for training
        dependsOn: Dependency tuple specifying parent resource type and ID

    Example:
        ```python
        model = Model(
            modelId="model_123",
            name="Building Damage Detection v1",
            baseModel="ResNet50",
            learningRate="0.001",
            batchSize="32",
            maxEpochs="100",
            autoRunInference=True
        )
        ```
    """

    modelId: Optional[str] = Field(default=None)
    projectId: Optional[str] = Field(default=None)
    imageLayerId: Optional[str] = Field(default=None)
    labelprojectId: Optional[str] = Field(default=None)
    name: Optional[str] = Field(default=None)
    labelsCount: Optional[int] = Field(default=0)
    baseModel: Optional[str] = Field(default=None)
    baseModelWeightsUrl: Optional[str] = Field(default=None)
    initialWeightsUrl: Optional[str] = Field(default=None)
    outputModelWeightsUrl: Optional[str] = Field(default=None)
    learningRate: Optional[str] = Field(default=None)
    batchSize: Optional[str] = Field(default=None)
    maxEpochs: Optional[str] = Field(default=None)
    userId: Optional[str] = Field(default=None)
    creationDate: Optional[str] = Field(default=None)
    trainDate: Optional[str] = Field(default=None)
    status: Optional[str] = Field(default=None)
    currentStep: Optional[int] = Field(default=0)
    progressPct: Optional[float] = Field(default=0.0)
    totalSteps: Optional[int] = Field(default=0)
    statusMessage: Optional[str] = Field(default="")
    autoRunInference: Optional[bool] = Field(default=True)
    checkpointPath: Optional[str] = Field(default=None)
    trainingOutputPath: Optional[str] = Field(default=None)
    inferenceOutputPath: Optional[str] = Field(default=None)
    trainingJob: Optional[TrainingJob] = Field(default=None)
    inferenceJobs: Optional[List[InferenceJob]] = Field(default_factory=list)
    inferenceStatus: Optional[str] = Field(default=None)
    inferenceCurrentStep: Optional[int] = Field(default=0)
    inferenceProgressPct: Optional[float] = Field(default=0.0)
    inferenceTotalSteps: Optional[int] = Field(default=0)
    inferenceUid: Optional[str] = Field(default=None)
    currentInferenceTaskId: Optional[str] = Field(default=None)
    inferenceStatusMessage: Optional[str] = Field(default="")
    predictedDamageLayerUrl: Optional[str] = Field(default=None)
    gpkgUrl: Optional[str] = Field(default=None)
    labelsUrl: Optional[str] = Field(default=None)
    dependsOn: Optional[tuple[str, str]] = Field(
        default=("ImageLayer", "imageLayerId")
    )


class ZipTypeEnum(str, Enum):
    """
    Enumeration of zip job types in the HASTE system.

    Defines the supported types of artifact packaging operations,
    distinguishing between training and inference output archiving.

    Attributes:
        TRAINING: Zip job for packaging training artifacts and outputs
        INFERENCE: Zip job for packaging inference results and predictions
    """

    TRAINING = "training"
    INFERENCE = "inference"


class ZipJob(BaseModel):
    """
    Represents a file archiving job for packaging model artifacts in the HASTE system.

    This model captures zip job execution details for packaging training outputs,
    inference results, and other model artifacts into downloadable archives.
    Zip jobs run on Azure Batch services to handle large file collections.

    Args:
        projectId: Reference to the parent project containing artifacts
        imageLayerId: Reference to the imagery layer associated with artifacts
        modelId: Reference to the model that generated the artifacts
        uid: Unique identifier for the zip job instance, DEPRECATED
        jobId: Azure Batch job identifier for job management and monitoring
        taskId: Azure Batch task identifier within the job
        status: Current execution status (e.g., 'running', 'completed', 'failed')
        logs: Job logs and output messages from the execution
        srcArtifactPaths: List of source file paths to include in the archive
        dstZipPath: Destination path for the generated zip file
        creationDate: ISO formatted timestamp when job was created
        completedDate: ISO formatted timestamp when job finished
        dependsOn: Dependency tuple specifying parent resource type and ID

    Example:
        ```python
        zip_job = ZipJob(
            projectId="proj_123",
            modelId="model_456",
            srcArtifactPaths=["/models/weights.pth", "/logs/training.log"],
            dstZipPath="/archives/model_artifacts.zip"
        )
        ```
    """

    projectId: Optional[str] = Field(default=None)
    imageLayerId: Optional[str] = Field(default=None)
    modelId: Optional[str] = Field(default=None)
    uid: Optional[str] = Field(default=None)
    # jobType: Optional[str] = Field(default=None)
    jobId: Optional[str] = Field(default=None)
    taskId: Optional[str] = Field(default=None)
    status: Optional[str] = Field(default=None)
    logs: Optional[str] = Field(default="")
    srcArtifactPaths: Optional[List[str]] = Field(default_factory=list)
    dstZipPath: Optional[str] = Field(default=None)
    creationDate: Optional[str] = Field(default=None)
    completedDate: Optional[str] = Field(default=None)
    dependsOn: Optional[tuple[str, str]] = Field(
        default=("ModelArtifacts", "modelId")
    )


class ModelArtifacts(BaseModel):
    """
    Represents model artifact management and packaging state in the HASTE system.

    This model tracks the status and availability of model output artifacts,
    including training results, inference outputs, and packaged downloads.
    Coordinates zip job execution for artifact archiving and distribution.

    Args:
        projectId: Reference to the parent project containing the model
        imageLayerId: Reference to the imagery layer used by the model
        modelId: Reference to the model that generated the artifacts
        currentZipJobUid: Reference to the active zip job packaging artifacts
        zipUrl: URL to the downloadable zip archive of model artifacts
        zipStatus: Current status of the zip packaging operation
        zipStatusMessage: Detailed message about zip operation status
        zipJobs: List of zip jobs associated with this model's artifacts
        dependsOn: Dependency tuple specifying parent resource type and ID

    Example:
        ```python
        artifacts = ModelArtifacts(
            projectId="proj_123",
            modelId="model_456",
            zipStatus="completed",
            zipUrl="https://storage.blob.core.windows.net/artifacts/model_456.zip"
        )
        ```
    """

    projectId: Optional[str] = Field(default=None)
    imageLayerId: Optional[str] = Field(default=None)
    modelId: Optional[str] = Field(default=None)
    currentZipJobUid: Optional[str] = Field(default=None)
    zipUrl: Optional[str] = Field(default=None)
    trainingZipUrl: Optional[str] = Field(default=None)
    trainingZipSize: Optional[int] = Field(default=None)
    inferenceZipUrl: Optional[str] = Field(default=None)
    inferenceZipSize: Optional[int] = Field(default=None)
    zipStatus: Optional[str] = Field(default=None)
    zipStatusMessage: Optional[str] = Field(default="")
    zipJobs: Optional[List[ZipJob]] = Field(default_factory=list)
    dependsOn: Optional[tuple[str, str]] = Field(default=("Model", "modelId"))


class ImageryPreprocessJob(BaseModel):
    """
    Represents an imagery preprocessing job in the HASTE system.

    This model captures preprocessing job execution details for preparing
    raw imagery data for analysis and machine learning workflows.
    Preprocessing jobs run on Azure Batch services to handle large imagery datasets.

    Args:
        projectId: Reference to the parent project containing the imagery
        imageLayerId: Reference to the imagery layer being processed
        jobId: Azure Batch job identifier for job management and monitoring
        taskId: Azure Batch task identifier within the job
        status: Current execution status (e.g., 'running', 'completed', 'failed')
        logs: Processing logs and output messages from the job execution
        creationDate: ISO formatted timestamp when job was created
        completedDate: ISO formatted timestamp when job finished
        dependsOn: Dependency tuple specifying parent resource type and ID

    Example:
        ```python
        preprocess_job = ImageryPreprocessJob(
            projectId="proj_123",
            imageLayerId="layer_456",
            status="processing"
        )
        ```
    """

    projectId: Optional[str] = Field(default=None)
    imageLayerId: Optional[str] = Field(default=None)
    jobId: Optional[str] = Field(default=None)
    taskId: Optional[str] = Field(default=None)
    status: Optional[str] = Field(default=None)
    logs: Optional[str] = Field(default=None)
    creationDate: Optional[str] = Field(default=None)
    completedDate: Optional[str] = Field(default=None)
    dependsOn: Optional[tuple[str, str]] = Field(
        default=("ImageLayer", "imageLayerId")
    )


class ImageLayer(BaseModel):
    """
    Represents an imagery layer containing satellite or aerial imagery data in the HASTE system.

    This comprehensive model manages imagery datasets including pre-event and post-event
    imagery for damage assessment, along with processing state, normalization parameters,
    and associated analysis models. Supports multiple imagery sources and formats.

    Args:
        imageLayerId: Unique identifier for the imagery layer
        projectId: Reference to the parent project containing this layer
        labelProjectId: Reference to associated labeling project for ground truth
        name: Human-readable name for the imagery layer
        description: Detailed description of the imagery content and purpose
        format: Imagery file format (e.g., 'GeoTIFF', 'COG')
        sourceType: Legacy field for imagery source type (deprecated)
        sourceTypePreEvent: Source type for pre-event imagery (e.g., 'Sentinel-2', 'WorldView')
        sourceTypePostEvent: Source type for post-event imagery
        imageryCaptureDatePreEvent: ISO formatted capture date for pre-event imagery
        imageryCaptureDatePostEvent: ISO formatted capture date for post-event imagery
        normalizationFactor: Scaling factor for pixel value normalization
        imageryCaptureDate: Legacy field for capture date (deprecated)
        preEventImageryUrls: List of URLs to pre-event imagery files
        preEventPreviewUrls: List of URLs to pre-event preview/thumbnail images
        preEventMosaicCogImageryUrl: URL to pre-event mosaic Cloud Optimized GeoTIFF
        preEventProcessedImageryUrl: URL to preprocessed pre-event imagery
        postEventImageryUrls: List of URLs to post-event imagery files
        postEventPreviewUrls: List of URLs to post-event preview/thumbnail images
        postEventMosaicCogImageryUrl: URL to post-event mosaic Cloud Optimized GeoTIFF
        postEventProcessedImageryUrl: URL to preprocessed post-event imagery
        processedImageryUrls: Legacy field for processed imagery URLs (deprecated)
        rawImageryUrls: Legacy field for raw imagery URLs (deprecated)
        previewSourceImageryUrls: Legacy field for preview URLs (deprecated)
        preprocessJob: Associated preprocessing job for this imagery layer
        imageryPath: File system path to imagery data
        userId: Identifier of the user who created the layer
        status: Current processing status (e.g., 'processing', 'ready', 'failed')
        statusMessage: Detailed status message for current processing state
        currentStep: Current processing step number for progress tracking
        totalSteps: Total number of processing steps expected
        progressPct: Processing progress percentage (0.0 to 100.0)
        creationDate: ISO formatted timestamp when layer was created
        modelCount: Number of models trained on this imagery layer
        labelProjectCount: Number of labeling projects using this layer
        autoFineTune: Whether to automatically fine-tune models with this imagery
        models: List of models associated with this imagery layer
        normalizationMeans: Mean values for each spectral band for normalization
        normalizationStds: Standard deviation values for each spectral band
        labelProject: Associated labeling project providing ground truth data
        labelsUrl: URL to labels file for the imagery layer
        buildingFootprintsUrl: URL to the cached Overture Maps building
            footprint GeoPackage scoped to this layer's AOI. Populated
            by the imageryprep workflow; consumed by inference instead of
            re-downloading on every model run.
        dependsOn: Dependency tuple specifying parent resource type and ID

    Example:
        ```python
        imagery_layer = ImageLayer(
            imageLayerId="layer_123",
            name="Hurricane Harvey - Houston",
            sourceTypePreEvent="Sentinel-2",
            sourceTypePostEvent="WorldView-3",
            imageryCaptureDatePreEvent="2017-08-20T00:00:00Z",
            imageryCaptureDatePostEvent="2017-08-30T00:00:00Z"
        )
        ```
    """

    imageLayerId: Optional[str] = Field(default=None)
    projectId: Optional[str] = Field(default=None)
    labelProjectId: Optional[str] = Field(default=None)
    name: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    format: Optional[str] = Field(default=None)
    sourceType: Optional[str] = Field(default=None)  # Deprecate
    sourceTypePreEvent: Optional[str] = Field(default=None)
    sourceTypePostEvent: Optional[str] = Field(default=None)
    imageryCaptureDatePreEvent: Optional[str] = Field(default=None)
    imageryCaptureDatePostEvent: Optional[str] = Field(default=None)
    normalizationFactor: Optional[float] = Field(default=None)
    imageryCaptureDate: Optional[str] = Field(default=None)  # Deprecate
    preEventImageryUrls: Optional[list[str]] = Field(default=None)
    preEventPreviewUrls: Optional[list[str]] = Field(default_factory=list)
    preEventMosaicCogImageryUrl: Optional[str] = Field(default=None)
    preEventProcessedImageryUrl: Optional[str] = Field(default=None)
    postEventImageryUrls: Optional[list[str]] = Field(default=None)
    postEventPreviewUrls: Optional[list[str]] = Field(default_factory=list)
    postEventMosaicCogImageryUrl: Optional[str] = Field(default=None)
    postEventProcessedImageryUrl: Optional[str] = Field(default=None)
    processedImageryUrls: Optional[list[str]] = Field(
        default=None
    )  # TODO - TO BE DEPRECATED and replaced with preEventProcessedImageryUrls and postEventProcessedImageryUrls
    rawImageryUrls: Optional[list[str]] = Field(default=None)  # TODO Deprecate
    previewSourceImageryUrls: Optional[list[str]] = Field(
        default=None
    )  # TODO Deprecate
    preprocessJob: Optional[ImageryPreprocessJob] = Field(default=None)
    imageryPath: Optional[str] = Field(default=None)
    userId: Optional[str] = Field(default=None)
    status: Optional[str] = Field(default=None)
    statusMessage: Optional[str] = Field(default="")
    currentStep: Optional[int] = Field(default=0)
    totalSteps: Optional[int] = Field(default=0)
    progressPct: Optional[float] = Field(default=0.0)
    creationDate: Optional[str] = Field(default=None)
    modelCount: Optional[int] = Field(default=0)
    labelProjectCount: Optional[int] = Field(default=0)
    autoFineTune: Optional[bool] = Field(default=False)
    models: Optional[List[Model]] = Field(default=None)
    normalizationMeans: Optional[List[int]] = Field(default_factory=list)
    normalizationStds: Optional[List[int]] = Field(default_factory=list)
    labelProject: Optional[LabelProject] = Field(default=None)
    labelsUrl: Optional[str] = Field(default=None)
    buildingFootprintsUrl: Optional[str] = Field(default=None)
    dependsOn: Optional[tuple[str, str]] = Field(
        default=("Project", "projectId")
    )


class Project(BaseModel):
    """
    Represents a top-level project in the HASTE system for damage assessment analysis.

    This model serves as the root container for all project-related resources including
    imagery layers, labeling projects, models, and analysis results. Projects typically
    correspond to specific disaster events or geographical areas of interest.

    Args:
        projectId: Unique identifier for the project
        name: Human-readable name for the project
        description: Detailed description of the project scope and objectives
        affectedCountries: List of countries affected by the event being analyzed
        userId: Identifier of the user who created the project
        eventDate: ISO formatted date when the disaster event occurred
        creationDate: ISO formatted timestamp when project was created
        imageLayerCount: Number of imagery layers associated with the project
        imageLayer: List of imagery layers containing satellite/aerial data
        primaryClasses: List of damage classification categories for labeling

    Example:
        ```python
        project = Project(
            projectId="proj_123",
            name="Hurricane Harvey 2017 - Houston Assessment",
            description="Building damage assessment for Hurricane Harvey impact in Houston",
            affectedCountries=["United States"],
            eventDate="2017-08-25T00:00:00Z"
        )
        ```
    """

    projectId: Optional[str] = Field(default=None)
    name: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    affectedCountries: Optional[List[str]] = Field(default=None)
    userId: Optional[str] = Field(default=None)
    eventDate: Optional[str] = Field(default=None)
    eventTypes: Optional[List[str]] = Field(default=None)
    creationDate: Optional[str] = Field(default=None)
    imageLayerCount: Optional[int] = Field(default=0)
    imageLayer: Optional[List[ImageLayer]] = Field(default=None)
    primaryClasses: Optional[List[PrimaryClass]] = Field(default=None)


class Projects(BaseModel):
    """
    Container model for managing multiple Project instances in the HASTE system.

    This model provides a structured way to handle collections of projects,
    typically used in API responses and batch operations.

    Args:
        root: List of Project instances managed by this container

    Example:
        ```python
        projects = Projects(
            root=[
                Project(name="Hurricane Harvey Assessment"),
                Project(name="California Wildfire Analysis")
            ]
        )
        ```
    """

    root: List[Project] = Field(default_factory=list)
