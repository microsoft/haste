# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import asyncio
import base64
import binascii
import json
import os
import re
import traceback
from urllib.parse import urlparse

import azure.functions as func  # type: ignore
import requests  # type: ignore
from hastegeo.core.config import Config
from hastegeo.core.models.admin import AdminConfig
from hastegeo.core.models.projects import (
    BuildingValidation,
    ImageLayer,
    LabelProject,
    Model,
    ModelArtifacts,
    Project,
)
from hastegeo.core.models.stats import (
    ImageLayerStats,
    ProjectsSummary,
    ProjectStats,
    StatsRequest,
)
from hastegeo.core.models.training import CatalogModel
from hastegeo.core.models.users import User
from hastegeo.core.models.visualizer import Imagery, Visualizer
from hastegeo.core.processors.artifacts import ArtifactProcessor
from hastegeo.core.processors.imagery import ImageryPreProcessor
from hastegeo.core.processors.inference import InferencePreprocessor
from hastegeo.core.processors.metadata import MetadataProcessor
from hastegeo.core.processors.stats import StatsPreProcessor
from hastegeo.core.processors.train import TrainPreprocessor
from hastegeo.core.processors.uploader import FileUploader
from hastegeo.core.utils.data import convert_json_to_geojson, filter_roles
from hastegeo.core.utils.logs import Logger
from hastegeo.core.utils.metadata import MetadataUtils
from hastegeo.core.utils.url_allowlist import (
    ALLOWED_HOST_DESCRIPTION,
    validate_imagery_url,
)
from hastegeo.core.utils.user import InvitationManager, UserManager
from pydantic import ValidationError  # type: ignore

config = Config()
process_id = MetadataUtils.generate_short_int_id()
short_date_stamp = MetadataUtils.get_short_date()
log_dir = os.path.join(config.DATA_DIR, "logs", short_date_stamp)
logger = Logger.get_logger(
    __name__, f"{__name__}_pid_{process_id}.log", log_dir=log_dir
)
app = func.FunctionApp()

# Development mode check - when running locally with Docker/Azurite
# Set DEVELOPMENT_MODE=true to disable function key authentication
DEVELOPMENT_MODE = (
    os.environ.get("DEVELOPMENT_MODE", "false").lower() == "true"
)
AUTH_LEVEL = (
    func.AuthLevel.ANONYMOUS if DEVELOPMENT_MODE else func.AuthLevel.FUNCTION
)


# Strict allowlist regexes for request parameters. Bound length and character
# set to defend against injection, path traversal, and oversized inputs.
_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,253}\.[A-Za-z]{2,24}$"
)
# Short numeric IDs produced by MetadataUtils.generate_short_int_id() — used
# for modelId (currently 4 zero-padded digits, e.g. "5557"). Width is bounded
# to leave room for the field to grow without ever admitting an unbounded
# string into log lines or blob paths.
_SHORT_INT_ID_RE = re.compile(r"^[0-9]{1,8}$")


def _require_guid_param(req: func.HttpRequest, name: str) -> str:
    """Return a request parameter validated as a canonical GUID, or raise ValueError."""
    value = req.params.get(name)
    if not value:
        raise ValueError(f"Missing required parameter: {name}")
    if not _GUID_RE.match(value):
        raise ValueError(f"Invalid format for parameter: {name}")
    return value


def _require_short_int_id_param(req: func.HttpRequest, name: str) -> str:
    """Return a request parameter validated as a short integer id, or raise ValueError.

    Used for fields populated by MetadataUtils.generate_short_int_id()
    (notably modelId), which produces 1-8 digit numeric strings rather
    than canonical GUIDs.
    """
    value = req.params.get(name)
    if not value:
        raise ValueError(f"Missing required parameter: {name}")
    if not _SHORT_INT_ID_RE.match(value):
        raise ValueError(f"Invalid format for parameter: {name}")
    return value


def _require_email_param(req: func.HttpRequest, name: str) -> str:
    """Return a request parameter validated as an email address, or raise ValueError."""
    value = req.params.get(name)
    if not value:
        raise ValueError(f"Missing required parameter: {name}")
    if not _EMAIL_RE.match(value):
        raise ValueError(f"Invalid format for parameter: {name}")
    return value


def _bad_request(name_or_message: str) -> func.HttpResponse:
    logger.warning(f"Rejected request: {name_or_message}")
    return func.HttpResponse("Invalid request parameters.", status_code=400)


def _split_blob_url(url: str) -> tuple[str, str]:
    """Extract (container_name, blob_name) from a blob URL.

    Handles both real-Azure URLs (https://<account>.blob.core.windows.net
    /<container>/<blob>?<sas>) and Azurite path-style URLs
    (http://<host>:<port>/<account>/<container>/<blob>?<sas>), including
    the docker-internal `http://azurite:10000/...` form. We can't just
    use azure.storage.blob.BlobClient.from_blob_url here because that
    helper only recognizes hosts matching `*.blob.core.windows.net`,
    `localhost`, or `127.0.0.1`; with the docker-network hostname
    `azurite` it silently falls into a wrong-shape parse that treats
    the second-to-last path segment as the container name (which then
    produces ContainerNotFound at download time).

    Detection: any host outside `*.blob.core.windows.net` is treated as
    Azurite-style and the first path segment is consumed as the account
    name. This matches the URLs `MetadataProcessor` produces in both
    dev (azurite:10000 / devstoreaccount1) and prod (Azure Blob).
    """
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    host = (parsed.hostname or "").lower()
    if host.endswith(".blob.core.windows.net"):
        # Real Azure: /<container>/<blob...>
        if len(parts) < 2:
            raise ValueError(f"Blob URL missing container/blob: {url}")
        return parts[0], "/".join(parts[1:])
    # Azurite path-style: /<account>/<container>/<blob...>
    if len(parts) < 3:
        raise ValueError(
            f"Azurite-style blob URL missing account/container/blob: {url}"
        )
    return parts[1], "/".join(parts[2:])


def _validate_imagery_urls(image_data: ImageLayer) -> str | None:
    """Validate user-submitted imagery URLs against the host allowlist.

    Returns a user-facing error message if any URL is not on the allowlist,
    or None if all URLs validate. Full URLs are logged server-side; only
    rejected hostnames are surfaced to the client.
    """
    rejected_hosts: list[str] = []
    for field_name in ("preEventImageryUrls", "postEventImageryUrls"):
        urls = getattr(image_data, field_name, None) or []
        for idx, url in enumerate(urls):
            if not url:
                continue
            try:
                validate_imagery_url(url)
            except ValueError:
                host = urlparse(url).hostname or "<unparseable>"
                logger.warning(
                    f"PutLayer rejected URL not on allowlist: "
                    f"field={field_name} index={idx} host={host}"
                )
                rejected_hosts.append(host)
    if rejected_hosts:
        unique_hosts = sorted(set(rejected_hosts))
        return (
            "One or more imagery URLs are not on the allowlist of permitted "
            f"hosts ({ALLOWED_HOST_DESCRIPTION}). "
            f"Rejected host(s): {', '.join(unique_hosts)}."
        )
    return None


def _decode_client_principal(req: func.HttpRequest) -> dict | None:
    """Decode SWA client principal header when present."""
    principal_header = req.headers.get("x-ms-client-principal")
    if not principal_header:
        return None

    try:
        padding = "=" * (-len(principal_header) % 4)
        decoded = base64.b64decode(principal_header + padding).decode("utf-8")
        principal = json.loads(decoded)
        return principal if isinstance(principal, dict) else None
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as e:
        logger.warning(
            f"Failed to decode x-ms-client-principal header: {type(e).__name__}"
        )
        return None


def _require_roles(
    req: func.HttpRequest, allowed_roles: set[str]
) -> func.HttpResponse | None:
    """Enforce identity and role checks for privileged operations."""
    if DEVELOPMENT_MODE:
        return None

    principal = _decode_client_principal(req)
    if principal is None:
        return func.HttpResponse(
            "Forbidden. Missing caller identity.", status_code=403
        )

    user_id = principal.get("userId") or principal.get("userDetails")
    if not user_id:
        return func.HttpResponse(
            "Forbidden. Missing caller identity.", status_code=403
        )

    raw_roles = principal.get("userRoles")
    roles = (
        {role.lower().strip() for role in raw_roles if isinstance(role, str)}
        if isinstance(raw_roles, list)
        else set()
    )
    if not roles.intersection({role.lower() for role in allowed_roles}):
        return func.HttpResponse(
            "Forbidden. Administrator role required.", status_code=403
        )

    return None


def add_cors_headers(response: func.HttpResponse) -> func.HttpResponse:
    """Add CORS headers to the response - handled by nginx proxy in local dev."""
    # CORS headers are now handled by nginx reverse proxy
    # to avoid duplicate headers
    return response


@app.route(
    route="options/{*path}",
    auth_level=func.AuthLevel.ANONYMOUS,
    methods=["OPTIONS"],
)
def handle_options(req: func.HttpRequest) -> func.HttpResponse:
    """Handle preflight OPTIONS requests for CORS."""
    response = func.HttpResponse("", status_code=200)
    return add_cors_headers(response)


@app.route(
    route="UploadFileByChunk",
    auth_level=AUTH_LEVEL,
    methods=["POST", "OPTIONS"],
)
async def UploadFileByChunk(req: func.HttpRequest) -> func.HttpResponse:
    """
    Upload large files in chunks for efficient processing of geospatial datasets.

    This endpoint handles chunked file uploads for large geospatial imagery files,
    supporting resumable uploads and parallel chunk processing. Files are uploaded
    in multiple chunks and assembled server-side for efficient handling of large
    datasets that would be impractical to upload as single files.

    The chunked upload process supports:
    - Resumable uploads if connection is interrupted
    - Progress tracking and validation
    - Automatic file assembly upon completion
    - Error handling for individual chunks

    Args:
        req (func.HttpRequest): HTTP request containing multipart form data with:
            - project_id (str): Unique identifier for the target project
            - file_id (str): Unique identifier for the file being uploaded
            - chunk_number (int): Current chunk number (0-based index)
            - total_chunks (int): Total number of chunks for this file
            - action (str): Upload action type ('upload', 'finalize', etc.)
            - chunk (file): Binary chunk data for this segment

    Returns:
        func.HttpResponse: JSON response containing:
            - status (str): Upload status ('success', 'partial', 'error')
            - chunk_info (dict): Information about processed chunk
            - upload_progress (float): Overall upload progress percentage
            - file_info (dict): File metadata if upload is complete

    Raises:
        ValidationError: If required parameters are missing or invalid
        StorageError: If chunk storage operations fail
        FileAssemblyError: If final file assembly fails

    Example:
        POST /api/UploadFileByChunk
        Content-Type: multipart/form-data

        Form data:
        - project_id: "proj_12345"
        - file_id: "imagery_layer_001"
        - chunk_number: "0"
        - total_chunks: "10"
        - action: "upload"
        - chunk: <binary data>
    """
    logger.info("UploadFileChunk HTTP trigger function processed a request.")
    try:
        form_data = req.form
        project_id = form_data.get("project_id")
        file_id = form_data.get("file_id")
        chunk_number = form_data.get("chunk_number")
        total_chunks = form_data.get("total_chunks")
        action = form_data.get("action")
        file_chunk = req.files.get("chunk")

        def missing_param_response(param_name):
            return func.HttpResponse(
                f"{param_name} parameter is missing.", status_code=400
            )

        if not file_id:
            return missing_param_response("file_id")
        if not chunk_number:
            return missing_param_response("chunk_number")
        if not total_chunks:
            return missing_param_response("total_chunks")
        if not file_chunk:
            return missing_param_response("chunk")
        if not action:
            action = "add"

        chunk_number = int(chunk_number)
        total_chunks = int(total_chunks)
        file_uploader = FileUploader(project_id=project_id, config=config)
        output = await asyncio.to_thread(
            file_uploader.save_chunk,
            file_id=file_id,
            chunk_number=chunk_number,
            total_chunks=total_chunks,
            chunk_data=file_chunk,
            action=action,
        )
        return func.HttpResponse(json.dumps(output.dict()), status_code=200)

    except Exception as e:
        logger.error(
            f"Error uploading file chunk: {e}\n{traceback.format_exc()}"
        )
        return func.HttpResponse(
            "Error uploading file chunk.", status_code=500
        )


@app.route(
    route="GetDashboardData",
    auth_level=AUTH_LEVEL,
    methods=["GET"],
)
async def GetDashboardData(req: func.HttpRequest) -> func.HttpResponse:
    """
    Retrieve comprehensive dashboard statistics for the HASTE application.

    This endpoint aggregates project summary statistics including project counts,
    layer information, model status, and system-wide metrics. If cached statistics
    are not available, it will automatically generate them.

    Args:
        req (func.HttpRequest): The HTTP request object containing dashboard data request.

    Returns:
        func.HttpResponse: JSON response containing dashboard statistics with the following structure:
            - projects: List of project summaries sorted by creation date (newest first)
            - project_count: Total number of projects in the system
            - layer_count: Total number of image layers across all projects
            - model_count: Total number of models across all projects
            - Additional aggregated statistics

    Raises:
        FileNotFoundError: If stats cache is not found, triggers automatic stats generation
        Exception: For any other processing errors, returns 500 status code

    Example Response:
        ```json
        {
            "projects": [
                {
                    "projectId": "proj_123",
                    "name": "Hurricane Harvey Assessment",
                    "creationDate": "2023-08-01T12:00:00Z",
                    "imageLayerCount": 3,
                    "modelCount": 2
                }
            ],
            "project_count": 1,
            "layer_count": 3,
            "model_count": 2
        }
        ```

    HTTP Status Codes:
        200: Dashboard data retrieved successfully
        500: Internal server error during data retrieval
    """
    logger.info("GetDashboardData by loading project summary stats")
    try:
        stats = await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().PROJECT.value
            ).load,
            "stats",
        )
        stats["projects"].sort(key=lambda x: x["creationDate"], reverse=True)
        return func.HttpResponse(json.dumps(stats), status_code=200)

    except FileNotFoundError as e:
        logger.warning(
            f"Project stats not found: {e}\n{traceback.format_exc()}"
        )
        return await GenerateProjectStats(req)
    except Exception as e:
        logger.error(
            f"Error loading project stats: {e}\n{traceback.format_exc()}"
        )
        return func.HttpResponse(
            "Error loading project stats.", status_code=500
        )


