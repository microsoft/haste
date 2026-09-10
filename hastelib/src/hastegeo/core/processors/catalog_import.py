# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Import locally verified transformer assets into configured catalog storage.

Run with ``python -m hastegeo.core.processors.catalog_import --help``.
The recipe comes from offline checkpoint/configuration acceptance, not a
browser submission. This command does not download or execute remote code.
"""

import argparse
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from ..config import Config
from ..models.pretrained_inference import CatalogInferenceSpec
from ..models.training import CatalogModel
from ..utils.catalog_lock import catalog_lock
from ..utils.logs import Logger
from .model_catalog import ModelCatalogProcessor

DINOV2_SOURCE_REVISION = (
    "958ff3d30601ffc3577da81af1ac0a545deb295e"  # pragma: allowlist secret
)
DINOV2_MANIFEST_SHA256 = "cbe9a4baec53e8a4f40fd27e5aacddb659836a1828dee3f0fe605adf1ad2d250"  # pragma: allowlist secret
DINOV2_CHECKPOINTS = (
    (
        "original_only",
        0,
        48884,
        "e6f1894b169a65c5ec937509cf5353148063f06825464684dea2628d0699f962",  # pragma: allowlist secret
    ),
    (
        "original_only",
        1,
        53328,
        "c8d6aa2d3943ac98fc667b920cd6dabe7cd99957aa7ec76ac9a2e167c430ae9f",  # pragma: allowlist secret
    ),
    (
        "original_only",
        2,
        51106,
        "5d58bd64979fd7c40bb8a88888b9a12fed7c1692289e7739401b2f4cec51cb45",  # pragma: allowlist secret
    ),
    (
        "source_balanced_50_50",
        0,
        57772,
        "e7f06e67331e5a149bc0c4981201b59f29316902e7a763e71b7541201bd62f6e",  # pragma: allowlist secret
    ),
    (
        "source_balanced_50_50",
        1,
        55550,
        "ebe8aaa2489e9716322df7a184a01eea9d63d35ad2e4947ca6030c4cfd193f8b",  # pragma: allowlist secret
    ),
    (
        "source_balanced_50_50",
        2,
        42218,
        "2a069ecc313bb33836daca8ed20743eb69e594c165cc777c5c1c3a1150bc2e57",  # pragma: allowlist secret
    ),
)


def dinov2_followup_entries(catalogued_by: str) -> list[CatalogModel]:
    """Six separately selectable, validation-selected xView2 checkpoints."""
    source_url = (
        "https://github.com/microsoft/building-damage-assessment/tree/"
        + DINOV2_SOURCE_REVISION
    )
    entries = []
    for condition, seed, update, digest in DINOV2_CHECKPOINTS:
        label = (
            "original only"
            if condition == "original_only"
            else "source-balanced 50/50"
        )
        relative = f"{condition}/seed_{seed:03d}_update_{update:06d}.ckpt"
        blob_path = "model_checkpoints/dinov2_followups_20260927/" + relative
        entries.append(
            CatalogModel(
                baseModelName=f"DINOv2 xView2 {label} (seed {seed})",
                description=(
                    f"DINOv2/UPerNet any-damage; {label}, seed {seed}, "
                    f"update {update}. Validation-selected within a predeclared "
                    "configuration, not selected by test results."
                ),
                source="external",
                cataloguedByUser=catalogued_by,
                capabilities=["inference"],
                checkpointFilePath=relative,
                additionalInfo={
                    "study": "xview2_dinov2_followups/run_001",
                    "condition": condition,
                    "seed": seed,
                    "selectedUpdate": update,
                    "manifestSha256": DINOV2_MANIFEST_SHA256,
                    "sourceRevision": DINOV2_SOURCE_REVISION,
                    "checkpointUrl": (
                        "https://geospatialvisualizer.blob.core.windows.net/"
                        "damage-assessments/" + blob_path
                    ),
                    "backboneLicense": "Apache-2.0",
                },
                inferenceSpec=CatalogInferenceSpec(
                    adapter="dinov2_upernet",
                    checkpointFilePath=relative,
                    checkpointSha256=digest,
                    backbone="dinov2_vits14_reg",
                    labelGrouping="any",
                    sourceRevision=DINOV2_SOURCE_REVISION,
                    sourceUrl=source_url,
                    inputKind="rgb",
                    numChannels=3,
                    normalizationMeans=[0.485, 0.456, 0.406],
                    normalizationStds=[0.229, 0.224, 0.225],
                ),
            )
        )
    return entries


def file_sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


class ModelCatalogAssetImporter:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config()
        self.catalog = ModelCatalogProcessor(self.config)
        self.artifacts = self.catalog.artifacts

    def _verify_stored(self, path: str, digest: str) -> None:
        with TemporaryDirectory() as directory:
            self.artifacts.fetch_artifact(identifier=path, dst_path=directory)
            local = Path(directory) / (
                Path(path).name
                if self.config.artifact_storage_type == "local"
                else path
            )
            if not local.is_file() or file_sha256(local) != digest:
                raise ValueError(
                    "Stored catalog asset failed SHA-256 verification"
                )

    def _import_asset(self, local: Path, digest: str, filename: str) -> str:
        namespace = ["model-catalog", "assets", digest]
        target = "/".join([*namespace, filename])
        if not self.artifacts.artifact_exists(target):
            self.artifacts.store_artifact(
                filename, src_path=str(local), namespace=namespace
            )
        self._verify_stored(target, digest)
        return target

    def import_model(
        self,
        entry: CatalogModel,
        checkpoint_file: Path,
        backbone_config_file: Path | None = None,
    ) -> CatalogModel:
        entry = entry.model_copy(deep=True)
        spec = entry.inferenceSpec
        if (
            entry.source != "external"
            or entry.capabilities != ["inference"]
            or spec is None
            or spec.adapter not in ("dinov2_upernet", "dinov3_upernet")
        ):
            raise ValueError(
                "Import requires an inference-only transformer recipe"
            )
        assets = [(checkpoint_file, spec.checkpointSha256)]
        if spec.adapter == "dinov3_upernet":
            if backbone_config_file is None:
                raise ValueError("DINOv3 import requires --backbone-config")
            assets.append((backbone_config_file, spec.backboneConfigSha256))
        elif backbone_config_file is not None:
            raise ValueError("DINOv2 uses its embedded backbone configuration")
        for local, digest in assets:
            if file_sha256(local) != digest:
                raise ValueError(
                    "Local catalog asset does not match its approved SHA-256"
                )
        with catalog_lock(self.config, key="asset-import"):
            spec.checkpointFilePath = self._import_asset(
                checkpoint_file, spec.checkpointSha256, "model.ckpt"
            )
            if backbone_config_file is not None:
                spec.backboneConfigPath = self._import_asset(
                    backbone_config_file,
                    spec.backboneConfigSha256,
                    "config.json",
                )
            spec.checkpointEtag = self.artifacts.get_artifact_etag(
                spec.checkpointFilePath
            )
            entry.checkpointFilePath = spec.checkpointFilePath
            return self.catalog.add(entry, idempotent=True)

    def import_dinov2_followups(
        self, checkpoint_directory: Path, catalogued_by: str
    ) -> list[CatalogModel]:
        entries = dinov2_followup_entries(catalogued_by)
        assets = [
            checkpoint_directory / entry.inferenceSpec.checkpointFilePath
            for entry in entries
        ]
        for entry, checkpoint in zip(entries, assets):
            if file_sha256(checkpoint) != entry.inferenceSpec.checkpointSha256:
                raise ValueError(
                    f"DINOv2 checkpoint failed SHA-256 verification: {checkpoint.name}"
                )
        return [
            self.import_model(entry, checkpoint)
            for entry, checkpoint in zip(entries, assets)
        ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    recipe = parser.add_mutually_exclusive_group(required=True)
    recipe.add_argument("--recipe", type=Path)
    recipe.add_argument(
        "--dinov2-followups",
        type=Path,
        help="Directory containing the two condition folders from the 20260927 manifest",
    )
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--backbone-config", type=Path)
    parser.add_argument("--catalogued-by")
    args = parser.parse_args()
    if args.dinov2_followups:
        if not args.catalogued_by or not args.catalogued_by.strip():
            parser.error("--dinov2-followups requires --catalogued-by")
        if args.checkpoint or args.backbone_config:
            parser.error(
                "--dinov2-followups does not accept individual asset flags"
            )
        registered = ModelCatalogAssetImporter().import_dinov2_followups(
            args.dinov2_followups, args.catalogued_by
        )
    else:
        if args.checkpoint is None:
            parser.error("--recipe requires --checkpoint")
        entry = CatalogModel.model_validate_json(args.recipe.read_text())
        registered = [
            ModelCatalogAssetImporter().import_model(
                entry, args.checkpoint, args.backbone_config
            )
        ]
    for entry in registered:
        Logger.get_logger(__name__).info(
            "Registered inference catalog model %s", entry.baseModelName
        )


if __name__ == "__main__":
    main()
