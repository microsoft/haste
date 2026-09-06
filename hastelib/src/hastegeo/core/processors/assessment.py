import asyncio
import os
from typing import Any, Callable, Dict, Optional

from ..config import Config
from ..models.prediction_results import ResultsRequest
from ..utils.assessment import (
    build_assessment_inputs_from_gpkgs,
    compute_assessment_report,
)
from ..utils.blob import download_blob_to_tempfile
from .metadata import MetadataProcessor
from .prediction_results import PredictionResultsProcessor


class AssessmentSizeLimitError(ValueError):
    """Raised when assessment inputs exceed the configured byte budget."""


class AssessmentReportProcessor:
    """Load HASTE artifacts and compute one server-side assessment report."""

    def __init__(
        self,
        config: Optional[Config] = None,
        processor_factory: Callable[
            ..., MetadataProcessor
        ] = MetadataProcessor,
        downloader: Callable[..., Any] = download_blob_to_tempfile,
    ) -> None:
        self.config = config or Config()
        self.processor_factory = processor_factory
        self.downloader = downloader

    async def generate(
        self,
        project_id: str,
        image_layer_id: str,
        model_id: str,
        threshold: float = 0.1,
        min_area_m2: float = 50,
        max_total_bytes: Optional[int] = None,
    ) -> Dict[str, Any]:
        if max_total_bytes is not None and max_total_bytes < 1:
            raise ValueError("max_total_bytes must be positive")
        metadata_types = self.config.get_metadata_types()
        model, image_layer = await asyncio.to_thread(
            PredictionResultsProcessor(
                self.config, self.processor_factory
            ).raw_context,
            ResultsRequest(
                projectId=project_id,
                imageLayerId=image_layer_id,
                modelId=model_id,
            ),
        )
        gpkg_url = model.gpkgUrl
        footprints_url = image_layer.buildingFootprintsUrl
        if not footprints_url:
            raise FileNotFoundError(
                "No building footprints available for this image layer"
            )

        try:
            validation_data = await asyncio.to_thread(
                self.processor_factory(
                    data_type=metadata_types.VALIDATION.value,
                    partition_key=project_id,
                    config=self.config,
                ).load,
                image_layer_id,
            )
            labels_dict = validation_data.get("labels") or {}
        except FileNotFoundError:
            labels_dict = {}
        labels = [
            (building_id, value.get("label"))
            for building_id, value in labels_dict.items()
            if value.get("label")
        ]

        downloaded_paths = []
        try:
            try:
                footprints_path = await self.downloader(
                    footprints_url,
                    suffix=".gpkg",
                    max_bytes=max_total_bytes,
                )
            except ValueError as error:
                if "allowed download size" in str(error):
                    raise AssessmentSizeLimitError(
                        "Assessment inputs exceed the allowed size"
                    ) from error
                raise
            downloaded_paths.append(footprints_path)
            remaining_bytes = (
                None
                if max_total_bytes is None
                else max_total_bytes - os.path.getsize(footprints_path)
            )
            if remaining_bytes is not None and remaining_bytes < 1:
                raise AssessmentSizeLimitError(
                    "Assessment inputs exceed the allowed size"
                )
            try:
                gpkg_path = await self.downloader(
                    gpkg_url,
                    suffix=".gpkg",
                    max_bytes=remaining_bytes,
                )
            except ValueError as error:
                if "allowed download size" in str(error):
                    raise AssessmentSizeLimitError(
                        "Assessment inputs exceed the allowed size"
                    ) from error
                raise
            downloaded_paths.append(gpkg_path)
            inputs = await asyncio.to_thread(
                build_assessment_inputs_from_gpkgs,
                footprints_path,
                gpkg_path,
                labels=labels,
            )
            return await asyncio.to_thread(
                compute_assessment_report,
                inputs,
                threshold=threshold,
                min_area_m2=min_area_m2,
            )
        finally:
            for path in downloaded_paths:
                try:
                    os.unlink(path)
                except OSError:
                    pass