@app.route(route="GetProjects", auth_level=AUTH_LEVEL, methods=["GET"])
async def GetProjects(req: func.HttpRequest) -> func.HttpResponse:
    """
    Retrieve all projects with their associated statistics and metadata.

    This endpoint returns a comprehensive list of all projects in the HASTE system
    along with aggregated statistics including layer counts, model counts, and
    processing status information.

    Args:
        req (func.HttpRequest): The HTTP request object for retrieving project data.

    Returns:
        func.HttpResponse: JSON response containing project statistics with the following structure:
            - projects: Array of project objects with full metadata
            - project_count: Total number of projects
            - layer_count: Total number of image layers across all projects
            - model_count: Total number of models across all projects

    Raises:
        FileNotFoundError: When project statistics cache is not available
        Exception: For any other processing errors during data retrieval

    Example Response:
        ```json
        {
            "projects": [
                {
                    "projectId": "proj_123",
                    "name": "Hurricane Harvey Assessment",
                    "description": "Building damage assessment post-hurricane",
                    "affectedCountries": ["United States"],
                    "eventDate": "2017-08-25T00:00:00Z",
                    "creationDate": "2023-08-01T12:00:00Z",
                    "imageLayerCount": 2,
                    "imageLayer": [...],
                    "primaryClasses": [...]
                }
            ],
            "project_count": 1,
            "layer_count": 2,
            "model_count": 3
        }
        ```

    HTTP Status Codes:
        200: Projects retrieved successfully
        404: Project statistics not found
        500: Internal server error during data retrieval
    """
    logger.info("Load All projects HTTP trigger function processed a request.")
    try:
        stats = await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().PROJECT.value
            ).load,
            "stats",
        )

        return func.HttpResponse(json.dumps(stats), status_code=200)

    except FileNotFoundError as e:
        logger.error(f"Project stats not found: {e}\n{traceback.format_exc()}")
        return func.HttpResponse("Project stats not found.", status_code=404)
    except Exception as e:
        logger.error(
            f"Error loading project stats: {e}\n{traceback.format_exc()}"
        )
        return func.HttpResponse(
            "Error loading project stats.", status_code=500
        )


@app.route(
    route="GetProjectDetails",
    auth_level=AUTH_LEVEL,
    methods=["GET"],
)
async def GetProjectDetails(req: func.HttpRequest) -> func.HttpResponse:
    """
    Retrieve comprehensive details for a specific HASTE project.

    This endpoint returns detailed information about a project including metadata,
    image layers, associated models, processing status, and configuration. It supports
    optional inclusion of model details to reduce response size when not needed.

    The response includes:
    - Project metadata (name, description, creation date, location)
    - Image layer information with processing status
    - Model configurations and training status (if requested)
    - Primary class definitions and labeling schema
    - Processing statistics and progress indicators

    Args:
        req (func.HttpRequest): HTTP request with query parameters:
            - projectId (str, required): Unique identifier for the project
            - includeModels (bool, optional): Whether to include model details
              in response. Defaults to False for performance.

    Returns:
        func.HttpResponse: JSON response containing:
            - project (dict): Complete project information including:
                - projectId (str): Unique project identifier
                - name (str): Human-readable project name
                - description (str): Project description
                - location (dict): Geographic location information
                - affectedCountries (list): Countries affected by the event
                - eventDate (str): ISO timestamp of the event
                - creationDate (str): ISO timestamp of project creation
                - imageLayerCount (int): Number of associated image layers
                - imageLayer (list): Detailed image layer information
                - primaryClasses (list): Classification schema definitions
                - models (list, optional): Model details if includeModels=true
                - processingStatus (dict): Current processing state

    Raises:
        ProjectNotFoundError: If the specified project does not exist
        ValidationError: If projectId parameter is missing or invalid
        MetadataAccessError: If project metadata cannot be retrieved

    Example:
        GET /api/GetProjectDetails?projectId=proj_12345&includeModels=true

        Response:
        {
            "projectId": "proj_12345",
            "name": "Hurricane Harvey Analysis",
            "description": "Post-hurricane damage assessment",
            "location": {"lat": 29.7604, "lon": -95.3698},
            "affectedCountries": ["United States"],
            "eventDate": "2017-08-25T00:00:00Z",
            "imageLayerCount": 3,
            "models": [...]
        }
    """
    logger.info("GetProjectDetails HTTP trigger function processed a request.")
    try:
        try:
            project_id = _require_guid_param(req, "projectId")
        except ValueError as ve:
            return _bad_request(f"GetProjectDetails: {ve}")
        include_models = (
            req.params.get("includeModels", "false").lower() == "true"
        )

        logger.info(
            f"GetProjectDetails HTTP trigger function processed a request for project id: {project_id} with includeModels: {include_models}"
        )

        project = await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().PROJECT.value,
                partition_key=project_id,
            ).load,
            project_id,
        )
        image_layers = await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().IMAGELAYER.value,
                partition_key=project_id,
            ).load_all_from_partition
        )
        if include_models:
            models = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().MODEL.value,
                    partition_key=project_id,
                ).load_all_from_partition
            )
        for image_layer in image_layers:
            image_layer_id = image_layer["imageLayerId"]
            if include_models:
                match_models = [
                    model
                    for model in models
                    if model["imageLayerId"] == image_layer_id
                ]
                match_models.sort(
                    key=lambda x: x["creationDate"], reverse=True
                )
                for model in match_models:
                    try:
                        artifacts = await asyncio.to_thread(
                            MetadataProcessor(
                                data_type=config.get_metadata_types().MODEL_ARTIFACTS.value,
                                partition_key=project_id,
                            ).load,
                            model["modelId"],
                        )
                        model["artifacts"] = artifacts
                    except FileNotFoundError:
                        model["artifacts"] = None
                    try:
                        if not model.get("labelsUrl"):
                            # Older models may not have labelsUrl
                            model["labelsUrl"] = await asyncio.to_thread(
                                MetadataProcessor(
                                    data_type=config.get_metadata_types().TRAIN_LABELS.value,
                                    partition_key=project_id,
                                ).export,
                                key=model["modelId"],
                                data_format="geojson",
                            )
                    except FileNotFoundError:
                        # This is a noop until the export method is properly
                        # implemented
                        model["labelsUrl"] = None
                image_layer["models"] = match_models
                image_layer["modelCount"] = len(match_models)
            label_projects = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().LABELS.value,
                    partition_key=project_id,
                ).load_all_from_partition
            )
            match_label_projects = next(
                (
                    label_project
                    for label_project in label_projects
                    if label_project["imageLayerId"] == image_layer_id
                ),
                None,
            )
            if match_label_projects is not None:
                if (
                    "labels" in match_label_projects
                    and match_label_projects["labels"] is not None
                ):
                    image_layer["labelProjectCount"] = len(
                        match_label_projects["labels"]
                    )
                else:
                    image_layer["labelProjectCount"] = 0
                if not image_layer.get("labelsUrl"):
                    # Older image layers will not have the generated geoJSON
                    image_layer["labelsUrl"] = None
            try:
                validation_data = await asyncio.to_thread(
                    MetadataProcessor(
                        data_type=config.get_metadata_types().VALIDATION.value,
                        partition_key=project_id,
                    ).load,
                    image_layer_id,
                )
                labels = validation_data.get("labels") or {}
                image_layer["validationLabelCount"] = len(labels)
            except FileNotFoundError:
                image_layer["validationLabelCount"] = 0
        project["imageLayer"] = image_layers
        project["imageLayerCount"] = len(image_layers)
        project["imageLayer"].sort(
            key=lambda x: x["creationDate"], reverse=True
        )
        return func.HttpResponse(json.dumps(project), status_code=200)

    except FileNotFoundError as e:
        logger.error(f"Project not found: {e}\n{traceback.format_exc()}")
        return func.HttpResponse("Project not found.", status_code=404)
    except Exception as e:
        logger.error(
            f"Error loading project details: {e}\n{traceback.format_exc()}"
        )
        return func.HttpResponse(
            "Error loading project details.", status_code=500
        )


@app.route(route="PutProject", auth_level=AUTH_LEVEL, methods=["PUT"])
async def PutProject(req: func.HttpRequest) -> func.HttpResponse:
    """
    Create a new project or update an existing project configuration.

    This endpoint handles both project creation and updates using a unified PUT operation.
    When creating a new project, a unique project ID and creation timestamp are automatically
    generated if not provided. For updates, the existing project is modified with the
    provided data while preserving unspecified fields.

    Project validation ensures:
    - Required fields are present and properly formatted
    - Geographic coordinates are valid
    - Classification schema is properly structured
    - Event dates are valid ISO timestamps

    Args:
        req (func.HttpRequest): HTTP request with JSON body containing:
            - projectId (str, optional): Unique project identifier. Auto-generated if not provided.
            - name (str, required): Human-readable project name
            - description (str, optional): Detailed project description
            - location (dict, required): Geographic location with lat/lon coordinates
            - affectedCountries (list, optional): List of affected country names
            - eventDate (str, optional): ISO timestamp of the event being analyzed
            - creationDate (str, optional): ISO timestamp. Auto-generated if not provided.
            - primaryClasses (list, optional): Classification schema definitions
            - processingConfig (dict, optional): Processing configuration parameters

    Returns:
        func.HttpResponse: JSON response containing:
            - success (bool): Operation success status
            - projectId (str): Project identifier (generated or provided)
            - message (str): Success or error message
            - project (dict): Complete project object as stored

    Raises:
        ValidationError: If required fields are missing or invalid
        SchemaError: If project schema validation fails
        ConflictError: If project ID already exists during creation
        StorageError: If project data cannot be saved

    Example:
        PUT /api/PutProject
        Content-Type: application/json

        {
            "name": "Hurricane Analysis 2024",
            "description": "Post-hurricane damage assessment",
            "location": {"lat": 25.7617, "lon": -80.1918},
            "affectedCountries": ["United States"],
            "eventDate": "2024-09-15T00:00:00Z",
            "primaryClasses": [
                {"name": "damage", "color": "#ff0000"},
                {"name": "no_damage", "color": "#00ff00"}
            ]
        }
    """
    logger.info("PutProject HTTP trigger function processed a request.")

    try:
        req_body = req.get_json()
        output = Project(**req_body)

        if output.projectId is None:
            output.projectId = MetadataUtils.generate_id()
        if output.creationDate is None:
            output.creationDate = MetadataUtils.get_timestamp()

        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().PROJECT.value,
                partition_key=output.projectId,
            ).save,
            output.projectId,
            output.dict(),
        )

        request = StatsPreProcessor(
            request=StatsRequest(
                action="add",
                projectId=output.projectId,
                name=output.name,
                description=output.description,
                creationDate=output.creationDate,
                affectedCountries=output.affectedCountries,
            )
        ).send_to_queue()
        logger.info(
            f"Message sent to update stats for project id {output.projectId} with request {request.dict()}"
        )

        return func.HttpResponse(json.dumps(output.dict()), status_code=200)

    except ValidationError as e:
        logger.error(f"Validation error: {e}\n{traceback.format_exc()}")
        return func.HttpResponse("Validation error.", status_code=400)
    except ValueError as e:
        logger.error(f"Invalid JSON: {e}\n{traceback.format_exc()}")
        return func.HttpResponse(
            "Invalid JSON in request body.", status_code=400
        )
    except Exception as e:
        logger.error(
            f"Error parsing Project data: {e}\n{traceback.format_exc()}"
        )
        return func.HttpResponse(
            "Error parsing Project data.", status_code=500
        )


@app.route(
    route="DeleteProject",
    auth_level=AUTH_LEVEL,
    methods=["DELETE"],
)
async def DeleteProject(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("DeleteProject HTTP trigger function processed a request.")
    try:
        try:
            project_id = _require_guid_param(req, "projectId")
        except ValueError as ve:
            return _bad_request(f"DeleteProject: {ve}")

        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().PROJECT.value,
                partition_key=project_id,
            ).delete_all_from_partition
        )

        request = StatsPreProcessor(
            request=StatsRequest(
                action="delete",
                projectId=project_id,
            )
        ).send_to_queue()
        logger.info(
            f"Message sent to update stats for project id {project_id} with request {request.dict()}"
        )

        return func.HttpResponse(
            f"Project with ID {project_id} deleted successfully.",
            status_code=200,
        )

    except FileNotFoundError as e:
        logger.error(f"Project not found: {e}\n{traceback.format_exc()}")
        return func.HttpResponse("Project not found.", status_code=404)
    except Exception as e:
        logger.error(f"Error deleting project: {e}\n{traceback.format_exc()}")
        return func.HttpResponse("Error deleting project.", status_code=500)


