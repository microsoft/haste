# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Per-building embedding workflow for the building labeling workflow.

Ported from ``interactive-building-labeler/embed_buildings.py`` and adapted
to the HASTE workflow contract used by
``prepare_imagery.py``:

* Driven by a single ``--config`` JSON file.
* Reads the post-event mosaic COG and the cached building-footprints GeoPackage
  (both downloaded into the task working dir by the runner).
* For each building footprint: crop the imagery around its bounding box, run
  the selected embedding model on the crop, mask the building polygon into
  the token grid, and average the token features into one vector per building.
* Writes three outputs to ``outputs/``: a GeoJSON of footprints + ``f_0..f_N``
  feature columns, a PMTiles vector-tile file (via tippecanoe), and a manifest.

CRITICAL — row-order invariant:
    ``GetValidationReport`` / ``GetAssessmentReport`` join predictions to the
    layer's ``buildingFootprintsUrl`` GeoPackage **by row index**. So this
    workflow MUST emit exactly one output row per footprint, in the footprints
    file's native order, with ``id = 0..N-1``. Buildings that fall outside the
    raster extent (or yield zero tokens) keep their slot with NaN features —
    they are never dropped or reordered.
"""

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Callable, Dict, Optional

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.windows
import torch
import torch.nn as nn
import torch.nn.functional as F
from hastegeo.core.utils.logs import Logger as HasteLogger
from rasterio.features import geometry_mask
from shapely.geometry import mapping
from torch import Tensor
from torchgeo.datasets import NonGeoDataset
from torchgeo.models import RCF

WORKDIR = os.getenv("WORKDIR", ".")
LOG_DIR = os.path.join(WORKDIR, "logs")
LOG_FILE = "embedding_verbose.log"
os.makedirs(LOG_DIR, exist_ok=True)

logger = HasteLogger.get_logger(
    "embed_buildings", log_dir=LOG_DIR, log_file=LOG_FILE
)
logger.info("Executing %s", __file__)

# ---------------------------------------------------------------------------
# Constants (must match the reference embed_buildings.py)
# ---------------------------------------------------------------------------
# MOSAIKS token stride (RCF block_size). Kept as the canonical default so the
# pure-python helpers (compute_crop_windows, rasterize_building_in_token_grid)
# behave identically to the pre-DINOv2 module when called positionally.
TOKEN_STRIDE = 16
DEFAULT_MOSAIKS_FEATS = 1024
DEFAULT_MOSAIKS_KERNEL_SIZE = 7
DEFAULT_RESIZE_FACTOR = 4
DEFAULT_BATCH_SIZE = 16
DEFAULT_CONTEXT_PX = 8
# Cap a single building's crop (in SOURCE pixels) so a large footprint can't
# blow up GPU/CPU memory: at resize_factor R the model input is this * R per
# axis. 192 src px keeps even a 4x crop at 768px, ~few-GB conv activations.
# Oversized buildings get a centered crop — fine for mean-pooled texture feats.
DEFAULT_MAX_CROP_PX = 192
# Cap the conv-activation tensor elements per forward so the batch size adapts
# down for large crops (keeps a batch's peak allocation in the low-GB range).
MAX_ACT_ELEMENTS = 2.5e8

# Administrator-approved immutable SAT-493M snapshot. Validation happens
# before AutoModel allocates the model so a truncated, substituted, or unsafe
# snapshot never reaches the deserializer.
DINOV3_SAT_SNAPSHOT_MANIFEST = {
    "config.json": {
        "sha256": (
            "135ecd23e34a70b6fbed8b083fdecb319b7e3a54e3d849258bbe4ddcf1783bb5"  # pragma: allowlist secret
        ),
        "size": 745,
    },
    "model.safetensors": {
        "sha256": (
            "4e6356d992c1301b5e7c275f465e47296c5c4ad17052e262b29fc21e82ccc698"  # pragma: allowlist secret
        ),
        "size": 1212559808,
    },
}
UNSAFE_MODEL_SUFFIXES = {".bin", ".pt", ".pth", ".py"}

# Where to look for pre-baked torch.hub assets (DINOv2 source + weights). The
# training docker image populates this at build time so workflow runs don't
# touch the internet. Falls back to the default torch.hub cache if missing
# (useful for local dev runs outside the docker image).
TORCH_HUB_CACHE_DIR = "/opt/torch-hub-cache/hub"


# ---------------------------------------------------------------------------
# Model wrappers
# ---------------------------------------------------------------------------
class RCFPooled(RCF):
    """RCF with block-level average pooling (16x16 -> 1 token)."""

    def __init__(
        self,
        in_channels: int = 3,
        features: int = 512,
        kernel_size: int = 3,
        bias: float = -1.0,
        seed: Optional[int] = None,
        mode: str = "gaussian",
        dataset: Optional[NonGeoDataset] = None,
        block_size: int = 16,
    ) -> None:
        super().__init__(
            in_channels=in_channels,
            features=features,
            kernel_size=kernel_size,
            bias=bias,
            seed=seed,
            mode=mode,
            dataset=dataset,
        )
        self.block_size = int(block_size)

    def forward(self, x: Tensor) -> Tensor:
        assert x.dim() == 3, "Input tensor must have 3 dimensions (C, H, W)"
        padding = self.weights.shape[-1] // 2
        pos = F.relu(
            F.conv2d(
                x, self.weights, bias=self.biases, stride=1, padding=padding
            ),
            inplace=True,
        )
        neg = F.relu(
            -F.conv2d(
                x, self.weights, bias=self.biases, stride=1, padding=padding
            ),
            inplace=False,
        )
        k = self.block_size
        pos_pool = F.avg_pool2d(pos, kernel_size=k, stride=k, ceil_mode=False)
        neg_pool = F.avg_pool2d(neg, kernel_size=k, stride=k, ceil_mode=False)
        num_features, H_pool, W_pool = pos_pool.shape
        pos_pool = pos_pool.view(num_features, -1)
        neg_pool = neg_pool.view(num_features, -1)
        features = torch.cat([pos_pool, neg_pool], dim=0)
        features = features.permute(1, 0)
        return features


class BatchedMosaiksWrapper(nn.Module):
    def __init__(
        self,
        features: int = DEFAULT_MOSAIKS_FEATS,
        kernel_size: int = DEFAULT_MOSAIKS_KERNEL_SIZE,
        block_size: int = TOKEN_STRIDE,
    ):
        super().__init__()
        self.backbone = RCFPooled(
            in_channels=3,
            features=features,
            kernel_size=kernel_size,
            seed=0,
            mode="gaussian",
            block_size=block_size,
        ).eval()

    @torch.no_grad()
    def forward(self, x: Tensor) -> Tensor:
        if x.dim() == 3:
            x = x.unsqueeze(0)
        assert x.dim() == 4 and x.size(1) == 3
        padding = self.backbone.weights.shape[-1] // 2
        pos = F.relu(
            F.conv2d(
                x,
                self.backbone.weights,
                bias=self.backbone.biases,
                stride=1,
                padding=padding,
            ),
            inplace=True,
        )
        neg = F.relu(
            -F.conv2d(
                x,
                self.backbone.weights,
                bias=self.backbone.biases,
                stride=1,
                padding=padding,
            ),
            inplace=False,
        )
        pool_size = self.backbone.block_size
        pos_pool = F.avg_pool2d(
            pos, kernel_size=pool_size, stride=pool_size, ceil_mode=False
        )
        neg_pool = F.avg_pool2d(
            neg, kernel_size=pool_size, stride=pool_size, ceil_mode=False
        )
        feats = torch.cat([pos_pool, neg_pool], dim=1)
        B, C, H, W = feats.shape
        feats = feats.view(B, C, H * W).transpose(1, 2).contiguous()
        return feats


class _DinoV2PatchTokensWrapper(nn.Module):
    """Thin wrapper that returns DINOv2 patch tokens as ``(B, H*W, D)``.

    DINOv2 is loaded via ``torch.hub`` from a pre-baked cache (so Azure Batch
    nodes don't reach out to GitHub at runtime). The model's
    ``forward_features`` returns a dict with ``x_norm_patchtokens``: a
    ``(B, N_patches, D)`` tensor of L2-normalized patch features. We reshape
    it back to the same layout MOSAIKS uses (one token per grid cell, row-major)
    so the downstream masking/pooling code is shared.

    Build inputs must be ``(B, 3, H, W)`` with H and W both multiples of 14
    (the DINOv2 patch size). ``embed_footprints`` enforces this by rounding
    each batch's interpolated model input up to a multiple of ``patch_size``.
    """

    PATCH_SIZE = 14

    # Per-variant output feature dim (the ``num_features`` attribute of the
    # underlying DINOv2 ViT — kept as a constant lookup so callers don't need
    # the model handle to know the expected dim).
    VARIANT_DIMS = {
        "dinov2_vits14": 384,
        "dinov2_vitb14": 768,
        "dinov2_vitl14": 1024,
    }

    def __init__(self, variant: str):
        super().__init__()
        if variant not in self.VARIANT_DIMS:
            raise ValueError(
                f"Unknown DINOv2 variant {variant!r}. "
                f"Supported: {sorted(self.VARIANT_DIMS)}"
            )
        self.variant = variant
        # Prefer a pre-baked hub cache (training docker image populates
        # /opt/torch-hub-cache/hub). Fall back to torch.hub's default cache
        # for local dev runs outside the image.
        if os.path.isdir(TORCH_HUB_CACHE_DIR):
            torch.hub.set_dir(TORCH_HUB_CACHE_DIR)
        # ``skip_validation=True`` avoids a GitHub API call to check tag/SHA
        # state when the cached zip is already present.
        self.backbone = torch.hub.load(
            "facebookresearch/dinov2",
            variant,
            trust_repo=True,
            skip_validation=True,
        ).eval()

    @torch.no_grad()
    def forward(self, x: Tensor) -> Tensor:
        if x.dim() == 3:
            x = x.unsqueeze(0)
        assert x.dim() == 4 and x.size(1) == 3
        if x.shape[-1] % self.PATCH_SIZE or x.shape[-2] % self.PATCH_SIZE:
            raise ValueError(
                f"DINOv2 input dims must be multiples of {self.PATCH_SIZE}; "
                f"got {tuple(x.shape[-2:])}"
            )
        out = self.backbone.forward_features(x)
        # (B, num_patches, D) — num_patches = (H/P) * (W/P), row-major.
        return out["x_norm_patchtokens"]


class _DinoV3SatPatchTokensWrapper(nn.Module):
    """Load staged DINOv3-SAT weights and return patch tokens only."""

    PATCH_SIZE = 16
    FEATURE_DIM = 1024
    REQUIRED_FILES = ("config.json", "model.safetensors")

    def __init__(self, model_path: Optional[str]):
        super().__init__()
        if not model_path:
            raise ValueError(
                "A local model_path is required for the dinov3_sat model."
            )
        if os.path.islink(model_path):
            raise ValueError(
                "DINOv3-SAT model directory must not be a symlink: "
                f"{model_path}"
            )
        if not os.path.isdir(model_path):
            raise FileNotFoundError(
                f"DINOv3-SAT model directory not found: {model_path}"
            )
        self._validate_snapshot(model_path)

        # Imported only for this model so existing embedding runtimes do not
        # require transformers. The flags prohibit Hub/network fallback,
        # executable repository code, and pickle weight deserialization.
        from transformers import AutoModel

        self.backbone = AutoModel.from_pretrained(
            model_path,
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
        ).eval()
        config = self.backbone.config
        if getattr(config, "model_type", None) != "dinov3_vit":
            raise ValueError(
                "Invalid DINOv3-SAT metadata: model_type must be "
                "'dinov3_vit'."
            )
        if getattr(config, "patch_size", None) != self.PATCH_SIZE:
            raise ValueError(
                "Invalid DINOv3-SAT metadata: patch_size must be 16."
            )
        if getattr(config, "hidden_size", None) != self.FEATURE_DIM:
            raise ValueError(
                "Invalid DINOv3-SAT metadata: hidden_size must be 1024."
            )
        register_tokens = getattr(config, "num_register_tokens", None)
        if (
            not isinstance(register_tokens, int)
            or isinstance(register_tokens, bool)
            or not 0 <= register_tokens <= 256
        ):
            raise ValueError(
                "Invalid DINOv3-SAT metadata: num_register_tokens must be "
                "an integer between 0 and 256."
            )
        self.num_register_tokens = register_tokens

    @classmethod
    def _validate_snapshot(cls, model_path: str) -> None:
        """Verify the staged snapshot against the approved two-file manifest."""
        snapshot_root = os.path.abspath(model_path)
        found_files = set()
        for root, dirs, files in os.walk(snapshot_root, followlinks=False):
            for name in dirs + files:
                path = os.path.join(root, name)
                relative_path = os.path.relpath(path, snapshot_root)
                if os.path.islink(path):
                    raise ValueError(
                        "DINOv3-SAT model snapshot must not contain symlinks: "
                        f"{relative_path}"
                    )
            if dirs:
                relative_dirs = sorted(
                    os.path.relpath(os.path.join(root, name), snapshot_root)
                    for name in dirs
                )
                raise ValueError(
                    "DINOv3-SAT model snapshot must not contain directories: "
                    + ", ".join(relative_dirs)
                )
            for name in files:
                path = os.path.join(root, name)
                relative_path = os.path.relpath(path, snapshot_root)
                if not os.path.isfile(path):
                    raise ValueError(
                        "DINOv3-SAT model snapshot entries must be regular "
                        f"files: {relative_path}"
                    )
                found_files.add(relative_path)
                if os.path.splitext(name)[1].lower() in UNSAFE_MODEL_SUFFIXES:
                    raise ValueError(
                        "DINOv3-SAT model snapshot contains an unsafe file: "
                        f"{relative_path}"
                    )

        expected_files = set(DINOV3_SAT_SNAPSHOT_MANIFEST)
        missing = [
            filename
            for filename in cls.REQUIRED_FILES
            if filename not in found_files
        ]
        if missing:
            raise FileNotFoundError(
                "DINOv3-SAT model directory is missing required file(s): "
                + ", ".join(missing)
            )
        unexpected = sorted(found_files - expected_files)
        if unexpected:
            raise ValueError(
                "DINOv3-SAT model snapshot contains unexpected file(s): "
                + ", ".join(unexpected)
            )

        for filename, expected in DINOV3_SAT_SNAPSHOT_MANIFEST.items():
            path = os.path.join(snapshot_root, filename)
            actual_size = os.path.getsize(path)
            if actual_size != expected["size"]:
                raise ValueError(
                    f"DINOv3-SAT snapshot size mismatch for {filename}: "
                    f"expected {expected['size']}, got {actual_size}."
                )
            digest = hashlib.sha256()
            with open(path, "rb") as snapshot_file:
                for chunk in iter(
                    lambda: snapshot_file.read(1024 * 1024), b""
                ):
                    digest.update(chunk)
            actual_sha256 = digest.hexdigest()
            if actual_sha256 != expected["sha256"]:
                raise ValueError(
                    f"DINOv3-SAT snapshot SHA-256 mismatch for {filename}."
                )

    @torch.no_grad()
    def forward(self, x: Tensor) -> Tensor:
        if x.dim() == 3:
            x = x.unsqueeze(0)
        if x.dim() != 4 or x.size(1) != 3:
            raise ValueError("DINOv3-SAT input must have shape (B, 3, H, W).")
        if x.shape[-1] % self.PATCH_SIZE or x.shape[-2] % self.PATCH_SIZE:
            raise ValueError(
                f"DINOv3-SAT input dims must be multiples of {self.PATCH_SIZE}; "
                f"got {tuple(x.shape[-2:])}"
            )
        hidden_state = self.backbone(pixel_values=x).last_hidden_state
        patch_tokens = hidden_state[:, 1 + self.num_register_tokens :, :]
        expected_patches = (x.shape[-2] // self.PATCH_SIZE) * (
            x.shape[-1] // self.PATCH_SIZE
        )
        if patch_tokens.shape[1] != expected_patches:
            raise ValueError(
                "DINOv3-SAT output patch-token count does not match input: "
                f"expected {expected_patches}, got {patch_tokens.shape[1]}."
            )
        if patch_tokens.shape[-1] != self.FEATURE_DIM:
            raise ValueError(
                "DINOv3-SAT output hidden dimension must be 1024; "
                f"got {patch_tokens.shape[-1]}."
            )
        return patch_tokens


# ---------------------------------------------------------------------------
# Embedding-model factory (used by embed_footprints to dispatch on
# pipeline.model). Returns a uniform handle so the cropping/masking/pooling
# code paths are shared across model families.
# ---------------------------------------------------------------------------
def build_embedding_model(
    model_name: str,
    *,
    num_feats: int = DEFAULT_MOSAIKS_FEATS,
    kernel_size: int = DEFAULT_MOSAIKS_KERNEL_SIZE,
    model_path: Optional[str] = None,
) -> Dict[str, object]:
    """Build the embedding model and return its uniform inference handle.

    ``model_name`` is one of:

    - ``"mosaiks"``: torchgeo RCF with 16x16 block pooling. ``num_feats`` and
      ``kernel_size`` configurable (default 1024, 7). Per-band normalization
      is the 3-channel mean/std from the original MOSAIKS reference impl.
    - ``"dinov2_vits14"`` / ``"dinov2_vitb14"`` / ``"dinov2_vitl14"``:
      DINOv2 ViT patch tokens (14x14 patches). ``num_feats`` is ignored — the
      output dim is fixed by the variant (384 / 768 / 1024). Normalization is
      the ImageNet mean/std DINOv2 was trained with.
    - ``"dinov3_sat"``: locally staged SAT-493M DINOv3 ViT-L/16 patch
      tokens. ``model_path`` must contain the approved Hugging Face snapshot.

    Returns a dict with:

    - ``model``: callable ``(B, 3, H, W) -> (B, N_tokens, D)``
    - ``patch_size``: pixels per token side in MODEL input space (16 or 14)
    - ``feat_dim``: D
    - ``img_mean`` / ``img_std``: ``(1, 3, 1, 1)`` per-channel normalization
      tensors that the workflow applies before resizing/forward.
    """
    if model_name == "mosaiks":
        model: Callable[[Tensor], Tensor] = BatchedMosaiksWrapper(
            features=num_feats,
            kernel_size=kernel_size,
            block_size=TOKEN_STRIDE,
        )
        return {
            "model": model,
            "patch_size": TOKEN_STRIDE,
            # torchgeo's RCF halves the per-filter count internally so the
            # pos/neg ReLU concat lands back at exactly ``features`` channels.
            "feat_dim": int(num_feats),
            # Reference embed_buildings.py per-channel stats.
            "img_mean": torch.tensor([0.430, 0.411, 0.296]).view(1, 3, 1, 1),
            "img_std": torch.tensor([0.213, 0.156, 0.143]).view(1, 3, 1, 1),
        }
    if model_name.startswith("dinov2_"):
        backbone = _DinoV2PatchTokensWrapper(model_name)
        return {
            "model": backbone,
            "patch_size": _DinoV2PatchTokensWrapper.PATCH_SIZE,
            "feat_dim": _DinoV2PatchTokensWrapper.VARIANT_DIMS[model_name],
            # ImageNet mean/std — what DINOv2 was pre-trained with.
            "img_mean": torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1),
            "img_std": torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1),
        }
    if model_name == "dinov3_sat":
        backbone = _DinoV3SatPatchTokensWrapper(model_path)
        return {
            "model": backbone,
            "patch_size": _DinoV3SatPatchTokensWrapper.PATCH_SIZE,
            "feat_dim": _DinoV3SatPatchTokensWrapper.FEATURE_DIM,
            # ImageNet stats match the repo-loaded dinov3_sat reference.
            "img_mean": torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1),
            "img_std": torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1),
        }
    raise ValueError(
        f"Unknown embedding model {model_name!r}. "
        "Supported: mosaiks, dinov2_vits14, dinov2_vitb14, dinov2_vitl14, "
        "dinov3_sat."
    )


# ---------------------------------------------------------------------------
# Geometry / crop helpers (ported verbatim from the reference)
# ---------------------------------------------------------------------------
def pad_to_multiple(val: int, multiple: int) -> int:
    """Round *up* to next multiple."""
    return math.ceil(val / multiple) * multiple


def compute_crop_windows(
    footprints: gpd.GeoDataFrame,
    raster_transform: rasterio.Affine,
    raster_height: int,
    raster_width: int,
    context_px: int = DEFAULT_CONTEXT_PX,
    resize_factor: int = 1,
    max_crop_px: int = DEFAULT_MAX_CROP_PX,
    patch_size: int = TOKEN_STRIDE,
) -> list[dict]:
    """Compute a token-aligned pixel crop window per building.

    Returns one dict per building that intersects the raster, each keyed by the
    building's original (native-order) row index in ``footprints``. Buildings
    that don't overlap the raster are omitted (they keep a NaN slot downstream).
    A crop wider/taller than ``max_crop_px`` source pixels is centered and
    capped so a single large footprint can't exhaust GPU/CPU memory at the
    upscaled resolution.

    ``patch_size`` is the model's token side length (pixels per token in MODEL
    input space): 16 for MOSAIKS, 14 for DINOv2. The source-pixel padding
    ``grain`` (``patch_size // resize_factor``) keeps the upscaled model input
    aligned to whole tokens for the common case where ``resize_factor`` evenly
    divides ``patch_size``; for the misaligned case ``embed_footprints``
    additionally rounds the model input up to a ``patch_size`` multiple.
    """
    inv_transform = ~raster_transform
    grain = max(1, patch_size // resize_factor)
    crops = []

    for idx, geom in zip(footprints.index, footprints.geometry):
        if geom is None or geom.is_empty:
            continue

        minx, miny, maxx, maxy = geom.bounds

        px_left, px_top = inv_transform * (minx, maxy)
        px_right, px_bottom = inv_transform * (maxx, miny)

        c0 = int(math.floor(min(px_left, px_right))) - context_px
        r0 = int(math.floor(min(px_top, px_bottom))) - context_px
        c1 = int(math.ceil(max(px_left, px_right))) + context_px
        r1 = int(math.ceil(max(px_top, px_bottom))) + context_px

        # Skip buildings entirely outside the raster (no usable pixels).
        if c1 <= 0 or r1 <= 0 or c0 >= raster_width or r0 >= raster_height:
            continue

        c0 = max(0, c0)
        r0 = max(0, r0)
        c1 = min(raster_width, c1)
        r1 = min(raster_height, r1)

        w = c1 - c0
        h = r1 - r0

        # Cap oversized crops, keeping them centered on the building.
        if max_crop_px and w > max_crop_px:
            c0 = max(
                0, min(c0 + (w - max_crop_px) // 2, raster_width - max_crop_px)
            )
            w = max_crop_px
        if max_crop_px and h > max_crop_px:
            r0 = max(
                0,
                min(r0 + (h - max_crop_px) // 2, raster_height - max_crop_px),
            )
            h = max_crop_px

        if w < grain or h < grain:
            w = max(w, grain)
            h = max(h, grain)
            c0 = max(0, min(c0, raster_width - w))
            r0 = max(0, min(r0, raster_height - h))

        pw = pad_to_multiple(w, grain)
        ph = pad_to_multiple(h, grain)

        crops.append(
            {
                "idx": idx,
                "col_off": c0,
                "row_off": r0,
                "width": w,
                "height": h,
                "padded_width": pw,
                "padded_height": ph,
            }
        )

    return crops


def rasterize_building_in_token_grid(
    geom,
    crop_transform: rasterio.Affine,
    token_h: int,
    token_w: int,
    resize_factor: int = 1,
    patch_size: int = TOKEN_STRIDE,
) -> np.ndarray:
    """Rasterize a building polygon into the token-resolution grid.

    ``patch_size`` is the model's token side in MODEL pixels (16 for MOSAIKS,
    14 for DINOv2); the effective stride in SOURCE pixels is
    ``patch_size / resize_factor``.
    """
    effective_stride = patch_size / resize_factor
    token_transform = crop_transform * rasterio.Affine.scale(
        effective_stride, effective_stride
    )
    mask = geometry_mask(
        [mapping(geom)],
        out_shape=(token_h, token_w),
        transform=token_transform,
        all_touched=True,
        invert=True,  # True where the building IS
    )
    return mask


def read_crop(raster, crop: dict) -> np.ndarray:
    """Read a crop from the raster, zero-pad to padded dimensions."""
    window = rasterio.windows.Window(
        crop["col_off"], crop["row_off"], crop["width"], crop["height"]
    )
    data = raster.read(window=window)  # (bands, h, w)
    bands, h, w = data.shape

    ph, pw = crop["padded_height"], crop["padded_width"]
    if h == ph and w == pw:
        return data

    padded = np.zeros((bands, ph, pw), dtype=data.dtype)
    padded[:, :h, :w] = data
    return padded


def column_names(num_bands: int) -> list[str]:
    """Feature column names for the mean reducer: f_0 .. f_{N-1}."""
    return [f"f_{i}" for i in range(num_bands)]


def _forward_batch(model, images_cpu, device):
    """Run the model on a (CPU) batch, returning features on CPU.

    Tries the requested device first; on CUDA OOM (e.g. a shared GPU under
    pressure, or an unusually large crop) it frees the cache and retries the
    batch on CPU so the whole job can't be killed by a single heavy building.
    """
    try:
        with torch.inference_mode(), torch.amp.autocast(
            "cuda", enabled=device.type == "cuda"
        ):
            feats = model(images_cpu.to(device))
        return feats.float().cpu()
    except torch.cuda.OutOfMemoryError:
        torch.cuda.empty_cache()
        logger.warning("CUDA OOM on a batch; retrying on CPU")
        model.to("cpu")
        try:
            with torch.inference_mode():
                feats = model(images_cpu.to("cpu"))
            return feats.float().cpu()
        finally:
            model.to(device)


def assemble_output(
    footprints: gpd.GeoDataFrame,
    feature_matrix: np.ndarray,
    pixel_counts: np.ndarray,
    col_names: list[str],
) -> gpd.GeoDataFrame:
    """Build the row-aligned output GeoDataFrame (the row-order invariant).

    Exactly one output row per input footprint, in the footprints file's
    native order. Adds the ``f_*`` feature columns (NaN where a building had no
    valid tokens), ``emb_px_count``, an integer row-index ``id`` (what the
    Validation/Assessment reports join on), and preserves any Overture ``id``
    under ``overture_id``. Output geometry is EPSG:4326.
    """
    feature_df = pd.DataFrame(
        feature_matrix, columns=col_names, index=footprints.index
    )
    feature_df["emb_px_count"] = pixel_counts

    out = footprints.copy()
    if "id" in out.columns:
        out = out.rename(columns={"id": "overture_id"})
    out = pd.concat([out, feature_df], axis=1)
    out = gpd.GeoDataFrame(
        out, geometry=footprints.geometry.name, crs=footprints.crs
    )
    out.insert(0, "id", range(len(out)))
    return out.to_crs(epsg=4326)


# ---------------------------------------------------------------------------
# Embedding driver
# ---------------------------------------------------------------------------
def embed_footprints(
    image_path: str,
    footprints_path: str,
    *,
    model_name: str = "mosaiks",
    num_feats: int = DEFAULT_MOSAIKS_FEATS,
    kernel_size: int = DEFAULT_MOSAIKS_KERNEL_SIZE,
    resize_factor: int = DEFAULT_RESIZE_FACTOR,
    batch_size: int = DEFAULT_BATCH_SIZE,
    context_px: int = DEFAULT_CONTEXT_PX,
    model_path: Optional[str] = None,
) -> gpd.GeoDataFrame:
    """Embed every building footprint and return a row-aligned GeoDataFrame.

    The output has exactly ``len(footprints)`` rows in the footprints file's
    native order, columns ``f_0..f_{feat_dim-1}`` (NaN for buildings outside
    the raster / with zero tokens), ``emb_px_count``, an integer row-index
    ``id``, the original ``overture_id``, and geometry in EPSG:4326.

    ``model_name`` selects the embedding backbone — see ``build_embedding_model``
    for the supported list. ``num_feats`` and ``kernel_size`` only apply to
    the MOSAIKS backbone; DINO variants ignore them (output dim is fixed by
    the selected model).
    """
    log_progress(f"Reading footprints from {footprints_path}")
    footprints = gpd.read_file(footprints_path)
    if footprints.empty:
        raise ValueError("Footprints file is empty.")
    if footprints.crs is None:
        raise ValueError("Footprints have no CRS.")
    footprints = footprints.reset_index(drop=True)
    n_total = len(footprints)
    log_progress(f"{n_total} footprints loaded (CRS: {footprints.crs})")

    raster = rasterio.open(image_path)
    raster_crs = raster.crs
    raster_transform = raster.transform
    raster_h, raster_w = raster.height, raster.width
    raster_bands = raster.count
    log_progress(
        f"Image: {raster_w}x{raster_h}, {raster_bands} bands, "
        f"CRS: {raster_crs}"
    )
    if raster_bands < 3:
        raster.close()
        raise ValueError(
            f"Image has {raster_bands} bands; need at least 3 (RGB)."
        )

    # Reproject geometries to the raster CRS for cropping/masking, but keep the
    # native row order (no clipping, no drops).
    if footprints.crs != raster_crs:
        log_progress(
            f"Reprojecting footprints {footprints.crs} -> {raster_crs}"
        )
        geoms_work = footprints.to_crs(raster_crs).geometry
    else:
        geoms_work = footprints.geometry

    work = gpd.GeoDataFrame(geometry=geoms_work, crs=raster_crs)
    work.index = footprints.index  # preserve native order indices

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    log_progress(f"Loading {model_name} model on {device}...")
    handle = build_embedding_model(
        model_name,
        num_feats=num_feats,
        kernel_size=kernel_size,
        model_path=model_path,
    )
    model = handle["model"].to(device)
    patch_size = int(handle["patch_size"])
    feat_dim = int(handle["feat_dim"])
    img_mean = handle["img_mean"]
    img_std = handle["img_std"]

    log_progress("Computing crop windows...")
    crops = compute_crop_windows(
        work,
        raster_transform,
        raster_h,
        raster_w,
        context_px,
        resize_factor=resize_factor,
        patch_size=patch_size,
    )
    log_progress(f"{len(crops)} of {n_total} footprints overlap the raster")

    # Group by padded size for efficient batching.
    size_groups: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for crop in crops:
        key = (crop["padded_height"], crop["padded_width"])
        size_groups[key].append(crop)

    col_names = column_names(feat_dim)
    feature_matrix = np.full(
        (n_total, len(col_names)), np.nan, dtype=np.float32
    )
    pixel_counts = np.zeros(n_total, dtype=np.int32)

    done = 0
    for (ph, pw), group in sorted(size_groups.items()):
        # Model input must be a multiple of ``patch_size``. For MOSAIKS this
        # is automatic (grain = patch_size // resize_factor), but for DINOv2
        # with a resize_factor that doesn't evenly divide 14 we round up.
        model_h = pad_to_multiple(ph * resize_factor, patch_size)
        model_w = pad_to_multiple(pw * resize_factor, patch_size)
        token_h = model_h // patch_size
        token_w = model_w // patch_size

        # Shrink the batch for large crops so the activation tensor stays
        # within MAX_ACT_ELEMENTS (peak ~ feat_dim * model_h * model_w * bs).
        per_image = max(1, feat_dim * model_h * model_w)
        eff_bs = max(1, min(batch_size, int(MAX_ACT_ELEMENTS // per_image)))

        for batch_start in range(0, len(group), eff_bs):
            batch_crops = group[batch_start : batch_start + eff_bs]
            bs = len(batch_crops)

            images = torch.zeros(bs, 3, ph, pw, dtype=torch.float32)
            for i, crop in enumerate(batch_crops):
                raw = read_crop(raster, crop)  # (bands, ph, pw)
                images[i] = torch.from_numpy(raw[:3].astype(np.float32))

            images = (images / 255.0 - img_mean) / img_std
            if images.shape[-2] != model_h or images.shape[-1] != model_w:
                images = F.interpolate(
                    images,
                    size=(model_h, model_w),
                    mode="bilinear",
                    align_corners=False,
                )

            features = _forward_batch(model, images, device)
            features = features.numpy().reshape(bs, token_h, token_w, feat_dim)

            for i, crop in enumerate(batch_crops):
                row_idx = crop["idx"]
                geom = work.geometry.loc[row_idx]

                crop_transform = (
                    raster_transform
                    * rasterio.Affine.translation(
                        crop["col_off"], crop["row_off"]
                    )
                )
                mask = rasterize_building_in_token_grid(
                    geom,
                    crop_transform,
                    token_h,
                    token_w,
                    resize_factor,
                    patch_size=patch_size,
                )
                n_valid = int(mask.sum())
                pixel_counts[row_idx] = n_valid
                if n_valid == 0:
                    continue

                token_features = features[i][mask]
                feature_matrix[row_idx] = np.nanmean(token_features, axis=0)

            done += bs
        if device.type == "cuda":
            torch.cuda.empty_cache()
        log_progress(f"Embedded {done}/{len(crops)} buildings")

    raster.close()

    # Assemble output, preserving native footprint order (one row per input).
    out = assemble_output(footprints, feature_matrix, pixel_counts, col_names)

    n_empty = int((out["emb_px_count"] == 0).sum())
    log_progress(
        f"Embedded {n_total - n_empty}/{n_total} buildings "
        f"({n_empty} with no valid tokens kept as NaN)"
    )
    return out


def write_pmtiles(geojson_path: str, pmtiles_path: str) -> None:
    """Convert a GeoJSON to PMTiles via tippecanoe.

    Keeps only the row-index ``id`` and ``overture_id`` attributes on each
    feature (via ``-y``); the heavy ``f_*`` columns ride in a separate
    binary sidecar (see :func:`write_features_sidecar`). Without ``-y``
    every tile would carry several KB of feature vectors per building,
    blowing up archive size and slowing every pan.

    Lift the per-tile size cap so a dense max-zoom tile carrying every
    geometry-only feature isn't trimmed; with ``f_*`` no longer in the
    tiles this is a very cheap "keep all buildings" guarantee.
    """
    cmd = [
        "tippecanoe",
        "-o",
        pmtiles_path,
        "-l",
        "buildings",
        # Bake the row-index `id` into each tile as the MVT feature id. This
        # gives every footprint a stable, native feature id so the interactive
        # labeler can drive per-building coloring via map feature-state — both
        # MapLibre and Azure Maps need this (Azure Maps' VectorTileSource does
        # not honor client-side promoteId).
        "--use-attribute-for-id=id",
        # Strip every attribute except id + overture_id. The labeler does
        # not need anything else in the tiles — feature vectors are looked
        # up from the sidecar by id, and Overture id is needed for the
        # PutInteractiveLabels round-trip.
        "-y",
        "id",
        "-y",
        "overture_id",
        "--force",
        # Cull world-scale levels — buildings are invisible below z=10,
        # so generating tiles there only adds bytes.
        "--minimum-zoom=10",
        # Pin the max zoom to the labeler's working zoom + 1. Tiles at
        # z>15 are rendered by the SDK via overzoom; the interactive
        # labeler's queryRenderedFeatures + setFeatureState work unchanged
        # on overzoomed tiles.
        "--maximum-zoom=15",
        # With f_* gone from the tiles even a dense urban tile is small;
        # we still pass --no-tile-size-limit so the default 500 KB cap
        # never bites and the build never silently drops a footprint.
        "--no-tile-size-limit",
        # Last-resort safety valve.
        "--drop-densest-as-needed",
        geojson_path,
    ]
    log_progress(f"Running tippecanoe -> {os.path.basename(pmtiles_path)}")
    subprocess.run(cmd, check=True)


# Binary sidecar format:
#   bytes  0-3  : magic "HFTR" (4 ASCII chars)
#   bytes  4-7  : u32 LE  version (currently 1)
#   bytes  8-11 : u32 LE  num_buildings (= row count in the embeddings GeoJSON)
#   bytes 12-15 : u32 LE  feat_dim       (= number of f_* columns)
#   bytes 16-..              : f32 LE * num_buildings * feat_dim
#                              (row-major, indexed directly by the row-index id)
#
# Row indexing matches the embeddings GeoJSON's "id" column (0..N-1), so the
# browser looks up a building's feature vector as
#   features.subarray(id * feat_dim, (id + 1) * feat_dim)
# Non-finite slots (off-raster buildings with NaN features) are written as
# NaN — the labeler's isValidVector() filter already rejects them.
SIDECAR_MAGIC = b"HFTR"
SIDECAR_VERSION = 1


def write_features_sidecar(
    gdf: gpd.GeoDataFrame, sidecar_path: str
) -> tuple[int, int]:
    """Write the per-building f_* vectors to a compact binary sidecar.

    The labeler fetches this file once at session start and looks vectors
    up by their row-index id — the in-tile attributes are kept down to just
    id + overture_id (see ``write_pmtiles``), so the PMTiles archive stays
    small and the labeler still has the data it needs to train + predict.

    Returns ``(num_buildings, feat_dim)``.
    """
    feat_cols = [c for c in gdf.columns if c.startswith("f_")]
    feat_cols.sort(key=lambda c: int(c[2:]))  # f_0, f_1, ..., f_N
    if not feat_cols:
        raise ValueError(
            "GeoDataFrame has no f_* columns to write to sidecar."
        )
    n = len(gdf)
    d = len(feat_cols)
    # NaN-fill is preserved on the round-trip — invalid feature rows stay
    # NaN in the sidecar and the labeler's isValidVector filter rejects them.
    matrix = np.ascontiguousarray(gdf[feat_cols].to_numpy(dtype=np.float32))
    header = (
        SIDECAR_MAGIC
        + np.uint32(SIDECAR_VERSION).tobytes()
        + np.uint32(n).tobytes()
        + np.uint32(d).tobytes()
    )
    with open(sidecar_path, "wb") as f:
        f.write(header)
        # Single contiguous write — pandas already gave us a contiguous f32
        # block, so this is a straight memcpy from numpy to disk.
        matrix.tofile(f)
    log_progress(
        f"Wrote features sidecar -> {os.path.basename(sidecar_path)} "
        f"({n} buildings × {d} dims, "
        f"{(16 + n * d * 4) / (1024 * 1024):.1f} MB)"
    )
    return n, d


# ---------------------------------------------------------------------------
# CLI / workflow entrypoint
# ---------------------------------------------------------------------------
def log_progress(message):
    """Append a friendly progress line consumed by EmbeddingPostprocessor."""
    logger.info(message)
    log_file = os.path.join(LOG_DIR, "embedding_friendly.log")
    with open(log_file, "a") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()}|{message}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=str, required=True, help="Path to config JSON file"
    )
    args = parser.parse_args()

    if not os.path.exists(args.config):
        logger.error("No config file found at location %s", args.config)
        sys.exit(1)

    with open(args.config) as f:
        config = json.load(f)
    if not config:
        logger.error("Config file is empty")
        sys.exit(1)

    output_dir = os.path.join(WORKDIR, config.get("output_dir", "outputs"))
    os.makedirs(output_dir, exist_ok=True)

    files = config.get("files", {})
    pipeline = config.get("pipeline", {})
    image_path = files.get("imagery")
    footprints_path = files.get("footprints")
    embeddings_name = files.get(
        "embeddings", f"building_embeddings_{config.get('model_id')}.geojson"
    )
    pmtiles_name = files.get(
        "pmtiles", f"building_pmtiles_{config.get('model_id')}.pmtiles"
    )
    sidecar_name = files.get(
        "sidecar", f"building_features_{config.get('model_id')}.bin"
    )

    try:
        if not image_path or not os.path.exists(image_path):
            raise FileNotFoundError(f"Imagery not found: {image_path}")
        if not footprints_path or not os.path.exists(footprints_path):
            raise FileNotFoundError(f"Footprints not found: {footprints_path}")

        log_progress("Embedding buildings")
        gdf = embed_footprints(
            image_path,
            footprints_path,
            model_name=str(pipeline.get("model", "mosaiks")),
            num_feats=int(pipeline.get("num_feats", DEFAULT_MOSAIKS_FEATS)),
            kernel_size=int(
                pipeline.get(
                    "mosaiks_kernel_size", DEFAULT_MOSAIKS_KERNEL_SIZE
                )
            ),
            resize_factor=int(
                pipeline.get("resize_factor", DEFAULT_RESIZE_FACTOR)
            ),
            batch_size=int(pipeline.get("batch_size", DEFAULT_BATCH_SIZE)),
            model_path=files.get("model"),
        )

        embeddings_path = os.path.join(
            output_dir, os.path.basename(embeddings_name)
        )
        log_progress(f"Writing {len(gdf)} buildings -> {embeddings_path}")
        gdf.to_file(embeddings_path, driver="GeoJSON")

        # Features sidecar — must be written BEFORE the PMTiles step strips
        # the f_* columns from the tiles, so the in-memory gdf is still
        # the authoritative source for both.
        sidecar_path = os.path.join(output_dir, os.path.basename(sidecar_name))
        num_buildings, feat_dim = write_features_sidecar(gdf, sidecar_path)

        pmtiles_path = os.path.join(output_dir, os.path.basename(pmtiles_name))
        write_pmtiles(embeddings_path, pmtiles_path)

        manifest = {
            "embeddings_filename": os.path.basename(embeddings_path),
            "pmtiles_filename": os.path.basename(pmtiles_path),
            "sidecar_filename": os.path.basename(sidecar_path),
            "num_buildings": int(num_buildings),
            "num_features": int(feat_dim),
        }
        log_progress("Finalizing outputs")
        with open(
            os.path.join(output_dir, "embedding_manifest.json"), "w"
        ) as f:
            json.dump(manifest, f, indent=4)
        logger.info("Building embedding completed successfully.")
    except Exception as e:
        logger.error("Error during building embedding", exc_info=True)
        log_progress(f"Error during building embedding: {e}")
        raise


if __name__ == "__main__":
    try:
        import multiprocessing

        multiprocessing.set_start_method("fork", force=True)
    except Exception:
        pass
    try:
        main()
    except Exception as e:
        logger.error(f"Error during main execution: {e}", exc_info=True)
        sys.exit(1)
