# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Import locally verified DINOv3 assets into configured catalog storage.

Run with ``python -m hastegeo.core.processors.catalog_import --help``.
The recipe comes from offline checkpoint/configuration acceptance, not a
browser submission. This command does not download or execute remote code.
"""

import argparse
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from ..config import Config
from ..models.training import CatalogModel
from ..utils.catalog_lock import catalog_lock
from ..utils.logs import Logger
from .model_catalog import ModelCatalogProcessor


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
        backbone_config_file: Path,
    ) -> CatalogModel:
        entry = entry.model_copy(deep=True)
        spec = entry.inferenceSpec
        if (
            entry.source != "external"
            or entry.capabilities != ["inference"]
            or spec is None
            or spec.adapter != "dinov3_upernet"
        ):
            raise ValueError("Import requires an inference-only DINOv3 recipe")
        for local, digest in (
            (checkpoint_file, spec.checkpointSha256),
            (backbone_config_file, spec.backboneConfigSha256),
        ):
            if file_sha256(local) != digest:
                raise ValueError(
                    "Local catalog asset does not match its approved SHA-256"
                )
        with catalog_lock(self.config, key="asset-import"):
            spec.checkpointFilePath = self._import_asset(
                checkpoint_file, spec.checkpointSha256, "model.ckpt"
            )
            spec.backboneConfigPath = self._import_asset(
                backbone_config_file, spec.backboneConfigSha256, "config.json"
            )
            spec.checkpointEtag = self.artifacts.get_artifact_etag(
                spec.checkpointFilePath
            )
            entry.checkpointFilePath = spec.checkpointFilePath
            return self.catalog.add(entry, idempotent=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--backbone-config", type=Path, required=True)
    args = parser.parse_args()
    entry = CatalogModel.model_validate_json(args.recipe.read_text())
    registered = ModelCatalogAssetImporter().import_model(
        entry, args.checkpoint, args.backbone_config
    )
    Logger.get_logger(__name__).info(
        "Registered inference catalog model %s", registered.baseModelName
    )


if __name__ == "__main__":
    main()