@app.route(route="PutLayer", auth_level=AUTH_LEVEL, methods=["PUT"])
async def PutLayer(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("PutLayer HTTP trigger function processed a request.")

    try:
        req_body = req.get_json()
        image_data = ImageLayer(**req_body)

        url_error = _validate_imagery_urls(image_data)
        if url_error:
            return func.HttpResponse(url_error, status_code=400)

        if image_data.imageLayerId is None:
            image_data.imageLayerId = MetadataUtils.generate_id()
        if image_data.creationDate is None:
            image_data.creationDate = MetadataUtils.get_timestamp()

        try:
            existing_image_layer = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().IMAGELAYER.value,
                    partition_key=image_data.projectId,
                ).load,
                image_data.imageLayerId,
            )
        except FileNotFoundError:
            existing_image_layer = None

        if existing_image_layer:
            # This is an edit
            output = image_data
        else:
            output = await asyncio.to_thread(
                ImageryPreProcessor(image_data=image_data).queue_for_processing
            )

        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().IMAGELAYER.value,
                partition_key=output.projectId,
            ).save,
            output.imageLayerId,
            output.dict(),
        )

        # Repeating the check because we want to save stats after the image layer, if new, is saved

        if not existing_image_layer:
            request = StatsPreProcessor(
                request=StatsRequest(
                    action="add",
                    projectId=output.projectId,
                    imageLayerStats=ImageLayerStats(
                        imageLayerId=output.imageLayerId,
                    ),
                )
            ).send_to_queue()
            logger.info(
                f"Message sent to update stats for project id {output.projectId} with request {request.dict()}"
            )

        return func.HttpResponse(json.dumps(output.dict()), status_code=200)

    except ValidationError as e:
        logger.error(f"Validation error: {e}\n{traceback.format_exc()}")
        return func.HttpResponse("Validation error.", status_code=400)
    except ValueError as e:
        logger.error(f"Invalid JSON: {e}\n{traceback.format_exc()}")
        return func.HttpResponse(
            "Invalid JSON in request body.", status_code=400
        )
    except Exception as e:
        logger.error(
            f"Error parsing ImageLayer: {e}\n{traceback.format_exc()}"
        )
        return func.HttpResponse(
            "Error parsing ImageLayer data.", status_code=500
        )


@app.route(route="DeleteLayer", auth_level=AUTH_LEVEL, methods=["DELETE"])
async def DeleteLayer(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("DeleteLayer HTTP trigger function processed a request.")
    try:
        try:
            project_id = _require_guid_param(req, "projectId")
            image_layer_id = _require_guid_param(req, "imageLayerId")
        except ValueError as ve:
            return _bad_request(f"DeleteLayer: {ve}")
        try:
            await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().IMAGELAYER.value,
                    partition_key=project_id,
                ).delete,
                image_layer_id,
            )
        except Exception as e:
            if "BlobNotFound" in str(e):
                pass  # image layer does not exist
            else:
                raise e

        # Also find models to delete
        models = await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().MODEL.value,
                partition_key=project_id,
            ).load_all_from_partition
        )
        delete_list = []
        for model in models:
            if model["imageLayerId"] == image_layer_id:
                try:
                    await asyncio.to_thread(
                        MetadataProcessor(
                            data_type=config.get_metadata_types().MODEL.value,
                            partition_key=project_id,
                        ).delete,
                        model["modelId"],
                    )
                    # Delete all other model artifacts if they exist
                    await asyncio.to_thread(
                        MetadataProcessor(
                            data_type=config.get_metadata_types().EXPERIMENT_CONFIG.value,
                            partition_key=project_id,
                        ).delete,
                        model["modelId"],
                        "yaml",
                    )

                    await asyncio.to_thread(
                        MetadataProcessor(
                            data_type=config.get_metadata_types().TRAIN_LABELS.value,
                            partition_key=project_id,
                            data_format="geojson",
                        ).delete,
                        model["modelId"],
                    )
                except Exception as e:
                    if "BlobNotFound" in str(e):
                        pass  # no other model artifacts exist
                    else:
                        raise e
                delete_list.append(model["modelId"])

        request = StatsPreProcessor(
            request=StatsRequest(
                action="delete",
                projectId=project_id,
                imageLayerStats=ImageLayerStats(
                    imageLayerId=image_layer_id,
                ),
                modelIds=delete_list,
            )
        ).send_to_queue()
        logger.info(
            f"Message sent to update stats for project id {project_id} with request {request.dict()}"
        )

        return func.HttpResponse(
            f"ImageLayer with ID {image_layer_id} deleted successfully.",
            status_code=200,
        )

    except FileNotFoundError as e:
        logger.error(f"ImageLayer not found: {e}\n{traceback.format_exc()}")
        return func.HttpResponse("ImageLayer not found.", status_code=404)
    except Exception as e:
        logger.error(
            f"Error deleting image layer: {e}\n{traceback.format_exc()}"
        )
        return func.HttpResponse(
            "Error deleting image layer.", status_code=500
        )


@app.route(
    route="GetLayerDetailView",
    auth_level=AUTH_LEVEL,
    methods=["GET"],
)
async def GetLayerDetailView(req: func.HttpRequest) -> func.HttpResponse:
    logger.info(
        "GetLayerDetailView HTTP trigger function processed a request."
    )
    try:
        project_id = req.params.get("projectId")
        image_layer_id = req.params.get("imageLayerId")
        image_layer = await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().IMAGELAYER.value,
                partition_key=project_id,
            ).load,
            image_layer_id,
        )
        models = await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().MODEL.value,
                partition_key=project_id,
            ).load_all_from_partition
        )
        match_models = [
            model
            for model in models
            if model["imageLayerId"] == image_layer_id
        ]
        image_layer["models"] = match_models
        image_layer["modelCount"] = len(match_models)
        return func.HttpResponse(json.dumps(image_layer), status_code=200)
    except FileNotFoundError as e:
        logger.error(f"ImageLayer not found: {e}\n{traceback.format_exc()}")
        return func.HttpResponse("ImageLayer not found.", status_code=404)
    except Exception as e:
        logger.error(
            f"Error loading image layer details: {e}\n{traceback.format_exc()}"
        )
        return func.HttpResponse(
            "Error loading image layer details.", status_code=500
        )


@app.route(route="DeleteModel", auth_level=AUTH_LEVEL, methods=["DELETE"])
async def DeleteModel(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("DeleteModel HTTP trigger function processed a request.")
    try:
        project_id = req.params.get("projectId")
        model_id = req.params.get("modelId")

        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().MODEL.value,
                partition_key=project_id,
            ).delete,
            model_id,
        )

        # Delete all other model artifacts
        try:
            await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().EXPERIMENT_CONFIG.value,
                    partition_key=project_id,
                ).delete,
                model_id,
                "yaml",
            )

            await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().TRAIN_LABELS.value,
                    partition_key=project_id,
                ).delete,
                model_id,
                "geojson",
            )

            await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().MODEL_ARTIFACTS.value,
                    partition_key=project_id,
                ).delete,
                model_id,
            )

            # NOTE: Also delete training, inference and zip output dirs

        except Exception as e:
            if "BlobNotFound" in str(e):
                pass  # no other model artifacts exist
            else:
                raise e

        request = StatsPreProcessor(
            request=StatsRequest(
                action="delete",
                projectId=project_id,
                modelIds=[model_id],
            )
        ).send_to_queue()
        logger.info(
            f"Message sent to update stats for project id {project_id} with request {request.dict()}"
        )

        return func.HttpResponse(
            f"Model with ID {model_id} deleted successfully.", status_code=200
        )

    except FileNotFoundError as e:
        logger.error(f"Model not found: {e}\n{traceback.format_exc()}")
        return func.HttpResponse("Model not found.", status_code=404)
    except Exception as e:
        logger.error(f"Error deleting model: {e}\n{traceback.format_exc()}")
        return func.HttpResponse("Error deleting model.", status_code=500)


@app.route(
    route="GetLayerModelsDetails",
    auth_level=AUTH_LEVEL,
    methods=["GET"],
)
async def GetLayerModelsDetails(req: func.HttpRequest) -> func.HttpResponse:
    logger.info(
        "Get models for a given projectId and imageLayerId HTTP trigger function processed a request."
    )
    try:
        project_id = req.params.get("projectId")
        image_layer_id = req.params.get("imageLayerId")

        models = await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().MODEL.value,
                partition_key=project_id,
            ).load_all_from_partition
        )
        match_models = [
            model
            for model in models
            if model["imageLayerId"] == image_layer_id
        ]

        return func.HttpResponse(json.dumps(match_models), status_code=200)

    except FileNotFoundError as e:
        logger.error(f"Models not found: {e}\n{traceback.format_exc()}")
        return func.HttpResponse("Models not found.", status_code=404)
    except Exception as e:
        logger.error(
            f"Error loading models: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        return func.HttpResponse("Error loading models.", status_code=500)


@app.route(
    route="PutLabelsFromLabelTool",
    auth_level=AUTH_LEVEL,
    methods=["PUT"],
)
async def PutLabelsFromLabelTool(req: func.HttpRequest) -> func.HttpResponse:
    logger.info(
        "PutLabelsFromLabelTool HTTP trigger function processed a request."
    )
    try:
        req_body = req.get_json()
        output = LabelProject(**req_body)
        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().LABELS.value,
                partition_key=output.projectId,
            ).save,
            output.labelprojectId,
            output.dict(),
        )

        labels_geojson = convert_json_to_geojson(
            output.model_dump(by_alias=True)
        )

        await asyncio.to_thread(
            ArtifactProcessor(
                partition_key=output.projectId,
            ).store_artifact,
            artifact_name=f"{config.get_metadata_types().LABELS.value}_{output.labelprojectId}.geojson",
            data=labels_geojson,
            # Note: short term solution is to store them in a separate folder,
            # long term - separate artifacts into their own container
            namespace="artifacts",
        )

        request = StatsPreProcessor(
            request=StatsRequest(
                action="add",
                projectId=output.projectId,
                imageLayerStats=ImageLayerStats(
                    imageLayerId=output.imageLayerId,
                    labelsCount=len(output.labels),
                ),
            )
        ).send_to_queue()
        logger.info(
            f"Message sent to update stats for project id {output.projectId} with request {request.dict()}"
        )

        return func.HttpResponse(json.dumps(output.dict()), status_code=200)

    except ValidationError as e:
        logger.error(f"Validation error: {e}\n{traceback.format_exc()}")
        return func.HttpResponse("Validation error.", status_code=400)
    except ValueError as e:
        logger.error(f"Invalid JSON: {e}\n{traceback.format_exc()}")
        return func.HttpResponse(
            "Invalid JSON in request body.", status_code=400
        )
    except Exception as e:
        logger.error(
            f"Error parsing LabelProject data: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        return func.HttpResponse(
            "Error parsing LabelProject data.", status_code=500
        )


@app.route(
    route="GetLayerLabelingToolData",
    auth_level=AUTH_LEVEL,
    methods=["GET"],
)
async def GetLayerLabelingToolData(req: func.HttpRequest) -> func.HttpResponse:
    logger.info(
        "Get LabelProject for a given projectId and imageLayerId HTTP trigger function processed a request."
    )
    try:
        project_id = req.params.get("projectId")
        image_layer_id = req.params.get("imageLayerId")

        label_projects = await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().LABELS.value,
                partition_key=project_id,
            ).load_all_from_partition
        )
        match_label_projects = next(
            (
                label_project
                for label_project in label_projects
                if label_project["imageLayerId"] == image_layer_id
            ),
            None,
        )

        if match_label_projects is None:
            return func.HttpResponse(
                "Label project not found.", status_code=404
            )

        return func.HttpResponse(
            json.dumps(match_label_projects), status_code=200
        )
    except FileNotFoundError as e:
        logger.error(
            f"Label projects not found: {e}\n{traceback.format_exc()}"
        )
        return func.HttpResponse("Label projects not found.", status_code=404)
    except Exception as e:
        logger.error(
            f"Error loading label projects: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        return func.HttpResponse(
            "Error loading label projects.", status_code=500
        )


