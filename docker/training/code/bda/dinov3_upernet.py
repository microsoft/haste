# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Offline DINOv3 + UPerNet inference model.

Adapted from microsoft/building-damage-assessment at
4d0d1925dc3a5a63566f047102f8dd474dbbcf80 (MIT). Neck/head module names,
GroupNorm, pyramid scales, and intermediate-token selection are preserved.

The DINOv3 backbone assets are separately licensed by Meta under the DINOv3
License (https://ai.meta.com/resources/models-and-libraries/dinov3-downloads/).
This source's MIT license does not relicense those assets. Supply an authorized
local config; this module never contacts Hugging Face or loads remote code.

Security scope for the pinned transformers==5.5.4: CVE-2026-9856 concerns
tokenizer/ProcessorMixin.save_pretrained chat_template filenames. This module
only constructs the built-in DINOv3 config/model; no tokenizer, processor,
tokenizer_config.json, chat_template or save_pretrained path is used. This is
a scoped reachability statement, not a claim that the package is unaffected.
Adding those APIs requires a fresh security/pin review.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

TRANSFORMERS_VERSION = "5.5.4"
DINOV3_HF_IDS = {
    "dinov3_vits16": "facebook/dinov3-vits16-pretrain-lvd1689m",
    "dinov3_vitb16": "facebook/dinov3-vitb16-pretrain-lvd1689m",
    "dinov3_vitl16": "facebook/dinov3-vitl16-pretrain-lvd1689m",
    "dinov3_vitl16_sat": "facebook/dinov3-vitl16-pretrain-sat493m",
}

# Tensor shapes cannot establish attention heads, RoPE, epsilon or activation.
# Require these in the supplied config rather than infer defaults from weights.
REQUIRED_CONFIG_FIELDS = {
    "model_type",
    "patch_size",
    "hidden_size",
    "intermediate_size",
    "num_hidden_layers",
    "num_attention_heads",
    "num_channels",
    "num_register_tokens",
    "hidden_act",
    "layer_norm_eps",
    "rope_theta",
    "query_bias",
    "key_bias",
    "value_bias",
    "proj_bias",
    "mlp_bias",
    "layerscale_value",
    "use_gated_mlp",
    "pos_embed_shift",
    "pos_embed_jitter",
    "pos_embed_rescale",
}


def _norm(num_channels: int) -> nn.GroupNorm:
    num_groups = 32
    while num_channels % num_groups:
        num_groups //= 2
    return nn.GroupNorm(num_groups, num_channels)


def _conv_bn_relu(in_ch, out_ch, kernel_size=3):
    return nn.Sequential(
        nn.Conv2d(
            in_ch, out_ch, kernel_size, padding=kernel_size // 2, bias=False
        ),
        _norm(out_ch),
        nn.ReLU(inplace=True),
    )


class DINOv3Backbone(nn.Module):
    """Four intermediate token maps, excluding class/register prefix tokens."""

    def __init__(self, name: str, backbone_config: dict):
        super().__init__()
        import transformers
        from transformers import DINOv3ViTConfig, DINOv3ViTModel

        if transformers.__version__ != TRANSFORMERS_VERSION:
            raise RuntimeError(
                f"DINOv3 runtime requires transformers=={TRANSFORMERS_VERSION}; "
                "other releases have different state keys/implementations"
            )
        if name not in DINOV3_HF_IDS:
            raise ValueError(f"Unsupported DINOv3 backbone: {name}")
        missing = REQUIRED_CONFIG_FIELDS - backbone_config.keys()
        if missing:
            raise ValueError(
                f"Incomplete local backbone config: {sorted(missing)}"
            )
        if (
            backbone_config["model_type"] != "dinov3_vit"
            or backbone_config.get("auto_map")
            or backbone_config["num_channels"] != 3
            or backbone_config["patch_size"] != 16
        ):
            raise ValueError("Expected a local RGB DINOv3 ViT/16 config")
        config = DINOv3ViTConfig.from_dict(backbone_config)
        # Pin the built-in attention path as well: a supplied JSON must not
        # select Hub kernels or other external attention implementations.
        config._attn_implementation = "sdpa"
        # Direct construction avoids AutoConfig.from_pretrained (gated even
        # when pretrained=False) and prevents custom/remote architecture code.
        self.vit = DINOv3ViTModel(config)
        self.patch_size = int(config.patch_size)
        self.embed_dim = int(config.hidden_size)
        self.num_prefix_tokens = 1 + int(config.num_register_tokens)
        n_layers = int(config.num_hidden_layers)
        if n_layers < 4:
            raise ValueError(
                "DINOv3 UPerNet needs at least four transformer layers"
            )
        self.out_indices = [
            n_layers // 4,
            n_layers // 2,
            3 * n_layers // 4,
            n_layers,
        ]

    def forward(self, x: torch.Tensor) -> list[torch.Tensor]:
        b, _, h, w = x.shape
        if h % self.patch_size or w % self.patch_size:
            raise ValueError(
                "Input dimensions must be divisible by patch size"
            )
        gh, gw = h // self.patch_size, w // self.patch_size
        outputs = self.vit(pixel_values=x, output_hidden_states=True)
        feats = []
        for idx in self.out_indices:
            tokens = outputs.hidden_states[idx][:, self.num_prefix_tokens :, :]
            feat = tokens.transpose(1, 2).reshape(b, self.embed_dim, gh, gw)
            feats.append(feat.contiguous())
        return feats


class _PPM(nn.ModuleList):
    def __init__(self, pool_scales, in_dim, channels):
        super().__init__()
        for scale in pool_scales:
            self.append(
                nn.Sequential(
                    nn.AdaptiveAvgPool2d(scale),
                    nn.Conv2d(in_dim, channels, 1, bias=False),
                    _norm(channels),
                    nn.ReLU(inplace=True),
                )
            )

    def forward(self, x):
        return [
            F.interpolate(
                block(x),
                size=x.shape[2:],
                mode="bilinear",
                align_corners=False,
            )
            for block in self
        ]


class UPerHead(nn.Module):
    def __init__(
        self,
        in_channels,
        channels=256,
        num_classes=3,
        pool_scales=(1, 2, 3, 6),
    ):
        super().__init__()
        self.ppm = _PPM(pool_scales, in_channels[-1], channels)
        self.ppm_bottleneck = _conv_bn_relu(
            in_channels[-1] + len(pool_scales) * channels, channels, 3
        )
        self.lateral_convs = nn.ModuleList(
            [_conv_bn_relu(c, channels, 1) for c in in_channels[:-1]]
        )
        self.fpn_convs = nn.ModuleList(
            [_conv_bn_relu(channels, channels, 3) for _ in in_channels[:-1]]
        )
        self.fpn_bottleneck = _conv_bn_relu(
            len(in_channels) * channels, channels, 3
        )
        self.dropout = nn.Dropout2d(0.1)
        self.classifier = nn.Conv2d(channels, num_classes, 1)

    def forward(self, feats):
        laterals = [
            conv(feats[i]) for i, conv in enumerate(self.lateral_convs)
        ]
        psp = torch.cat([feats[-1], *self.ppm(feats[-1])], dim=1)
        laterals.append(self.ppm_bottleneck(psp))
        for i in range(len(laterals) - 1, 0, -1):
            laterals[i - 1] = laterals[i - 1] + F.interpolate(
                laterals[i],
                size=laterals[i - 1].shape[2:],
                mode="bilinear",
                align_corners=False,
            )
        fpn_outs = [
            self.fpn_convs[i](laterals[i]) for i in range(len(laterals) - 1)
        ]
        fpn_outs.append(laterals[-1])
        for i in range(1, len(fpn_outs)):
            fpn_outs[i] = F.interpolate(
                fpn_outs[i],
                size=fpn_outs[0].shape[2:],
                mode="bilinear",
                align_corners=False,
            )
        out = self.fpn_bottleneck(torch.cat(fpn_outs, dim=1))
        return self.classifier(self.dropout(out))


class DINOv3UPerNet(nn.Module):
    """Reference neck/head with a config-only, strictly loaded backbone."""

    def __init__(
        self,
        backbone,
        backbone_config,
        in_channels=3,
        num_classes=3,
        channels=256,
    ):
        super().__init__()
        self.stem = (
            nn.Conv2d(in_channels, 3, 1) if in_channels != 3 else nn.Identity()
        )
        self.backbone = DINOv3Backbone(backbone, backbone_config)
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
        self.decode_head = UPerHead(
            [dim, dim, dim, dim], channels=channels, num_classes=num_classes
        )

    def forward(self, x):
        h, w = x.shape[-2:]
        feats = self.backbone(self.stem(x))
        feats = [
            self.fpn1(feats[0]),
            self.fpn2(feats[1]),
            self.fpn3(feats[2]),
            self.fpn4(feats[3]),
        ]
        logits = self.decode_head(feats)
        return F.interpolate(
            logits, size=(h, w), mode="bilinear", align_corners=False
        )
