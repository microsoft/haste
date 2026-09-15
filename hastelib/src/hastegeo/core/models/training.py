# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from .pretrained_inference import CatalogInferenceSpec


class ModelSource(str, Enum):
    HASTE = "haste"
    EXTERNAL = "external"


class Imagery(BaseModel):
    normalization_means: Optional[List[int]] = None
    normalization_stds: Optional[List[int]] = None
    num_channels: Optional[int] = None
    raw_fn: Optional[str] = None
    rgb_fn: Optional[str] = None


class Inference(BaseModel):
    output_subdir: str = Field(default="")
    batch_size: int = Field(default=1)
    gpu_id: int = Field(default=0)
    checkpoint_fn: str = Field(default="")
    padding: Optional[int] = Field(default=None)
    patch_size: Optional[int] = Field(default=None)
    building_footprints_source: Optional[str] = Field(default=None)
    country_alpha2_iso_code: Optional[str] = Field(default=None)
    predictions_gpkg_fileprefix: Optional[str] = Field(default=None)


class Labels(BaseModel):
    buffer_in_meters: Optional[int] = None
    class_to_buffer: Optional[str] = None
    class_to_buffer_by: Optional[str] = None
    classes: Optional[List[str]] = None
    fn: Optional[str] = None
    # Tile the labels onto a grid of this cell size (in the units of the
    # imagery CRS) and emit one image/mask pair per populated cell. None keeps
    # the single-pair behavior of cropping to the full label extent.
    cluster_size_in_meters: Optional[float] = Field(default=None, gt=0)
    # Clusters with fewer labeled pixels than this are discarded. Only used
    # when cluster_size_in_meters is set; create_masks.py defaults to 1000.
    min_pixels_per_cluster: Optional[int] = Field(default=None, ge=0)


class Training(BaseModel):
    batch_size: Optional[int] = None
    checkpoint_subdir: Optional[str] = None
    gpu_id: Optional[int] = None
    # Multi-GPU (DDP) training. Takes precedence over gpu_id when set.
    gpu_ids: Optional[List[int]] = None
    # Read every tile into RAM rather than decompressing each patch from
    # disk. Much faster, but the tiles must fit; under DDP each process
    # preloads independently. None leaves the container default (on).
    preload: Optional[bool] = None
    learning_rate: Optional[float] = None
    log_dir: Optional[str] = None
    max_epochs: Optional[int] = None
    use_constraint_loss: Optional[bool] = False
    initial_weights_fn: Optional[str] = None


class ExperimentConfig(BaseModel):
    experiment_dir: Optional[str] = None
    experiment_name: Optional[str] = None
    imagery: Optional[Imagery] = None
    inference: Inference = Field(default_factory=Inference)
    labels: Optional[Labels] = None
    training: Optional[Training] = None


class CatalogModel(BaseModel):
    baseModelName: str = Field(min_length=1, max_length=100)
    description: Optional[str] = None
    modelId: Optional[str] = None
    projectId: Optional[str] = None
    imageLayerId: Optional[str] = None
    imagerySource: Optional[str] = None
    checkpointFilePath: Optional[str] = None
    eventTypes: Optional[List[str]] = None
    cataloguedDate: Optional[str] = None
    cataloguedByUser: str
    additionalInfo: Optional[dict] = None
    source: ModelSource = Field(default=ModelSource.HASTE)
    usedByModels: list[str] = Field(default_factory=list)
    capabilities: list[Literal["training", "inference"]] | None = None
    inferenceSpec: CatalogInferenceSpec | None = None

    @model_validator(mode="after")
    def validate_catalog_contract(self) -> "CatalogModel":
        if not self.baseModelName.strip():
            raise ValueError("Catalog names must not be blank")
        if (
            self.inferenceSpec is not None
            and self.inferenceSpec.adapter == "dinov3_upernet"
            and self.capabilities != ["inference"]
        ):
            raise ValueError("DINOv3 catalog models support inference only")
        return self