@app.route(
    route="GetAdminSettings",
    auth_level=AUTH_LEVEL,
    methods=["GET"],
)
async def GetAdminSettings(req: func.HttpRequest) -> func.HttpResponse:
    logger.info(
        "GetAdminSettings HTTP trigger function processed a request. To get Config data from MetadataProcessor."
    )
    auth_error = _require_roles(req, {"administrators"})
    if auth_error:
        return auth_error
    try:
        config_data = await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().CONFIG.value
            ).load,
            "admin_settings",
        )
        return func.HttpResponse(json.dumps(config_data), status_code=200)
    except FileNotFoundError as e:
        logger.error(
            f"Admin settings data not found: {e}\n{traceback.format_exc()}"
        )
        return func.HttpResponse("Config data not found.", status_code=404)
    except Exception as e:
        logger.error(
            f"Error loading config data: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        return func.HttpResponse("Error loading config data.", status_code=500)


@app.route(
    route="PutAdminSettings",
    auth_level=AUTH_LEVEL,
    methods=["PUT"],
)
async def PutAdminSettings(req: func.HttpRequest) -> func.HttpResponse:
    logger.info(
        "PutAdminSettings HTTP trigger function processed a request. To save Config data to MetadataProcessor."
    )
    auth_error = _require_roles(req, {"administrators"})
    if auth_error:
        return auth_error
    try:
        req_body = req.get_json()
        output = AdminConfig(**req_body)
        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().CONFIG.value
            ).save,
            "admin_settings",
            output.dict(),
        )
        return func.HttpResponse(json.dumps(output.dict()), status_code=200)

    except ValidationError as e:
        logger.error(f"Validation error: {e}\n{traceback.format_exc()}")
        return func.HttpResponse("Validation error.", status_code=400)

    except ValueError as e:
        logger.error(f"Invalid JSON: {e}\n{traceback.format_exc()}")
        return func.HttpResponse(
            "Invalid JSON in request body.", status_code=400
        )
    except Exception as e:
        logger.error(
            f"Error parsing Config data: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        return func.HttpResponse("Error parsing Config data.", status_code=500)


@app.route(route="GetUsers", auth_level=AUTH_LEVEL, methods=["GET"])
async def GetUsers(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("GetUsers HTTP trigger function processed a request.")
    auth_error = _require_roles(req, {"administrators"})
    if auth_error:
        return auth_error
    # Define state transition rules
    state_transitions = {
        # (current_status, app_user_exists, roles_match): (new_status, deleted, comment)
        (config.get_user_statuses().ACTIVE.value, False, None): (
            config.get_user_statuses().INACTIVE.value,
            True,
            f"User deleted outside this system, returning state as {config.get_user_statuses().INACTIVE.value}",
        ),
        (config.get_user_statuses().PENDING.value, False, None): (
            None,
            None,
            "User invitation pending",
        ),
        (config.get_user_statuses().PENDING.value, True, False): (
            config.get_user_statuses().INACTIVE.value,
            True,
            f"Role mismatch after invitation, returning state as {config.get_user_statuses().INACTIVE.value}",
        ),
        (config.get_user_statuses().PENDING.value, True, True): (
            config.get_user_statuses().ACTIVE.value,
            False,
            f"User accepted invitation, returning state as {config.get_user_statuses().ACTIVE.value}",
        ),
        (config.get_user_statuses().INACTIVE.value, False, None): (
            None,
            None,
            "User remains inactive",
        ),
        (config.get_user_statuses().ACTIVE.value, True, False): (
            config.get_user_statuses().INACTIVE.value,
            True,
            f"Role mismatch detected, returning state as {config.get_user_statuses().INACTIVE.value}",
        ),
        (config.get_user_statuses().ACTIVE.value, True, True): (
            config.get_user_statuses().ACTIVE.value,
            None,
            "User active and valid",
        ),
        (None, True, True): (
            config.get_user_statuses().ACTIVE.value,
            None,
            "User active and valid",
        ),
    }
    try:
        users = await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().USERS.value
            ).load,
            "acl",
        )
        users = [
            User(**user).dict() for user in users
        ]  # To ensure defaults are applied to legacy entries
        app_users = await asyncio.to_thread(UserManager().list_users)
        app_users_dict = {
            user.display_name: {"provider": user.provider, "roles": user.roles}
            for user in app_users
        }
        for user in users:
            # user = User(**user).dict()
            app_user = app_users_dict.get(user["userId"])
            # Determine transition parameters
            app_user_exists = app_user is not None
            roles_match = (
                sorted(filter_roles(user["userRoles"]))
                == sorted(filter_roles(app_user["roles"].split(",")))
                if app_user_exists
                else None
            )

            # Apply state transition
            transition_key = (user.get("status"), app_user_exists, roles_match)
            if transition_key in state_transitions:
                new_status, deleted_flag, comment = state_transitions[
                    transition_key
                ]

                if new_status is not None:
                    user["status"] = new_status
                    user["updated_on"] = MetadataUtils.get_timestamp()
                if deleted_flag is not None:
                    user["deleted"] = deleted_flag
                    user["updated_on"] = MetadataUtils.get_timestamp()

                logger.info(f"User {user['userId']}: {comment}")
        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().USERS.value
            ).save,
            "acl",
            users,
        )
        return func.HttpResponse(json.dumps(users), status_code=200)

    except FileNotFoundError as e:
        logger.error(f"Users not found: {e}\n{traceback.format_exc()}")
        return func.HttpResponse("Users not found.", status_code=404)
    except Exception as e:
        logger.error(
            f"Error loading users: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        return func.HttpResponse("Error loading users.", status_code=500)


@app.route(route="PutUser", auth_level=AUTH_LEVEL, methods=["PUT"])
async def PutUser(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("PutUser HTTP trigger function processed a request.")
    try:
        req_body = req.get_json()
        input = User(**req_body.get("user", {}))
        action = req_body.get("action")

        # Authorization: admins can perform any action. Ordinary users may
        # only update their own profile/settings (action == "update", same
        # identity, no role change). Role-change attempts by non-admins
        # are rejected below in the update branch via `roles_changed`.
        is_admin = DEVELOPMENT_MODE
        if not DEVELOPMENT_MODE:
            principal = _decode_client_principal(req)
            caller_email = (
                (principal or {}).get("userDetails")
                or (principal or {}).get("userId")
                or ""
            ).lower()
            if not caller_email:
                return func.HttpResponse(
                    "Forbidden. Missing caller identity.", status_code=403
                )
            raw_roles = (principal or {}).get("userRoles")
            caller_roles = (
                {r.lower().strip() for r in raw_roles if isinstance(r, str)}
                if isinstance(raw_roles, list)
                else set()
            )
            is_admin = "administrators" in caller_roles
            target_email = (input.email or input.userId or "").lower()
            is_self = bool(target_email) and caller_email == target_email
            if not is_admin and not (action == "update" and is_self):
                return func.HttpResponse(
                    "Forbidden. Administrator role required.",
                    status_code=403,
                )
        if input.userId is None:
            input.userId = MetadataUtils.generate_id()
        try:
            users_data = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().USERS.value
                ).load,
                "acl",
            )
        except FileNotFoundError:
            users_data = []
        users = [User(**user) for user in users_data]

        # Helper function for sending invitations
        async def send_invitation(
            email: str, roles: list[str], delete_existing: bool = False
        ) -> None:
            invites = await asyncio.to_thread(
                InvitationManager(
                    email, roles, delete_existing=delete_existing
                ).send_invitations
            )
            if invites.results[0].error:
                raise RuntimeError(invites.results[0].error)

        # Helper function to check if roles have changed (ignoring system roles)
        def roles_changed(
            new_roles: list[str], current_roles: list[str]
        ) -> bool:
            return sorted(filter_roles(new_roles)) != sorted(
                filter_roles(current_roles)
            )

        # Find existing user
        user_index = next(
            (i for i, user in enumerate(users) if user.userId == input.userId),
            None,
        )
        user_exists = user_index is not None

        if not user_exists:
            # Create new user
            await send_invitation(input.email, input.userRoles)
            new_user = User(
                userId=input.email,
                name=input.name,
                email=input.email,
                userRoles=input.userRoles,
                status=config.get_user_statuses().PENDING.value,
                added_by=input.added_by,
                added_on=MetadataUtils.get_timestamp(),
            )
            users.append(new_user)
            user_response = new_user.dict()
        else:
            # Handle existing user
            existing_user = users[user_index]
            logger.info(f"User exists: {existing_user.userId}")

            # Validate add action for active users
            if action == "add" and not existing_user.deleted:
                raise RuntimeError(
                    f"User with ID {input.userId} already exists."
                )

            # Handle reactivation of deleted user
            if action == "add" and existing_user.deleted:
                logger.info(
                    f"Reactivating user: {input.email}, re-sending invitation."
                )
                await send_invitation(
                    input.email, input.userRoles, delete_existing=True
                )

                # Update user for reactivation
                existing_user.status = config.get_user_statuses().PENDING.value
                existing_user.deleted = False
                existing_user.updated_on = MetadataUtils.get_timestamp()
                existing_user.added_by = input.added_by
                existing_user.name = input.name
                existing_user.userRoles = input.userRoles
                existing_user.settings = input.settings
                existing_user.identityProvider = input.identityProvider

            # Handle regular update
            elif action == "update":
                existing_user.name = input.name
                existing_user.settings = input.settings
                existing_user.identityProvider = input.identityProvider
                # Check if roles changed and send new invitation if needed
                if roles_changed(input.userRoles, existing_user.userRoles):
                    if not is_admin:
                        return func.HttpResponse(
                            "Forbidden. Administrator role required.",
                            status_code=403,
                        )
                    logger.info(
                        f"Roles changed for user: {input.email}, re-sending invitation."
                    )
                    await send_invitation(
                        input.email, input.userRoles, delete_existing=True
                    )
                    existing_user.status = (
                        config.get_user_statuses().PENDING.value
                    )
                    existing_user.userRoles = input.userRoles
                    existing_user.updated_on = MetadataUtils.get_timestamp()
                else:
                    existing_user.status = (
                        config.get_user_statuses().ACTIVE.value
                    )
                    existing_user.updated_on = MetadataUtils.get_timestamp()

            # Handle reinvitation
            elif action == "reinvite":
                logger.info(f"Re-sending invitation to: {input.email}")
                await send_invitation(
                    input.email, input.userRoles, delete_existing=True
                )
                existing_user.status = config.get_user_statuses().PENDING.value
                existing_user.updated_on = MetadataUtils.get_timestamp()
                existing_user.added_by = input.added_by

            user_response = existing_user.dict()
        output = [user.dict() for user in users]
        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().USERS.value
            ).save,
            "acl",
            output,
        )
        return func.HttpResponse(json.dumps(user_response), status_code=200)

    except ValidationError as e:
        logger.error(f"Validation error: {e}\n{traceback.format_exc()}")
        return func.HttpResponse("Validation error.", status_code=400)

    except ValueError as e:
        logger.error(f"Invalid JSON: {e}\n{traceback.format_exc()}")
        return func.HttpResponse(
            "Invalid JSON in request body.", status_code=400
        )
    except RuntimeError as e:
        logger.error(f"Error putting user: {e}\n{traceback.format_exc()}")
        return func.HttpResponse("Error putting user.", status_code=400)
    except Exception as e:
        logger.error(
            f"Error parsing Users data: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        return func.HttpResponse("Error parsing Users data.", status_code=500)


@app.route(route="DeleteUser", auth_level=AUTH_LEVEL, methods=["DELETE"])
async def DeleteUser(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("DeleteUser HTTP trigger function processed a request.")
    auth_error = _require_roles(req, {"administrators"})
    if auth_error:
        return auth_error
    try:
        try:
            user_id = _require_email_param(req, "userId")
        except ValueError as ve:
            return _bad_request(f"DeleteUser: {ve}")
        users = await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().USERS.value
            ).load,
            "acl",
        )
        await asyncio.to_thread(UserManager().delete_user_by_email, user_id)
        users = [User(**user) for user in users]
        for idx, user in enumerate(users):
            if user.userId == user_id:
                logger.info(
                    f"Marking user as deleted: {user.userId}, {user.email}"
                )
                users[idx].deleted = True
                users[idx].status = config.get_user_statuses().INACTIVE.value
                users[idx].updated_on = MetadataUtils.get_timestamp()
                break

        output = [user.dict() for user in users]
        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().USERS.value
            ).save,
            "acl",
            output,
        )
        return func.HttpResponse(
            f"User with ID {user_id} marked as deleted.", status_code=200
        )

    except FileNotFoundError as e:
        logger.error(f"User not found: {e}\n{traceback.format_exc()}")
        return func.HttpResponse("User not found.", status_code=404)
    except Exception as e:
        logger.error(
            f"Error deleting user: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        return func.HttpResponse("Error deleting user.", status_code=500)


@app.route(route="GetUserById", auth_level=AUTH_LEVEL, methods=["GET"])
async def GetUserById(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("GetUser HTTP trigger function processed a request.")
    try:
        user_id = req.params.get("userId")
        users = await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().USERS.value
            ).load,
            "acl",
        )
        users = [User(**user) for user in users]
        existing_user = next(
            (user for user in users if user.userId == user_id), None
        )

        # In development mode, auto-create user if not found
        if existing_user is None:
            if DEVELOPMENT_MODE:
                logger.info(f"Development mode: Auto-creating user {user_id}")
                new_user = User(
                    userId=user_id,
                    name=user_id,
                    email=user_id,
                    userRoles=["authenticated", "administrators"],
                    status=config.get_user_statuses().ACTIVE.value,
                    settings={},
                    deleted=False,
                )
                users.append(new_user)
                # Save the new user
                await asyncio.to_thread(
                    MetadataProcessor(
                        data_type=config.get_metadata_types().USERS.value
                    ).save,
                    "acl",
                    [user.dict() for user in users],
                )
                return func.HttpResponse(
                    json.dumps(new_user.dict()), status_code=200
                )
            else:
                raise FileNotFoundError(f"User with ID {user_id} not found.")

        # Skip Azure AD user lookup in development mode
        if DEVELOPMENT_MODE:
            logger.info(
                f"Development mode: Skipping Azure AD lookup for user {user_id}"
            )
            return func.HttpResponse(
                json.dumps(existing_user.dict()), status_code=200
            )

        app_user = await asyncio.to_thread(
            UserManager().find_user_by_email, user_id
        )
        # Define state transition rules
        state_transitions = {
            # (current_status, app_user_exists, roles_match): (new_status, deleted, comment)
            (config.get_user_statuses().ACTIVE.value, False, None): (
                config.get_user_statuses().INACTIVE.value,
                True,
                f"User deleted outside this system, returning state as {config.get_user_statuses().INACTIVE.value}",
            ),
            (config.get_user_statuses().PENDING.value, False, None): (
                None,
                None,
                "User invitation pending",
            ),
            (config.get_user_statuses().PENDING.value, True, False): (
                config.get_user_statuses().INACTIVE.value,
                True,
                f"Role mismatch after invitation, returning state as {config.get_user_statuses().INACTIVE.value}",
            ),
            (config.get_user_statuses().PENDING.value, True, True): (
                config.get_user_statuses().ACTIVE.value,
                False,
                f"User accepted invitation, returning state as {config.get_user_statuses().ACTIVE.value}",
            ),
            (config.get_user_statuses().INACTIVE.value, False, None): (
                None,
                None,
                "User remains inactive",
            ),
            (config.get_user_statuses().ACTIVE.value, True, False): (
                config.get_user_statuses().INACTIVE.value,
                True,
                f"Role mismatch detected, returning state as {config.get_user_statuses().INACTIVE.value}",
            ),
            (config.get_user_statuses().ACTIVE.value, True, True): (
                None,
                None,
                "User active and valid",
            ),
            (None, True, True): (
                config.get_user_statuses().ACTIVE.value,
                None,
                "User active and valid",
            ),
        }

        # Determine transition parameters
        app_user_exists = app_user is not None
        roles_match = (
            sorted(filter_roles(existing_user.userRoles))
            == sorted(filter_roles(app_user.roles.split(",")))
            if app_user_exists
            else None
        )

        # Apply state transition
        transition_key = (existing_user.status, app_user_exists, roles_match)
        if transition_key in state_transitions:
            new_status, deleted_flag, comment = state_transitions[
                transition_key
            ]

            if new_status is not None:
                existing_user.status = new_status
            if deleted_flag is not None:
                existing_user.deleted = deleted_flag

            logger.info(f"User {user_id}: {comment}")

        return func.HttpResponse(
            json.dumps(existing_user.dict()), status_code=200
        )

    except FileNotFoundError as e:
        logger.error(f"User not found: {e}\n{traceback.format_exc()}")
        return func.HttpResponse("User not found.", status_code=404)
    except Exception as e:
        logger.error(
            f"Error loading user: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        return func.HttpResponse("Error loading user.", status_code=500)


@app.route(
    route="GetVisualizerResults",
    auth_level=AUTH_LEVEL,
    methods=["GET"],
)
async def GetVisualizerResults(req: func.HttpRequest) -> func.HttpResponse:
    logger.info(
        "GetVisualizerResults HTTP trigger function processed a request."
    )
    try:
        try:
            project_id = _require_guid_param(req, "projectId")
            image_layer_id = _require_guid_param(req, "imageLayerId")
            # modelId is generated by MetadataUtils.generate_short_int_id()
            # (currently "0000"-"9999"), not a UUID — so the GUID validator
            # rejected every real value. See _require_short_int_id_param.
            model_id = _require_short_int_id_param(req, "modelId")
        except ValueError as ve:
            return _bad_request(f"GetVisualizerResults: {ve}")

        model_data = Model(
            **await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().MODEL.value,
                    partition_key=project_id,
                ).load,
                model_id,
            )
        )
        project = Project(
            **await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().PROJECT.value,
                    partition_key=project_id,
                ).load,
                project_id,
            )
        )
        image_layer = ImageLayer(
            **await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().IMAGELAYER.value,
                    partition_key=project_id,
                ).load,
                image_layer_id,
            )
        )
        label_projects = await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().LABELS.value,
                partition_key=model_data.projectId,
            ).load_all_from_partition
        )
        match_label_projects = [
            label_project
            for label_project in label_projects
            if label_project["imageLayerId"] == image_layer.imageLayerId
        ]
        label_project = LabelProject(
            **match_label_projects[0] if match_label_projects else {}
        )

        titiler_ep = config.titiler_endpoint
        # URL needs to include SAS token for the image to be accessible
        # Also needs to be urlencoded so that SAS is not mangled
        pre_event_image_URL = (
            requests.utils.quote(
                image_layer.preEventProcessedImageryUrl, safe=""
            )
            if image_layer.preEventImageryUrls
            else ""
        )
        post_disaster_image_URL = requests.utils.quote(
            image_layer.postEventProcessedImageryUrl, safe=""
        )
        predicted_damage_layer_URL = (
            requests.utils.quote(model_data.predictedDamageLayerUrl, safe="")
            if model_data.predictedDamageLayerUrl
            else ""
        )
        # The inference workflow always produces a `_predictions.tif` next to
        # `_visualizer.tif`, sharing the same container SAS. Derive its URL by
        # swapping the suffix rather than persisting a separate model field.
        predictions_url_raw = (
            model_data.predictedDamageLayerUrl.replace(
                "_visualizer.tif", "_predictions.tif"
            )
            if model_data.predictedDamageLayerUrl
            else None
        )
        predictions_layer_URL = (
            requests.utils.quote(predictions_url_raw, safe="")
            if predictions_url_raw
            else ""
        )
        # TiTiler colormap overrides the embedded TIFF palette (whose alpha=0 entry
        # is silently dropped by TIFF). Maps pixel values 0/1 -> transparent,
        # 2 -> green, 3 -> red, matching the inference.py palette.
        predictions_colormap = requests.utils.quote(
            json.dumps(
                {
                    "0": [0, 0, 0, 0],
                    "1": [0, 0, 0, 0],
                    "2": [0, 255, 0, 255],
                    "3": [255, 0, 0, 255],
                }
            ),
            safe="",
        )

        visualizer = Visualizer(
            projectId=project_id,
            imageLayerId=image_layer_id,
            modelId=model_id,
            projectName=project.name,
            studyArea=label_project.features,
            eventDate=project.eventDate,
            # NOTE: predictedDamageImageryDownloadUrl will be a screenshot for pre-release, could be something else in the future
            preDisasterImagery=Imagery(
                # If no image is uploaded, then the base Azure Map will be displayed in the pre section
                url=(
                    f"{titiler_ep}cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?scale=1&url={pre_event_image_URL}"
                    if pre_event_image_URL
                    else ""
                ),
                bounds=(
                    label_project.features[0].bbox
                    if label_project.features
                    else None
                ),
            ),
            postDisasterImagery=Imagery(
                url=f"{titiler_ep}cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?scale=1&url={post_disaster_image_URL}",
                bounds=(
                    label_project.features[0].bbox
                    if label_project.features
                    else None
                ),
            ),
            predictedDamageLayer=Imagery(
                url=f"{titiler_ep}cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?scale=1&url={predicted_damage_layer_URL}",
                bounds=(
                    label_project.features[0].bbox
                    if label_project.features
                    else None
                ),
            ),
            predictionsLayer=Imagery(
                url=(
                    f"{titiler_ep}cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?scale=1&url={predictions_layer_URL}&colormap={predictions_colormap}"
                    if predictions_layer_URL
                    else ""
                ),
                bounds=(
                    label_project.features[0].bbox
                    if label_project.features
                    else None
                ),
            ),
            sourceTypePreEvent=image_layer.sourceTypePreEvent,
            sourceTypePostEvent=image_layer.sourceTypePostEvent,
            imageryCaptureDatePreEvent=image_layer.imageryCaptureDatePreEvent,
            imageryCaptureDatePostEvent=image_layer.imageryCaptureDatePostEvent,
        )

        return func.HttpResponse(
            json.dumps(visualizer.dict()), status_code=200
        )
    except Exception as e:
        logger.error(
            f"Error loading visualizer results: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        return func.HttpResponse(
            "Error loading visualizer results.", status_code=500
        )


