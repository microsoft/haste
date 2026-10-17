# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Offline registered DINOv2-S/14 + legacy UPerNet, with no Hub lookups.

Adapted from microsoft/building-damage-assessment at
958ff3d30601ffc3577da81af1ac0a545deb295e (MIT), bda/dino_upernet.py.
DINOv2 backbone code/weights retain Meta's Apache-2.0 license.
Only the registered small backbone and legacy decoder are supported.
"""

from __future__ import annotations

import json

import torch
from bda.dinov3_upernet import TRANSFORMERS_VERSION, UPerHead, _norm
from torch import nn
from torch.nn import functional as F

SOURCE_REVISION = (
    "958ff3d30601ffc3577da81af1ac0a545deb295e"  # pragma: allowlist secret
)
BACKBONE = "dinov2_vits14_reg"
BACKBONE_REVISION = (
    "0d9846e56b43a21fa46d7f3f5070f0506a5795a9"  # pragma: allowlist secret
)

# These are the published xview2_any.json contract, not inferred weight shapes.
EXPECTED_CONFIG = {
    "model_type": "dinov2_with_registers",
    "hidden_size": 384,
    "num_hidden_layers": 12,
    "num_attention_heads": 6,
    "mlp_ratio": 4,
    "hidden_act": "gelu",
    "hidden_dropout_prob": 0.0,
    "attention_probs_dropout_prob": 0.0,
    "layer_norm_eps": 1e-6,
    "image_size": 518,
    "patch_size": 14,
    "num_channels": 3,
    "qkv_bias": True,
    "layerscale_value": 1.0,
    "drop_path_rate": 0.0,
    "use_swiglu_ffn": False,
    "num_register_tokens": 4,
    "apply_layernorm": True,
    "reshape_hidden_states": True,
    "interpolate_antialias": True,
    "interpolate_offset": 0.0,
}


def validate_backbone_config(backbone: str, config: dict) -> dict:
    if backbone != BACKBONE:
        raise ValueError(f"Unsupported DINOv2 backbone: {backbone}")
    if not isinstance(config, dict):
        raise ValueError("DINOv2 requires an embedded backbone_config object")
    try:
        values = json.loads(json.dumps(config, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise ValueError("backbone_config must contain finite JSON") from error
    for key, expected in EXPECTED_CONFIG.items():
        value = values.get(key)
        if type(value) is not type(expected) or value != expected:
            raise ValueError(
                f"Unsupported DINOv2 backbone_config field: {key}"
            )
    if values.get("auto_map") or values.get("custom_pipelines"):
        raise ValueError("Remote/custom backbone configuration is unsupported")
    return values


class DINOv2Backbone(nn.Module):
    """Raw block outputs [3, 6, 9, 12], excluding class and four registers."""

    def __init__(self, backbone: str, backbone_config: dict) -> None:
        super().__init__()
        values = validate_backbone_config(backbone, backbone_config)
        import transformers
        from transformers import (
            Dinov2WithRegistersConfig,
            Dinov2WithRegistersModel,
        )

        if transformers.__version__ != TRANSFORMERS_VERSION:
            raise RuntimeError(
                "DINOv2 runtime requires "
                f"transformers=={TRANSFORMERS_VERSION}"
            )
        config = Dinov2WithRegistersConfig.from_dict(values)
        config._attn_implementation = "sdpa"
        self.vit = Dinov2WithRegistersModel(config)
        self.patch_size = 14
        self.embed_dim = 384
        self.num_prefix_tokens = 5
        self.out_indices = [3, 6, 9, 12]

    def forward(self, x: torch.Tensor) -> list[torch.Tensor]:
        batch, _, height, width = x.shape
        if height % self.patch_size or width % self.patch_size:
            raise ValueError(
                "DINOv2 backbone dimensions must be divisible by 14"
            )
        gh, gw = height // self.patch_size, width // self.patch_size
        outputs = self.vit(pixel_values=x, output_hidden_states=True)
        features = []
        for index in self.out_indices:
            tokens = outputs.hidden_states[index][:, self.num_prefix_tokens :]
            if tokens.shape != (batch, gh * gw, self.embed_dim):
                raise ValueError(
                    "DINOv2 produced an unexpected patch-token grid"
                )
            features.append(
                tokens.transpose(1, 2)
                .reshape(batch, self.embed_dim, gh, gw)
                .contiguous()
            )
        return features


class DINOv2UPerNet(nn.Module):
    def __init__(self, backbone: str, backbone_config: dict) -> None:
        super().__init__()
        self.stem = nn.Identity()
        self.backbone = DINOv2Backbone(backbone, backbone_config)
        dim = self.backbone.embed_dim
        self.fpn1 = nn.Sequential(
            nn.ConvTranspose2d(dim, dim, 2, stride=2),
            _norm(dim),
            nn.GELU(),
            nn.ConvTranspose2d(dim, dim, 2, stride=2),
        )
        self.fpn2 = nn.ConvTranspose2d(dim, dim, 2, stride=2)
        self.fpn3 = nn.Identity()
        self.fpn4 = nn.MaxPool2d(kernel_size=2, stride=2)
        self.decode_head = UPerHead([dim] * 4, channels=256, num_classes=3)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if x.ndim != 4 or x.shape[1] != 3 or min(x.shape[-2:]) < 15:
            raise ValueError("DINOv2 input must be (B,3,H,W) with H,W >= 15")
        height, width = x.shape[-2:]
        x = self.stem(x)
        pad_h, pad_w = -height % 14, -width % 14
        if pad_h or pad_w:
            x = F.pad(x, (0, pad_w, 0, pad_h), mode="reflect")
        features = self.backbone(x)
        features = [
            self.fpn1(features[0]),
            self.fpn2(features[1]),
            self.fpn3(features[2]),
            self.fpn4(features[3]),
        ]
        logits = F.interpolate(
            self.decode_head(features),
            size=x.shape[-2:],
            mode="bilinear",
            align_corners=False,
        )
        return logits[..., :height, :width]