@app.route(
    route="PutRunModelQueueMessage",
    auth_level=AUTH_LEVEL,
    methods=["PUT"],
)
async def PutRunModelQueueMessage(req: func.HttpRequest) -> func.HttpResponse:
    logger.info(
        "PutRunModelQueueMessage HTTP trigger function processed a request."
    )
    try:
        req_body = req.get_json()
        output = Model(**req_body)

        if output.modelId is None:
            output.modelId = MetadataUtils.generate_short_int_id()
        if output.creationDate is None:
            output.creationDate = MetadataUtils.get_timestamp()
        output.name = output.name.replace(" ", "-")

        label_projects = await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().LABELS.value,
                partition_key=output.projectId,
            ).load_all_from_partition
        )
        match_label_projects = next(
            (
                label_project
                for label_project in label_projects
                if label_project["imageLayerId"] == output.imageLayerId
            ),
            None,
        )

        output.labelprojectId = match_label_projects["labelprojectId"]
        output.labelsCount = len(match_label_projects["labels"])

        output = await asyncio.to_thread(
            TrainPreprocessor(output).send_to_queue
        )

        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().MODEL.value,
                partition_key=output.projectId,
            ).save,
            output.modelId,
            output.dict(),
        )

        request = StatsPreProcessor(
            request=StatsRequest(
                action="add",
                projectId=output.projectId,
                modelIds=[output.modelId],
            )
        ).send_to_queue()
        logger.info(
            f"Message sent to update stats for project id {output.projectId} with request {request.dict()}"
        )

        return func.HttpResponse(json.dumps(output.dict()), status_code=200)

    except ValidationError as e:
        logger.error(f"Validation error: {e}\n{traceback.format_exc()}")
        return func.HttpResponse("Validation error.", status_code=400)
    except ValueError as e:
        logger.error(f"Invalid JSON: {e}\n{traceback.format_exc()}")
        return func.HttpResponse(
            "Invalid JSON in request body.", status_code=400
        )


@app.route(
    route="PutRunInferenceQueueMessage",
    auth_level=AUTH_LEVEL,
    methods=["PUT"],
)
async def PutRunInferenceQueueMessage(
    req: func.HttpRequest,
) -> func.HttpResponse:
    logger.info(
        "PutRunInferenceQueueMessage HTTP trigger function processed a request."
    )
    try:
        req_body = req.get_json()
        output = Model(**req_body)
        if output.creationDate is None:
            output.creationDate = MetadataUtils.get_timestamp()

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

        return func.HttpResponse(json.dumps(output.dict()), status_code=200)

    except ValidationError as e:
        logger.error(f"Validation error: {e}\n{traceback.format_exc()}")
        return func.HttpResponse("Validation error.", status_code=400)
    except ValueError as e:
        logger.error(f"Invalid JSON: {e}\n{traceback.format_exc()}")
        return func.HttpResponse(
            "Invalid JSON in request body.", status_code=400
        )


@app.route(
    route="GenerateProjectStats",
    auth_level=AUTH_LEVEL,
    methods=["GET"],
)
async def GenerateProjectStats(req: func.HttpRequest) -> func.HttpResponse:
    """Helper endpoint to generate project stats from all project data.
    Useful for reconciling if they are out of sync.
    """
    logger.info("GenerateProjectStats by loading all project data")
    try:
        summary = []

        projects = await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().PROJECT.value
            ).load_all
        )
        for project in projects:
            project_id = project["projectId"]
            image_layers = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().IMAGELAYER.value,
                    partition_key=project_id,
                ).load_all_from_partition
            )
            models = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().MODEL.value,
                    partition_key=project_id,
                ).load_all_from_partition
            )
            for image_layer in image_layers:
                image_layer_id = image_layer["imageLayerId"]
                match_models = [
                    model
                    for model in models
                    if model["imageLayerId"] == image_layer_id
                ]
                image_layer["models"] = match_models
                image_layer["modelCount"] = len(match_models)
                label_projects = await asyncio.to_thread(
                    MetadataProcessor(
                        data_type=config.get_metadata_types().LABELS.value,
                        partition_key=project_id,
                    ).load_all_from_partition
                )
                match_label_projects = next(
                    (
                        label_project
                        for label_project in label_projects
                        if label_project["imageLayerId"] == image_layer_id
                    ),
                    None,
                )
                if match_label_projects is not None:
                    if (
                        "labels" in match_label_projects
                        and match_label_projects["labels"] is not None
                    ):
                        image_layer["labelProjectCount"] = len(
                            match_label_projects["labels"]
                        )
                    else:
                        image_layer["labelProjectCount"] = 0
            project["imageLayer"] = image_layers
            project["imageLayerCount"] = len(image_layers)

            projectstats = ProjectStats(
                projectId=project["projectId"],
                name=project["name"],
                description=project["description"],
                creationDate=project["creationDate"],
                affectedCountries=project["affectedCountries"],
                imageLayerStats=[
                    ImageLayerStats(
                        imageLayerId=image_layer["imageLayerId"],
                        labelsCount=image_layer["labelProjectCount"],
                    )
                    for image_layer in image_layers
                ],
                modelIds=set([str(model["modelId"]) for model in models]),
                imageLayerCount=project["imageLayerCount"],
                modelsCount=sum(
                    [image_layer["modelCount"] for image_layer in image_layers]
                ),
                labelsCount=sum(
                    [
                        image_layer["labelProjectCount"]
                        for image_layer in image_layers
                    ]
                ),
            )
            summary.append(projectstats)

        projects = ProjectsSummary(projects=summary)

        if not summary:
            logger.info("No projects found, initializing stats")

        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().PROJECT.value
            ).save,
            "stats",
            projects.dict(),
        )

        return func.HttpResponse(json.dumps(projects.dict()), status_code=200)

    except Exception as e:
        logger.error(
            f"Error generating project stats: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        return func.HttpResponse(
            "Error generating project stats.", status_code=500
        )


@app.route(
    route="PutArtifactsZipQueueMessage",
    auth_level=AUTH_LEVEL,
    methods=["PUT"],
)
async def PutArtifactsZipQueueMessage(
    req: func.HttpRequest,
) -> func.HttpResponse:
    logger.info(
        "PutArtifactsZipQueueMessage HTTP trigger function processed a request."
    )
    try:
        req_body = req.get_json()
        model_artifacts = ModelArtifacts(**req_body)

        output = await asyncio.to_thread(
            ArtifactProcessor(
                partition_key=model_artifacts.projectId,
                model_artifacts=model_artifacts,
            ).send_to_zip_queue
        )

        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().MODEL_ARTIFACTS.value,
                partition_key=output.projectId,
            ).save,
            output.modelId,
            output.dict(),
        )

        return func.HttpResponse(json.dumps(output.dict()), status_code=200)

    except ValidationError as e:
        logger.error(f"Validation error: {e}\n{traceback.format_exc()}")
        return func.HttpResponse("Validation error.", status_code=400)
    except ValueError as e:
        logger.error(f"Invalid JSON: {e}\n{traceback.format_exc()}")
        return func.HttpResponse(
            "Invalid JSON in request body.", status_code=400
        )


@app.route(
    route="PutCancelModelQueueMessage",
    auth_level=AUTH_LEVEL,
    methods=["PUT"],
)
async def PutCancelModelQueueMessage(
    req: func.HttpRequest,
) -> func.HttpResponse:
    logger.info(
        "PutCancelModelQueueMessage HTTP trigger function processed a request."
    )
    try:
        model_cancel_req = req.get_json()

        try:
            existing_model_data = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().MODEL.value,
                    partition_key=model_cancel_req["projectId"],
                ).load,
                model_cancel_req["modelId"],
            )
        except FileNotFoundError:
            existing_model_data = None

        if existing_model_data:
            existing_model_data = Model(**existing_model_data)
        else:
            logger.info(
                f"Model {model_cancel_req.modelId} not found, likely deleted, skipping canceling"
            )
            return func.HttpResponse(json.dumps({}), status_code=200)

        if (
            existing_model_data.status
            == config.get_status_types().COMPLETED.value
            and not (
                existing_model_data.inferenceStatus
                == config.get_status_types().COMPLETED.value
                or existing_model_data.inferenceStatus
                == config.get_status_types().FAILED.value
            )
        ):
            logger.info(
                f"Training for model {model_cancel_req['modelId']} already completed, cancelling inference"
            )
            output = await asyncio.to_thread(
                InferencePreprocessor(existing_model_data).send_to_queue,
                status=config.get_status_types().CANCELLED.value,
            )
        elif (
            existing_model_data.status
            == config.get_status_types().FAILED.value
        ):
            logger.info(
                f"Training for model {model_cancel_req['modelId']} already failed, no action taken"
            )
            output = existing_model_data
            output.statusMessage = MetadataUtils.append_status_message(
                output.statusMessage,
                "Training already failed, Cancel action has no effect",
            )
        elif (
            existing_model_data.inferenceStatus
            == config.get_status_types().COMPLETED.value
        ):
            logger.info(
                f"Inference for model {model_cancel_req['modelId']} already completed, no action taken"
            )
            output = existing_model_data
            output.inferenceStatusMessage = (
                MetadataUtils.append_status_message(
                    output.inferenceStatusMessage,
                    "Inference already completed, Cancel action has no effect",
                )
            )
        elif (
            existing_model_data.inferenceStatus
            == config.get_status_types().FAILED.value
        ):
            logger.info(
                f"Inference for model {model_cancel_req['modelId']} already failed, no action taken"
            )
            output = existing_model_data
            output.inferenceStatusMessage = (
                MetadataUtils.append_status_message(
                    output.inferenceStatusMessage,
                    "Inference already failed, Cancel action has no effect",
                )
            )
        else:
            output = await asyncio.to_thread(
                TrainPreprocessor(existing_model_data).send_to_queue,
                status=config.get_status_types().CANCELLED.value,
            )

        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().MODEL.value,
                partition_key=output.projectId,
            ).save,
            output.modelId,
            output.dict(),
        )

        return func.HttpResponse(json.dumps(output.dict()), status_code=200)

    except ValidationError as e:
        logger.error(f"Validation error: {e}\n{traceback.format_exc()}")
        return func.HttpResponse("Validation error.", status_code=400)
    except ValueError as e:
        logger.error(f"Invalid JSON: {e}\n{traceback.format_exc()}")
        return func.HttpResponse(
            "Invalid JSON in request body.", status_code=400
        )
    except Exception as e:
        logger.error(
            f"Error cancelling model task: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        return func.HttpResponse(
            "Error cancelling model task.", status_code=500
        )


@app.route(
    route="GetModelCatalog",
    auth_level=func.AuthLevel.FUNCTION,
    methods=["GET"],
)
async def GetModelCatalog(req: func.HttpRequest) -> func.HttpResponse:
    """
    Retrieve the model catalog containing all available base models for training.

    This endpoint returns a comprehensive list of all catalogued models that can be used
    as base models for training new models. The catalog includes metadata about each model
    such as disaster type, imagery source, and usage history.

    Args:
        req (func.HttpRequest): HTTP request with optional query parameters:
            - eventTypes (str, optional): Filter by event type(s). Can be a single value or
              comma-separated list (e.g., "Hurricane,Tornado,Fires"). Models with any matching
              event type in their eventTypes array will be returned.
            - imagerySource (str, optional): Filter by imagery source (Planet, Maxar, etc.)

    Returns:
        func.HttpResponse: JSON response containing:
            - modelCatalog (list): Array of catalogued models with metadata:
                - baseModelName (str): Human-readable name of the base model
                - modelId (str): Original model ID this was checkpointed from
                - projectId (str): Project ID where the model was created
                - imageLayerId (str): Image layer ID associated with the model
                - imagerySource (str): Source of imagery (Planet, Maxar, etc.)
                - eventTypes (list[str]): Types of disaster events (Hurricane, Tornado, Fires, etc.)
                - cataloguedDate (str): ISO timestamp when model was added to catalog
                - cataloguedByUser (str): User ID who added the model to catalog
                - additionalInfo (dict): User-defined metadata key-value pairs
                - usedByModels (list): List of model IDs that used this as base model

    Raises:
        FileNotFoundError: If model catalog data is not found
        Exception: For any other processing errors during data retrieval

    Example Response:
        ```json
        {
            "modelCatalog": [
                {
                    "baseModelName": "hurricane-damage-v1",
                    "modelId": "model_12345",
                    "projectId": "proj_67890",
                    "imageLayerId": "layer_11111",
                    "imagerySource": "Planet",
                    "eventTypes": ["Hurricane"],
                    "cataloguedDate": "2024-08-15T10:30:00Z",
                    "cataloguedByUser": "user@example.com",
                    "additionalInfo": {
                        "accuracy": "92%",
                        "notes": "Trained on Hurricane Harvey data"
                    },
                    "usedByModels": ["model_22222", "model_33333"]
                }
            ]
        }
        ```

    HTTP Status Codes:
        200: Model catalog retrieved successfully
        404: Model catalog not found
        500: Internal server error during retrieval
    """
    logger.info("GetModelCatalog HTTP trigger function processed a request.")
    try:
        # Get optional filter parameters
        # eventTypes can be comma-separated for multiple values: ?eventTypes=Hurricane,Tornado
        event_type_param = req.params.get("eventTypes")
        event_types = (
            [et.strip() for et in event_type_param.split(",") if et.strip()]
            if event_type_param
            else []
        )
        imagery_source = req.params.get("imagerySource")

        logger.info(
            f"GetModelCatalog filters - eventTypes: {event_types}, imagerySource: {imagery_source}"
        )

        # Load the model catalog from metadata storage
        try:
            catalog_data = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().MODEL_CATALOG.value
                ).load,
                "index",
            )
        except FileNotFoundError:
            # Initialize empty catalog if none exists
            catalog_data = {"modelCatalog": []}
            logger.info("Model catalog not found, returning empty catalog")

        # Apply filters if provided
        model_catalog = catalog_data.get("modelCatalog", [])

        if event_types:
            # Filter models where any of the requested event types match any of the model's event types
            event_types_lower = [et.lower() for et in event_types]
            model_catalog = [
                model
                for model in model_catalog
                if model.get("eventTypes")
                and any(
                    model_et.lower() in event_types_lower
                    for model_et in model.get("eventTypes", [])
                )
            ]
            logger.info(
                f"Filtered by event types {event_types}: {len(model_catalog)} models"
            )

        if imagery_source and imagery_source.strip():
            model_catalog = [
                model
                for model in model_catalog
                if model.get("imagerySource", "")
                and model.get("imagerySource", "").lower()
                == imagery_source.lower()
            ]
            logger.info(
                f"Filtered by imagery source '{imagery_source}': {len(model_catalog)} models"
            )

        # Sort by catalogued date (newest first)
        model_catalog.sort(
            key=lambda x: x.get("cataloguedDate", ""), reverse=True
        )

        response_data = {"modelCatalog": model_catalog}

        logger.info(f"Returning {len(model_catalog)} models from catalog")
        return func.HttpResponse(json.dumps(response_data), status_code=200)

    except Exception as e:
        logger.error(
            f"Error loading model catalog: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        return func.HttpResponse(
            "Error loading model catalog.", status_code=500
        )


@app.route(
    route="PutModelCatalog",
    auth_level=func.AuthLevel.FUNCTION,
    methods=["PUT"],
)
async def PutModelCatalog(req: func.HttpRequest) -> func.HttpResponse:
    """
    Add a model to the model catalog for reuse as a base model.

    This endpoint allows users to checkpoint successful training results and add them
    to the model catalog with custom metadata. The catalogued models can then be used
    as base models for future training runs. External models can also be added without
    requiring validation of their existence in the HASTE system.

    Args:
        req (func.HttpRequest): HTTP request with JSON body containing:
            - baseModelName (str, required): Human-readable name for the base model
            - modelId (str, optional): ID of the original model (required only for HASTE models)
            - projectId (str, optional): Project ID (required only for HASTE models)
            - imageLayerId (str, optional): Image layer ID (required only for HASTE models)
            - imagerySource (str, optional): Source of imagery (Planet, Maxar, etc.)
            - eventTypes (list[str], optional): Types of disaster events (Hurricane, Tornado, etc.)
            - cataloguedByUser (str, required): User ID who is adding the model to catalog
            - description (str, optional): Description of the model
            - checkpointFilePath (str, optional): Path to model checkpoint file. Auto-populated for HASTE models.
            - source (str, optional): Model source ("haste", "external", etc.). Defaults to "haste".
            - additionalInfo (dict, optional): User-defined metadata key-value pairs

    Returns:
        func.HttpResponse: JSON response containing:
            - success (bool): Operation success status
            - catalogModel (dict): Complete catalog model object as stored
            - message (str): Success or error message

    Raises:
        ValidationError: If required fields are missing or invalid
        ConflictError: If model with same name already exists in catalog
        StorageError: If catalog data cannot be saved

    Example:
        PUT /api/PutModelCatalog
        Content-Type: application/json

        # HASTE model
        {
            "baseModelName": "hurricane-damage-harvey-v1",
            "modelId": "model_12345",
            "projectId": "proj_67890",
            "imageLayerId": "layer_11111",
            "imagerySource": "Planet",
            "eventTypes": ["Hurricane"],
            "cataloguedByUser": "user@example.com",
            "source": "haste",
            "description": "High-accuracy model trained on Hurricane Harvey damage data"
        }

        # External model
        {
            "baseModelName": "resnet50-imagenet-pretrained",
            "cataloguedByUser": "admin@example.com",
            "source": "external",
            "checkpointFilePath": "https://download.pytorch.org/models/resnet50.pth",
            "description": "Pre-trained ResNet50 model from PyTorch"
        }
    """
    logger.info("PutModelCatalog HTTP trigger function processed a request.")
    try:
        req_body = req.get_json()

        # Create and validate the catalog model
        catalog_model = CatalogModel(**req_body)

        # Auto-generate fields if not provided
        if catalog_model.cataloguedDate is None:
            catalog_model.cataloguedDate = MetadataUtils.get_timestamp()

        # Determine if this is a HASTE model or external model
        is_haste_model = getattr(catalog_model, "source", "haste") == "haste"

        # Load existing catalog or create new one
        try:
            catalog_data = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().MODEL_CATALOG.value
                ).load,
                "index",
            )
            existing_catalog = catalog_data.get("modelCatalog", [])
        except FileNotFoundError:
            existing_catalog = []
            logger.info("Model catalog not found, creating new catalog")

        # Check for duplicate base model names
        existing_names = [
            model.get("baseModelName", "").lower()
            for model in existing_catalog
        ]
        if catalog_model.baseModelName.lower() in existing_names:
            logger.warning(
                f"Model catalog entry with name '{catalog_model.baseModelName}' already exists"
            )
            return func.HttpResponse(
                f"Model with name '{catalog_model.baseModelName}' already exists in catalog. Please use a different name.",
                status_code=409,
            )

        # Check for duplicate model IDs (if modelId is provided)
        if catalog_model.modelId:
            existing_model_ids = [
                model.get("modelId")
                for model in existing_catalog
                if model.get("modelId")
            ]
            if catalog_model.modelId in existing_model_ids:
                existing_name_in_catalog = existing_catalog[
                    existing_model_ids.index(catalog_model.modelId)
                ].get("baseModelName")
                logger.warning(
                    f"Model catalog entry with modelId '{catalog_model.modelId}' already exists"
                )
                return func.HttpResponse(
                    f"Model with modelId '{catalog_model.modelId}' already exists in catalog with name '{existing_name_in_catalog}'. "
                    f"To replace the existing catalog entry, please delete it first.",
                    status_code=409,
                )

        # Only validate source model exists if this is a HASTE model
        if is_haste_model:
            # Validate required fields for HASTE models
            if not catalog_model.modelId or not catalog_model.projectId:
                return func.HttpResponse(
                    "modelId and projectId are required for HASTE models (source='haste').",
                    status_code=400,
                )

            # Validate that the source model exists and get its data
            try:
                source_model = await asyncio.to_thread(
                    MetadataProcessor(
                        data_type=config.get_metadata_types().MODEL.value,
                        partition_key=catalog_model.projectId,
                    ).load,
                    catalog_model.modelId,
                )
                logger.info(
                    f"Validated HASTE source model {catalog_model.modelId} exists in project {catalog_model.projectId}"
                )
            except FileNotFoundError:
                logger.error(
                    f"HASTE source model {catalog_model.modelId} not found in project {catalog_model.projectId}"
                )
                return func.HttpResponse(
                    f"HASTE source model {catalog_model.modelId} not found in project {catalog_model.projectId}.",
                    status_code=400,
                )

            # Verify the source model is completed and ready for cataloging
            if (
                source_model.get("status")
                != config.get_status_types().COMPLETED.value
            ):
                logger.warning(
                    f"HASTE source model {catalog_model.modelId} is not completed (status: {source_model.get('status')})"
                )
                return func.HttpResponse(
                    f"HASTE source model {catalog_model.modelId} must be completed before it can be catalogued.",
                    status_code=400,
                )

            # Auto-populate checkpointFilePath if not provided for HASTE models
            if catalog_model.checkpointFilePath is None:
                # Try to get checkpoint path from the source model
                checkpoint_path = source_model.get("checkpointPath")
                if checkpoint_path:
                    # Construct the full path to the checkpoint file
                    catalog_model.checkpointFilePath = (
                        f"{checkpoint_path}/last.ckpt"
                    )
                    logger.info(
                        f"Auto-populated checkpointFilePath for HASTE model: {catalog_model.checkpointFilePath}"
                    )
                else:
                    logger.warning(
                        f"No checkpoint path found for HASTE model {catalog_model.modelId}"
                    )
                    return func.HttpResponse(
                        f"No checkpoint path available for HASTE model {catalog_model.modelId}. Please provide checkpointFilePath.",
                        status_code=400,
                    )
        else:
            # For external models, checkpointFilePath is required
            if not catalog_model.checkpointFilePath:
                return func.HttpResponse(
                    "checkpointFilePath is required for external models.",
                    status_code=400,
                )
            logger.info(
                f"Adding external model '{catalog_model.baseModelName}' with checkpoint: {catalog_model.checkpointFilePath}"
            )

        # Add the new model to the catalog
        catalog_model_dict = catalog_model.dict()
        existing_catalog.append(catalog_model_dict)

        # Sort catalog by catalogued date (newest first)
        existing_catalog.sort(
            key=lambda x: x.get("cataloguedDate", ""), reverse=True
        )

        # Save updated catalog
        updated_catalog_data = {"modelCatalog": existing_catalog}
        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().MODEL_CATALOG.value
            ).save,
            "index",
            updated_catalog_data,
        )

        model_type = "HASTE" if is_haste_model else "external"
        logger.info(
            f"Successfully added {model_type} model '{catalog_model.baseModelName}' to catalog"
        )

        response_data = {
            "success": True,
            "catalogModel": catalog_model_dict,
            "message": f"Model '{catalog_model.baseModelName}' successfully added to catalog",
        }

        return func.HttpResponse(json.dumps(response_data), status_code=200)

    except ValidationError as e:
        logger.error(f"Validation error: {e}\n{traceback.format_exc()}")
        return func.HttpResponse("Validation error.", status_code=400)
    except ValueError as e:
        logger.error(f"Invalid JSON: {e}\n{traceback.format_exc()}")
        return func.HttpResponse(
            "Invalid JSON in request body.", status_code=400
        )
    except Exception as e:
        logger.error(
            f"Error adding model to catalog: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        return func.HttpResponse(
            "Error adding model to catalog.", status_code=500
        )


@app.route(
    route="DeleteModelCatalog",
    auth_level=func.AuthLevel.FUNCTION,
    methods=["DELETE"],
)
async def DeleteModelCatalog(req: func.HttpRequest) -> func.HttpResponse:
    """
    Delete a model from the model catalog.

    This endpoint removes a catalogued model from the model catalog. The model
    can be identified by either its baseModelName or modelId.

    Args:
        req (func.HttpRequest): HTTP request with query parameters:
            - baseModelName (str, optional): Name of the catalogued model to delete
            - modelId (str, optional): ID of the catalogued model to delete
            At least one of baseModelName or modelId must be provided.

    Returns:
        func.HttpResponse: JSON response containing:
            - success (bool): Operation success status
            - message (str): Success or error message
            - deletedModel (dict): The deleted catalog model object

    Raises:
        ValidationError: If neither baseModelName nor modelId is provided
        NotFoundError: If the specified model is not found in the catalog
        StorageError: If catalog data cannot be saved

    Example:
        DELETE /api/DeleteModelCatalog?baseModelName=hurricane-damage-harvey-v1

        Response:
        {
            "success": true,
            "message": "Model 'hurricane-damage-harvey-v1' successfully deleted from catalog",
            "deletedModel": { ... }
        }
    """
    logger.info(
        "DeleteModelCatalog HTTP trigger function processed a request."
    )
    try:
        base_model_name = req.params.get("baseModelName")
        model_id = req.params.get("modelId")

        if not base_model_name and not model_id:
            return func.HttpResponse(
                "Either baseModelName or modelId query parameter is required.",
                status_code=400,
            )

        # Load existing catalog
        try:
            catalog_data = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().MODEL_CATALOG.value
                ).load,
                "index",
            )
            existing_catalog = catalog_data.get("modelCatalog", [])
        except FileNotFoundError:
            logger.info("Model catalog not found")
            return func.HttpResponse(
                "Model catalog is empty or does not exist.", status_code=404
            )

        # Find the model to delete
        model_to_delete = None
        model_index = None

        for i, model in enumerate(existing_catalog):
            if (
                base_model_name
                and model.get("baseModelName", "").lower()
                == base_model_name.lower()
            ):
                model_to_delete = model
                model_index = i
                break
            if model_id and model.get("modelId") == model_id:
                model_to_delete = model
                model_index = i
                break

        if model_to_delete is None:
            identifier = base_model_name or model_id
            logger.warning(f"Model '{identifier}' not found in catalog")
            return func.HttpResponse(
                f"Model '{identifier}' not found in catalog.", status_code=404
            )

        # Remove the model from the catalog
        deleted_model = existing_catalog.pop(model_index)

        # Save updated catalog
        updated_catalog_data = {"modelCatalog": existing_catalog}
        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().MODEL_CATALOG.value
            ).save,
            "index",
            updated_catalog_data,
        )

        logger.info(
            f"Successfully deleted model '{deleted_model.get('baseModelName')}' from catalog"
        )

        response_data = {
            "success": True,
            "message": f"Model '{deleted_model.get('baseModelName')}' successfully deleted from catalog",
            "deletedModel": deleted_model,
        }

        return func.HttpResponse(json.dumps(response_data), status_code=200)

    except Exception as e:
        logger.error(
            f"Error deleting model from catalog: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        return func.HttpResponse(
            "Error deleting model from catalog.", status_code=500
        )


@app.route(
    route="GetAzureMapsToken",
    auth_level=AUTH_LEVEL,
    methods=["GET"],
)
async def GetAzureMapsToken(req: func.HttpRequest) -> func.HttpResponse:
    """Return an Azure AD token for Azure Maps using managed identity."""
    try:
        from azure.identity import DefaultAzureCredential

        credential = DefaultAzureCredential()
        token = credential.get_token("https://atlas.microsoft.com/.default")

        return func.HttpResponse(
            json.dumps({"access_token": token.token}),
            status_code=200,
            mimetype="application/json",
        )
    except Exception as e:
        logger.error(
            f"Error fetching Azure Maps token: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        return func.HttpResponse(
            "Error fetching Azure Maps token.", status_code=500
        )


@app.route(
    route="GetBuildingFootprintsGeoJSON",
    auth_level=AUTH_LEVEL,
    methods=["GET"],
)
async def GetBuildingFootprintsGeoJSON(
    req: func.HttpRequest,
) -> func.HttpResponse:
    """Return a random sample of building footprints as a GeoJSON FeatureCollection.

    Reads the cached .gpkg file from blob storage for the given image layer,
    selects a random sample of up to ``sample`` buildings, and returns them as
    a GeoJSON FeatureCollection.  Each feature carries the Overture building
    ``id``, ``subtype``, and ``class`` properties.

    Query params:
        projectId (str): Parent project identifier.
        imageLayerId (str): Image layer identifier.
        sample (int, optional): Maximum number of buildings to return
            (default 200). Clamped to the inclusive range [1, 2000] to bound
            response size and server-side memory.
    """
    logger.info(
        "GetBuildingFootprintsGeoJSON HTTP trigger function processed a request."
    )
    tmp_path = None
    try:
        import os as _os
        import tempfile

        import geopandas as gpd

        project_id = req.params.get("projectId")
        image_layer_id = req.params.get("imageLayerId")
        try:
            requested_sample = int(req.params.get("sample", 200))
        except (TypeError, ValueError):
            requested_sample = 200
        # Clamp to a sane range so callers can't accidentally pull the
        # entire dataset (which can be millions of features) into memory.
        sample_size = max(1, min(requested_sample, 2000))

        if not project_id or not image_layer_id:
            return func.HttpResponse(
                "projectId and imageLayerId are required.", status_code=400
            )

        # Load the image layer metadata to get the buildingFootprintsUrl.
        image_layer_data = await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().IMAGELAYER.value,
                partition_key=project_id,
            ).load,
            image_layer_id,
        )

        footprints_url = image_layer_data.get("buildingFootprintsUrl")
        if not footprints_url:
            return func.HttpResponse(
                "No building footprints available for this image layer.",
                status_code=404,
            )

        # Resolve container+blob from the externally-shaped URL with a
        # parser that handles both real-Azure (account-in-host) and
        # Azurite (account-in-path), including the docker-internal
        # `http://azurite:10000/...` form. We can't use the Azure SDK's
        # BlobClient.from_blob_url for this — see _split_blob_url docstring.
        from azure.storage.blob import BlobServiceClient

        conn_str = os.environ.get("BLOB_CONNECTION_STRING", "")
        container_name, blob_name = _split_blob_url(footprints_url)

        bsc = BlobServiceClient.from_connection_string(conn_str)
        blob_bytes = await asyncio.to_thread(
            lambda: bsc.get_container_client(container_name)
            .get_blob_client(blob_name)
            .download_blob()
            .readall()
        )

        with tempfile.NamedTemporaryFile(suffix=".gpkg", delete=False) as tmp:
            tmp.write(blob_bytes)
            tmp_path = tmp.name

        gdf = await asyncio.to_thread(gpd.read_file, tmp_path)

        # Random sample
        if len(gdf) > sample_size:
            gdf = gdf.sample(n=sample_size, random_state=42)

        # Ensure only the columns we care about are returned.
        keep_cols = [
            c
            for c in ["id", "subtype", "class", "geometry"]
            if c in gdf.columns
        ]
        gdf = gdf[keep_cols]

        geojson_str = await asyncio.to_thread(lambda: gdf.to_json())

        return func.HttpResponse(
            geojson_str,
            status_code=200,
            mimetype="application/json",
        )

    except FileNotFoundError:
        return func.HttpResponse("Image layer not found.", status_code=404)
    except Exception as e:
        logger.error(
            f"Error in GetBuildingFootprintsGeoJSON: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        return func.HttpResponse(
            "Error fetching building footprints.", status_code=500
        )
    finally:
        # Clean up the temporary .gpkg even when the read/sample/to_json
        # path raises, so we don't leak files into the Functions worker's
        # /tmp on every failed request.
        if tmp_path is not None:
            try:
                _os.unlink(tmp_path)
            except OSError:
                pass


@app.route(
    route="GetBuildingValidation",
    auth_level=AUTH_LEVEL,
    methods=["GET"],
)
async def GetBuildingValidation(req: func.HttpRequest) -> func.HttpResponse:
    """Return existing building validation labels for an image layer.

    Query params:
        projectId (str): Parent project identifier.
        imageLayerId (str): Image layer identifier.

    Returns a BuildingValidation JSON object, or an empty one if no labels exist yet.
    """
    logger.info(
        "GetBuildingValidation HTTP trigger function processed a request."
    )
    try:
        project_id = req.params.get("projectId")
        image_layer_id = req.params.get("imageLayerId")

        if not project_id or not image_layer_id:
            return func.HttpResponse(
                "projectId and imageLayerId are required.", status_code=400
            )

        try:
            validation_data = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().VALIDATION.value,
                    partition_key=project_id,
                ).load,
                image_layer_id,
            )
        except FileNotFoundError:
            validation_data = BuildingValidation(
                imageLayerId=image_layer_id,
                projectId=project_id,
                labels={},
            ).model_dump()

        return func.HttpResponse(
            json.dumps(validation_data),
            status_code=200,
            mimetype="application/json",
        )

    except Exception as e:
        logger.error(
            f"Error in GetBuildingValidation: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        return func.HttpResponse(
            "Error fetching building validation.", status_code=500
        )


@app.route(
    route="PutBuildingValidation",
    auth_level=AUTH_LEVEL,
    methods=["PUT"],
)
async def PutBuildingValidation(req: func.HttpRequest) -> func.HttpResponse:
    """Save (replace) building validation labels for an image layer.

    Request body: BuildingValidation JSON
        {
            "projectId": "...",
            "imageLayerId": "...",
            "labels": {
                "<overture-id>": {"id": "...", "label": "Damaged|NotDamaged|Unknown", "updatedAt": "..."}
            }
        }
    """
    logger.info(
        "PutBuildingValidation HTTP trigger function processed a request."
    )
    try:
        req_body = req.get_json()
        validation = BuildingValidation(**req_body)

        if not validation.projectId or not validation.imageLayerId:
            return func.HttpResponse(
                "projectId and imageLayerId are required.", status_code=400
            )

        await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().VALIDATION.value,
                partition_key=validation.projectId,
            ).save,
            validation.imageLayerId,
            validation.model_dump(),
        )

        return func.HttpResponse(
            json.dumps(validation.model_dump()),
            status_code=200,
            mimetype="application/json",
        )

    except Exception as e:
        logger.error(
            f"Error in PutBuildingValidation: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        return func.HttpResponse(
            "Error saving building validation.", status_code=500
        )


@app.route(
    route="GetValidationReport",
    auth_level=AUTH_LEVEL,
    methods=["GET"],
)
async def GetValidationReport(req: func.HttpRequest) -> func.HttpResponse:
    """Compute a validation accuracy report by crossing inference results with
    user-supplied building validation labels.

    Joins the inference GeoPackage (integer sequential IDs, ``damaged`` 0/1)
    with the building-footprints GeoPackage (Overture string IDs in the same
    row order) to produce a per-building prediction lookup, then compares
    against the human labels stored in BuildingValidation.

    ``Unknown`` labels are excluded from all metric calculations.

    Query params:
        projectId (str): Parent project identifier.
        imageLayerId (str): Image layer identifier.
        modelId (str): Model identifier whose inference results to use.

    Returns JSON:
        {
          "matched": int,            // buildings with both a prediction and a label
          "totalValidationLabels": int,
          "labelCounts": {"Damaged": int, "NotDamaged": int, "Unknown": int},
          "accuracy": float,
          "confusionMatrix": {
            "labels": ["Damaged", "NotDamaged"],
            "matrix": [[TP, FN], [FP, TN]]   // rows=actual, cols=predicted; positive=Damaged
          },
          "perClass": {
            "Damaged":    {"precision": float, "recall": float, "f1": float},
            "NotDamaged": {"precision": float, "recall": float, "f1": float}
          },
          "macroF1": float
        }
    """
    logger.info(
        "GetValidationReport HTTP trigger function processed a request."
    )
    try:
        import os as _os
        import tempfile

        from azure.storage.blob import BlobServiceClient

        project_id = req.params.get("projectId")
        image_layer_id = req.params.get("imageLayerId")
        model_id = req.params.get("modelId")

        if not project_id or not image_layer_id or not model_id:
            return func.HttpResponse(
                "projectId, imageLayerId and modelId are required.",
                status_code=400,
            )

        # ── 1. Load validation labels ──────────────────────────────────────────
        try:
            validation_data = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().VALIDATION.value,
                    partition_key=project_id,
                ).load,
                image_layer_id,
            )
        except FileNotFoundError:
            return func.HttpResponse(
                json.dumps(
                    {
                        "error": "No validation labels found for this image layer."
                    }
                ),
                status_code=404,
                mimetype="application/json",
            )

        labels_dict = validation_data.get("labels") or {}
        if not labels_dict:
            return func.HttpResponse(
                json.dumps(
                    {
                        "error": "No validation labels found for this image layer."
                    }
                ),
                status_code=404,
                mimetype="application/json",
            )

        # ── 2. Load model to get gpkgUrl ───────────────────────────────────────
        model_data = await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().MODEL.value,
                partition_key=project_id,
            ).load,
            model_id,
        )

        gpkg_url = model_data.get("gpkgUrl")
        if not gpkg_url:
            return func.HttpResponse(
                json.dumps(
                    {"error": "No inference results available for this model."}
                ),
                status_code=404,
                mimetype="application/json",
            )

        # ── 3. Load image layer to get buildingFootprintsUrl ──────────────────
        image_layer_data = await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().IMAGELAYER.value,
                partition_key=project_id,
            ).load,
            image_layer_id,
        )

        footprints_url = image_layer_data.get("buildingFootprintsUrl")
        if not footprints_url:
            return func.HttpResponse(
                json.dumps(
                    {
                        "error": "No building footprints available for this image layer."
                    }
                ),
                status_code=404,
                mimetype="application/json",
            )

        # ── 4. Helper: download a blob by its public/SAS URL ──────────────────
        # Container+blob extraction uses _split_blob_url because the Azure
        # SDK's BlobClient.from_blob_url misparses Azurite URLs whose host
        # is the docker-internal `azurite:10000`. See helper docstring.
        conn_str = os.environ.get("BLOB_CONNECTION_STRING", "")
        bsc = BlobServiceClient.from_connection_string(conn_str)

        async def _download_gpkg(url: str) -> str:
            container_name, blob_name = _split_blob_url(url)
            blob_bytes = await asyncio.to_thread(
                lambda: bsc.get_container_client(container_name)
                .get_blob_client(blob_name)
                .download_blob()
                .readall()
            )
            with tempfile.NamedTemporaryFile(
                suffix=".gpkg", delete=False
            ) as tmp:
                tmp.write(blob_bytes)
                return tmp.name

        # ── 5. Read both GeoPackages ───────────────────────────────────────────
        import fiona

        footprints_path = await _download_gpkg(footprints_url)
        gpkg_path = await _download_gpkg(gpkg_url)

        try:
            # Build index → overture_id from the building footprints file
            with fiona.open(footprints_path) as src_fp:
                idx_to_overture = {
                    i: feat["properties"]["id"]
                    for i, feat in enumerate(src_fp)
                }

            # Build int_id → damaged from the inference results
            with fiona.open(gpkg_path) as src_inf:
                int_id_to_damaged = {
                    feat["properties"]["id"]: feat["properties"]["damaged"]
                    for feat in src_inf
                }
        finally:
            _os.unlink(footprints_path)
            _os.unlink(gpkg_path)

        # Build overture_id → predicted_damaged
        overture_to_pred = {
            overture_id: int_id_to_damaged[int_id]
            for int_id, overture_id in idx_to_overture.items()
            if int_id in int_id_to_damaged
        }

        # ── 6. Compute metrics ─────────────────────────────────────────────────
        label_counts = {"Damaged": 0, "NotDamaged": 0, "Unknown": 0}
        for lbl_obj in labels_dict.values():
            lbl = lbl_obj.get("label", "Unknown")
            label_counts[lbl] = label_counts.get(lbl, 0) + 1

        # Matched pairs (exclude Unknown)
        pairs = []
        for overture_id, lbl_obj in labels_dict.items():
            actual_label = lbl_obj.get("label")
            if actual_label == "Unknown":
                continue
            pred = overture_to_pred.get(overture_id)
            if pred is None:
                continue
            pred_label = "Damaged" if pred == 1 else "NotDamaged"
            pairs.append((actual_label, pred_label))

        matched = len(pairs)

        if matched == 0:
            return func.HttpResponse(
                json.dumps(
                    {
                        "matched": 0,
                        "totalValidationLabels": len(labels_dict),
                        "labelCounts": label_counts,
                        "error": "No validation labels could be matched to inference results.",
                    }
                ),
                status_code=200,
                mimetype="application/json",
            )

        # Confusion matrix: rows=actual, cols=predicted, for [Damaged, NotDamaged]
        classes = ["Damaged", "NotDamaged"]
        cm = {a: {p: 0 for p in classes} for a in classes}
        for actual, predicted in pairs:
            cm[actual][predicted] += 1

        matrix = [[cm[a][p] for p in classes] for a in classes]
        correct = sum(cm[c][c] for c in classes)
        accuracy = correct / matched

        def _safe_div(num, den):
            return num / den if den > 0 else 0.0

        per_class = {}
        f1_scores = []
        for cls in classes:
            tp = cm[cls][cls]
            fp = sum(cm[other][cls] for other in classes if other != cls)
            fn = sum(cm[cls][other] for other in classes if other != cls)
            precision = _safe_div(tp, tp + fp)
            recall = _safe_div(tp, tp + fn)
            f1 = _safe_div(2 * precision * recall, precision + recall)
            per_class[cls] = {
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
            }
            f1_scores.append(f1)

        macro_f1 = sum(f1_scores) / len(f1_scores)

        report = {
            "matched": matched,
            "totalValidationLabels": len(labels_dict),
            "labelCounts": label_counts,
            "accuracy": round(accuracy, 4),
            "confusionMatrix": {
                "labels": classes,
                "matrix": matrix,
            },
            "perClass": per_class,
            "macroF1": round(macro_f1, 4),
        }

        return func.HttpResponse(
            json.dumps(report),
            status_code=200,
            mimetype="application/json",
        )

    except Exception as e:
        logger.error(
            f"Error in GetValidationReport: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        return func.HttpResponse(
            "Error generating validation report.", status_code=500
        )


@app.route(
    route="GetAssessmentReport",
    auth_level=AUTH_LEVEL,
    methods=["GET"],
)
async def GetAssessmentReport(req: func.HttpRequest) -> func.HttpResponse:
    """Run the damage-assessment evaluation against the model's inference.

    Reproduces the "Analyze results" computation from the
    ``notebooks/Evaluate-Gezanine_1.ipynb`` notebook and from the
    ``validation/evaluate.py`` CLI: precision/recall/AP against any
    available human labels, the predicted damaged-building count for the
    layer, and a finite-population estimate (with 95% CI) for the total
    damaged count across all footprints above a minimum area threshold.

    The math lives in :func:`hastegeo.core.utils.assessment.compute_assessment_report`.
    This endpoint is the I/O wrapper that pulls the model's merged
    predictions GeoPackage and the layer's cached building footprints
    GeoPackage, joins them on row order (the convention used by
    ``merge_with_building_footprints.py``), and folds in whatever
    validation labels exist.

    Query params:
        projectId (str): Parent project identifier.
        imageLayerId (str): Image layer identifier.
        modelId (str): Model whose inference results to assess.
        threshold (float, optional): Damage fraction above which a
            building is called damaged (default 0.1, same as the CLI).
        minAreaM2 (float, optional): Minimum footprint area in m² for
            the population extrapolation (default 50).
    """
    logger.info(
        "GetAssessmentReport HTTP trigger function processed a request."
    )
    try:
        import os as _os
        import tempfile

        from azure.storage.blob import BlobServiceClient
        from hastegeo.core.utils.assessment import (
            build_assessment_inputs_from_gpkgs,
            compute_assessment_report,
        )

        project_id = req.params.get("projectId")
        image_layer_id = req.params.get("imageLayerId")
        model_id = req.params.get("modelId")

        if not project_id or not image_layer_id or not model_id:
            return func.HttpResponse(
                "projectId, imageLayerId and modelId are required.",
                status_code=400,
            )

        # Parse optional knobs with bounded fallbacks; surfacing 400s on
        # garbage so the modal doesn't try to render an opaque 500.
        try:
            threshold = float(req.params.get("threshold", "0.1"))
        except ValueError:
            return func.HttpResponse(
                "threshold must be a number between 0 and 1.",
                status_code=400,
            )
        if not 0.0 <= threshold <= 1.0:
            return func.HttpResponse(
                "threshold must be between 0 and 1.", status_code=400
            )
        try:
            min_area_m2 = float(req.params.get("minAreaM2", "50"))
        except ValueError:
            return func.HttpResponse(
                "minAreaM2 must be a number >= 0.", status_code=400
            )
        if min_area_m2 < 0:
            return func.HttpResponse(
                "minAreaM2 must be >= 0.", status_code=400
            )

        # Load model + image layer to get the two blob URLs we need.
        model_data = await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().MODEL.value,
                partition_key=project_id,
            ).load,
            model_id,
        )
        gpkg_url = model_data.get("gpkgUrl")
        if not gpkg_url:
            return func.HttpResponse(
                json.dumps(
                    {"error": "No inference results available for this model."}
                ),
                status_code=404,
                mimetype="application/json",
            )

        image_layer_data = await asyncio.to_thread(
            MetadataProcessor(
                data_type=config.get_metadata_types().IMAGELAYER.value,
                partition_key=project_id,
            ).load,
            image_layer_id,
        )
        footprints_url = image_layer_data.get("buildingFootprintsUrl")
        if not footprints_url:
            return func.HttpResponse(
                json.dumps(
                    {
                        "error": "No building footprints available for this image layer."
                    }
                ),
                status_code=404,
                mimetype="application/json",
            )

        # Validation labels are optional for the assessment report — the
        # CLI script can produce the damage-count estimate without labels,
        # and the modal renders that section regardless. The metrics
        # section is what needs labels.
        try:
            validation_data = await asyncio.to_thread(
                MetadataProcessor(
                    data_type=config.get_metadata_types().VALIDATION.value,
                    partition_key=project_id,
                ).load,
                image_layer_id,
            )
            labels_dict = validation_data.get("labels") or {}
        except FileNotFoundError:
            labels_dict = {}

        labels_pairs = [
            (bid, obj.get("label"))
            for bid, obj in labels_dict.items()
            if obj.get("label")
        ]

        # Download both GeoPackages through the function-app-internal
        # BlobServiceClient. Uses _split_blob_url for the same azurite-host
        # reason GetValidationReport does.
        conn_str = os.environ.get("BLOB_CONNECTION_STRING", "")
        bsc = BlobServiceClient.from_connection_string(conn_str)

        async def _download_gpkg(url: str) -> str:
            container_name, blob_name = _split_blob_url(url)
            blob_bytes = await asyncio.to_thread(
                lambda: bsc.get_container_client(container_name)
                .get_blob_client(blob_name)
                .download_blob()
                .readall()
            )
            with tempfile.NamedTemporaryFile(
                suffix=".gpkg", delete=False
            ) as tmp:
                tmp.write(blob_bytes)
                return tmp.name

        footprints_path = await _download_gpkg(footprints_url)
        gpkg_path = await _download_gpkg(gpkg_url)
        try:
            inputs = await asyncio.to_thread(
                build_assessment_inputs_from_gpkgs,
                footprints_path,
                gpkg_path,
                labels=labels_pairs,
            )
        finally:
            for path in (footprints_path, gpkg_path):
                try:
                    _os.unlink(path)
                except OSError:
                    pass

        report = await asyncio.to_thread(
            compute_assessment_report,
            inputs,
            threshold=threshold,
            min_area_m2=min_area_m2,
        )

        return func.HttpResponse(
            json.dumps(report, allow_nan=False),
            status_code=200,
            mimetype="application/json",
        )

    except Exception as e:
        logger.error(
            f"Error in GetAssessmentReport: {e}\n{traceback.format_exc()}",
            stack_info=True,
        )
        return func.HttpResponse(
            "Error generating assessment report.", status_code=500
        )
