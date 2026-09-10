# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Prepare a CatalogModel JSON only after offline asset acceptance.

Stdout is one JSON document: a validated CatalogModel on success (exit 0), or
a non-importable ``status=blocked`` diagnostic (exit 2). No registration,
credential output or unrestricted pickle loading. Runtime acceptance is offline.
The optional --fetch-backbone-config preparation step uses normal authenticated
Hub access at a resolved commit. Downloads and optional recipe files stay in
ignored localtmp/pretrained-assets.

Supply an authorized local backbone JSON and a local provenance JSON with:
  schemaVersion: 1
  checkpointSha256: <digest of the checkpoint evidenced by the training record>
  backboneConfigSha256: <digest of the authorized configuration export>
  backboneConfigSource: <authorized repo/revision/export reference>
  labelGrouping: any
  labelMapping: [0, 1, 2, 2, 2]
  labelGroupingSource: <training record/reference tied to this checkpoint>

The helper verifies the provenance's asset bindings, not the truth of external
training records. The operator must supply actual evidence, not infer grouping
from the filename. Missing evidence never yields a runnable recipe.

DINOv3 assets retain their separate Meta DINOv3 license, not this source's MIT
license. The parent importer owns controlled storage and registration.

Checkpoint deserialization requires torch>=2.10.0 for CVE-2026-24747, including
weights_only=True. Transformers 5.5.4 is retained for reference compatibility:
CVE-2026-9856's tokenizer/ProcessorMixin.save_pretrained path is not used.
Config export is DINOv3ViTConfig.to_json_string, not save_pretrained.
"""

import argparse
import ast
import base64
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

URL = (
    "https://geospatialvisualizer.blob.core.windows.net/damage-assessments/"
    "model_checkpoints/xview2_dinov3_upernet_any-last.ckpt"
)
SIZE = 377542808
MD5 = "q7OFTDJZUjCHk78g361bWw=="
ETAG = '"0x8DF0E9FE270A779"'
SHA256 = "d3c351c9822665359f78e835ece81d4ff518f8ceb736b5a815e1d72e2dc2c92f"  # pragma: allowlist secret
SOURCE_REVISION = "4d0d1925dc3a5a63566f047102f8dd474dbbcf80"  # pragma: allowlist secret
ROOT = Path(__file__).resolve().parents[1]
BACKBONE_REPOSITORY = "facebook/dinov3-vits16-pretrain-lvd1689m"
REFERENCE_HASHES = {
    "inference_dinov3.py": (
        "b03be58b8fe7c5f6c4cb0a160a247b5f8a2953bcb653473e0dae594ce3da14d8"  # pragma: allowlist secret
    ),
    "bda/dinov3_upernet.py": (
        "42b4863da410a6deca0a2dba2d956f2a000cfbfb6b81814fa717ab1a56414c81"  # pragma: allowlist secret
    ),
    "bda/xview2.py": (
        "137b55315682408e0cb2ed19e2178d3e6b584f8a94b09f9c2a3bf21b03aee19b"  # pragma: allowlist secret
    ),
    "scripts/xview2_dinov3_upernet_RESULTS.md": (
        "0f5bfe85641ee600eb591fbbdd473957c80026b895dbd41a28f7fffd40bae329"  # pragma: allowlist secret
    ),
    "scripts/train_eval_xview2_dinov3_upernet.py": (
        "f9fd4ff9d82d2b0a1c27f74982acb7c81fb2323c9e9463da1bd9bf397116868e"  # pragma: allowlist secret
    ),
}


def stage_reference_sources():
    """Stage hash-pinned MIT reference code/docs; never execute training code."""
    directory = asset_directory() / "reference" / SOURCE_REVISION
    base = (
        "https://raw.githubusercontent.com/microsoft/"
        f"building-damage-assessment/{SOURCE_REVISION}/"
    )
    for name, digest in REFERENCE_HASHES.items():
        path = directory / name
        if not path.exists():
            with urllib.request.urlopen(base + name, timeout=120) as source:
                content = source.read()
            if hashlib.sha256(content).hexdigest() != digest:
                raise ValueError(f"Reference source hash mismatch: {name}")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(content)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Staged reference hash mismatch: {name}")
    return directory


def relative_run_path(value):
    """Retain the recorded output path without publishing private home prefixes."""
    if not isinstance(value, str):
        return None
    if value.startswith("outputs/"):
        return value
    if "/outputs/" in value:
        return "outputs/" + value.split("/outputs/", 1)[1]
    return Path(value).name


def original_any_provenance(backbone_config):
    """Bind the supplied artifact to its embedded original-any run and source LUT."""
    evidence = inspect_checkpoint(stage_checkpoint())
    _, config_sha = read_json_asset(backbone_config)
    config_record, _ = read_json_asset(
        backbone_config.parent / "config.provenance.json"
    )
    if config_record.get("expandedConfigSha256") != config_sha:
        raise ValueError(
            "Expanded config does not match its authorized export"
        )
    official = backbone_config.parent / "config.json"
    _, official_sha = read_json_asset(official)
    if config_record.get("officialConfigSha256") != official_sha:
        raise ValueError("Official config does not match its recorded digest")
    if config_record.get("repository") != BACKBONE_REPOSITORY:
        raise ValueError("Unexpected backbone repository")
    reference = stage_reference_sources()
    # Parse the literal mapping, not the training module or any of its imports.
    syntax = ast.parse((reference / "bda/xview2.py").read_text())
    groupings = [
        ast.literal_eval(node.value)
        for node in syntax.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "GROUPINGS"
            for target in node.targets
        )
    ]
    if len(groupings) != 1 or groupings[0].get("any") != [0, 1, 2, 2, 2]:
        raise ValueError("Pinned source did not establish the any grouping")
    run = "outputs/xview2_dinov3_upernet_any/checkpoints"
    matches = [
        item
        for item in evidence["training"]["checkpointCallbacks"]
        if item["runDirectory"] == run
        and item["lastModelPath"] == run + "/last.ckpt"
    ]
    if len(matches) != 1:
        raise ValueError("Checkpoint is not tied to the original any run")
    results_url = (
        "https://github.com/microsoft/building-damage-assessment/blob/"
        f"{SOURCE_REVISION}/scripts/xview2_dinov3_upernet_RESULTS.md"
    )
    provenance = {
        "schemaVersion": 1,
        "checkpointSha256": evidence["sha256"],
        "backboneConfigSha256": config_sha,
        "backboneConfigSource": (
            f"https://huggingface.co/{BACKBONE_REPOSITORY}/blob/"
            f"{config_record['revision']}/config.json; "
            + config_record["exportMethod"]
        ),
        "labelGrouping": "any",
        "labelMapping": groupings[0]["any"],
        "labelGroupingSource": (
            results_url + "; bda/xview2.py GROUPINGS at the same revision; "
            "embedded ModelCheckpoint original-any run paths in the "
            "user-supplied artifact, not its download filename alone."
        ),
        "checkpointTrainingEvidence": evidence["training"],
        "sourceRevision": SOURCE_REVISION,
        "pinnedSourceHashes": REFERENCE_HASHES,
        "configurationExport": {
            key: value
            for key, value in config_record.items()
            if not key.endswith("Path")
        },
        "limitations": [
            "Embedded callback metadata is corroborating provenance, "
            "not an independently signed training record.",
            "The supplied artifact records epoch 12 and step 8190. "
            "No claim is made that it is the final 15-epoch artifact or "
            "that the results document's metrics were measured on these bytes.",
        ],
    }
    path = (
        asset_directory() / f"original-any-{config_sha[:12]}-provenance.json"
    )
    write_recipe(path, provenance, asset_directory())
    return {"provenancePath": str(path), "provenance": provenance}


def fetch_backbone_config():
    """Download authorized official JSON, then export defaults from pinned HF code.

    token=True uses the existing credential through the normal Hub client.
    No token is returned, printed or written into configuration/provenance.
    No alternate host, ungated mirror, or tensor-inferred settings are used.
    """
    import transformers
    from huggingface_hub import HfApi, hf_hub_download
    from transformers import DINOv3ViTConfig

    if transformers.__version__ != "5.5.4":
        raise RuntimeError("Config export requires transformers==5.5.4")
    info = HfApi(token=True).model_info(BACKBONE_REPOSITORY, revision="main")
    revision = info.sha
    if (
        not isinstance(revision, str)
        or len(revision) != 40
        or any(char not in "0123456789abcdef" for char in revision)
    ):
        raise ValueError("Hub did not resolve a commit SHA")
    directory = asset_directory()
    snapshot = directory / "hf-config" / revision
    official = Path(
        hf_hub_download(
            repo_id=BACKBONE_REPOSITORY,
            filename="config.json",
            revision=revision,
            token=True,
            local_dir=snapshot,
        )
    )
    raw, official_sha = read_json_asset(official)
    if raw.get("model_type") != "dinov3_vit" or raw.get("auto_map"):
        raise ValueError("Expected the official built-in DINOv3 ViT config")
    config = DINOv3ViTConfig.from_dict(raw)
    expanded = json.loads(config.to_json_string(use_diff=False))
    export = snapshot / "config.expanded.json"
    write_recipe(export, expanded, directory)
    _, expanded_sha = read_json_asset(export)
    record = {
        "repository": BACKBONE_REPOSITORY,
        "revision": revision,
        "officialConfigPath": str(official),
        "officialConfigSha256": official_sha,
        "expandedConfigPath": str(export),
        "expandedConfigSha256": expanded_sha,
        "exportMethod": (
            "DINOv3ViTConfig.from_dict(official_json)."
            "to_json_string(use_diff=False); sorted JSON with trailing newline"
        ),
        "transformersVersion": transformers.__version__,
        "officialDeclaredTransformersVersion": raw.get("transformers_version"),
        "addedDefaultFields": sorted(set(expanded) - set(raw)),
        "accessMethod": "HfApi/hf_hub_download authenticated; pinned commit",
    }
    write_recipe(snapshot / "config.provenance.json", record, directory)
    return record


def asset_directory():
    directory = ROOT / "localtmp" / "pretrained-assets"
    if directory.resolve() != directory:
        raise ValueError("Asset directory must not redirect via symlinks")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def stage_checkpoint(download=False):
    directory = asset_directory()
    path = directory / "xview2_dinov3_upernet_any-last.ckpt"
    if path.is_symlink():
        raise ValueError("Checkpoint must not be a symlink")
    if download and not path.exists():
        request = urllib.request.Request(URL, headers={"If-Match": ETAG})
        created = False
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                if (
                    int(response.headers["Content-Length"]) != SIZE
                    or response.headers["ETag"].strip('"') != ETAG.strip('"')
                    or response.headers["Content-MD5"] != MD5
                ):
                    raise ValueError("Authorized checkpoint identity changed")
                with path.open("xb") as dst:
                    created = True
                    while chunk := response.read(1024 * 1024):
                        dst.write(chunk)
        except Exception:
            if created:
                path.unlink(missing_ok=True)
            raise
    return path


def inspect_checkpoint(path):
    """Verify the authorized bytes before restricted metadata inspection."""
    sha256, md5 = hashlib.sha256(), hashlib.md5(usedforsecurity=False)
    with path.open("rb") as src:
        while chunk := src.read(1024 * 1024):
            sha256.update(chunk)
            md5.update(chunk)
    if (
        path.stat().st_size != SIZE
        or base64.b64encode(md5.digest()).decode() != MD5
        or sha256.hexdigest() != SHA256
    ):
        raise ValueError(
            "Checkpoint size/digest differs from authorized source"
        )
    import torch
    from packaging.version import Version

    # CVE-2026-24747 applies to restricted loading too; never fall back.
    if Version(torch.__version__.split("+")[0]) < Version("2.10.0"):
        raise RuntimeError(
            "Restricted loading requires torch>=2.10.0 (CVE-2026-24747)"
        )
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    hparams = checkpoint["hyper_parameters"]
    callbacks = []
    for values in checkpoint.get("callbacks", {}).values():
        if not isinstance(values, dict) or "dirpath" not in values:
            continue
        score = values.get("best_model_score")
        callbacks.append(
            {
                "runDirectory": relative_run_path(values.get("dirpath")),
                "bestModelPath": relative_run_path(
                    values.get("best_model_path")
                ),
                "lastModelPath": relative_run_path(
                    values.get("last_model_path")
                ),
                "bestModelScore": None if score is None else float(score),
            }
        )
    return {
        "sha256": sha256.hexdigest(),
        "sizeBytes": path.stat().st_size,
        "restrictedLoad": True,
        "hyperParameters": {
            key: hparams.get(key)
            for key in ("model", "backbone", "in_channels", "num_classes")
        },
        "modelTensorCount": sum(
            key.startswith("model.") for key in checkpoint["state_dict"]
        ),
        "labelGrouping": None,  # Never inferred from this checkpoint's name.
        "training": {
            "epoch": checkpoint.get("epoch"),
            "globalStep": checkpoint.get("global_step"),
            "lightningVersion": checkpoint.get("pytorch-lightning_version"),
            "checkpointCallbacks": callbacks,
        },
    }


def read_json_asset(path):
    """Return plain JSON and its byte identity; no YAML/custom object loader."""
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("Configuration/provenance exceeds 1 MiB")
    content = path.read_bytes()
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("Configuration/provenance must be a JSON object")
    json.dumps(value, allow_nan=False)
    return value, hashlib.sha256(content).hexdigest()


def validate_provenance(provenance, checkpoint_sha256, config_sha256):
    expected = {
        "schemaVersion": 1,
        "checkpointSha256": checkpoint_sha256,
        "backboneConfigSha256": config_sha256,
        "labelGrouping": "any",
        "labelMapping": [0, 1, 2, 2, 2],
    }
    for key, value in expected.items():
        if provenance.get(key) != value:
            raise ValueError(f"Provenance {key} is missing or mismatched")
    for key in ("backboneConfigSource", "labelGroupingSource"):
        value = provenance.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Provenance requires a documented {key}")


def validate_model(
    checkpoint, config, checkpoint_sha, config_sha, device, size
):
    """Use the deployed strict loader, then prove finite logits on the recipe grid."""
    import torch
    import transformers

    sys.path.insert(0, str(ROOT / "docker" / "training" / "code"))
    from bda.dinov3_upernet import REQUIRED_CONFIG_FIELDS
    from inference_dinov3 import load_model

    target = torch.device(device)
    if target.type not in ("cpu", "cuda"):
        raise ValueError("Validation device must be cpu or cuda:<index>")
    if target.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("Requested CUDA is unavailable; no CPU fallback")
    model = load_model(checkpoint, config, checkpoint_sha, config_sha, target)
    with torch.inference_mode(), torch.autocast(
        device_type=target.type,
        dtype=torch.float16,
        enabled=target.type == "cuda",
    ):
        output = model(torch.zeros(1, 3, size, size, device=target))
    if tuple(output.shape) != (1, 3, size, size):
        raise ValueError("Model returned an unexpected logit shape")
    if not torch.isfinite(output).all().item():
        raise ValueError("Model returned non-finite logits")
    return {
        "restrictedCheckpointLoad": True,
        "minimumTorchVersion": "2.10.0",
        "restrictedLoaderAdvisory": "CVE-2026-24747",
        "strictStateDict": True,
        "finiteForward": True,
        "forwardShape": list(output.shape),
        "device": str(target),
        "precision": "cuda_fp16_autocast" if target.type == "cuda" else "fp32",
        "torchVersion": str(torch.__version__),
        "transformersVersion": transformers.__version__,
        "transformersSecurityScope": {
            "advisory": "CVE-2026-9856",
            "affectedPath": (
                "PreTrainedTokenizerBase/ProcessorMixin.save_pretrained "
                "chat_template filenames"
            ),
            "runtimeReachability": (
                "Not used by this config-only DINOv3 constructor/export: "
                "no tokenizer/processor load or save_pretrained calls."
            ),
            "reviewRequiredIfScopeChanges": True,
        },
        "backboneConfig": {
            key: getattr(model.backbone.vit.config, key)
            for key in sorted(REQUIRED_CONFIG_FIELDS)
        },
    }


def blocked(reason, detail, checkpoint=None):
    return {
        "status": "blocked",
        "reason": reason,
        "detail": detail,
        "checkpoint": checkpoint,
        # Deliberately no baseModelName, cataloguedByUser or inferenceSpec:
        # CatalogModel.model_validate_json must reject this diagnostic.
    }


def prepare_recipe(
    checkpoint,
    backbone_config=None,
    provenance_file=None,
    catalogued_by=None,
    name="xview2-dinov3-upernet-any",
    device="cuda:0",
    patch_size=512,
    padding=64,
):
    evidence = None
    stage = "checkpoint_validation"
    try:
        evidence = inspect_checkpoint(checkpoint)
        missing = [
            key
            for key, value in {
                "authorized_backbone_config": backbone_config,
                "training_and_config_provenance": provenance_file,
                "catalogued_by": catalogued_by,
            }.items()
            if value is None or value == ""
        ]
        if missing:
            return blocked("missing_inputs", missing, evidence)
        stage = "config_and_provenance_validation"
        _, config_sha = read_json_asset(backbone_config)
        provenance, provenance_sha = read_json_asset(provenance_file)
        validate_provenance(provenance, evidence["sha256"], config_sha)
        if (
            type(patch_size) is not int
            or not 32 <= patch_size <= 4096
            or patch_size % 16
            or type(padding) is not int
            or not 0 <= padding < patch_size / 2
        ):
            raise ValueError("Invalid recipe patch size/padding")
        if not name.strip() or not catalogued_by.strip():
            raise ValueError("Name and catalogued-by must not be blank")

        stage = "strict_model_validation"
        validation = validate_model(
            checkpoint,
            backbone_config,
            evidence["sha256"],
            config_sha,
            device,
            patch_size,
        )
        stage = "catalog_schema_validation"
        sys.path.insert(0, str(ROOT / "hastelib" / "src"))
        from hastegeo.core.models.training import CatalogModel

        checkpoint_target = (
            f"model-catalog/assets/{evidence['sha256']}/model.ckpt"
        )
        config_target = f"model-catalog/assets/{config_sha}/config.json"
        entry = CatalogModel(
            baseModelName=name,
            cataloguedByUser=catalogued_by,
            source="external",
            capabilities=["inference"],
            checkpointFilePath=checkpoint_target,
            description="Post-event RGB8 xView2 DINOv3 UPerNet; any damage.",
            inferenceSpec={
                "schemaVersion": 1,
                "adapter": "dinov3_upernet",
                "checkpointFilePath": checkpoint_target,
                "checkpointSha256": evidence["sha256"],
                "backboneConfigPath": config_target,
                "backboneConfigSha256": config_sha,
                "backbone": evidence["hyperParameters"]["backbone"],
                "labelGrouping": provenance["labelGrouping"],
                "sourceRevision": SOURCE_REVISION,
                "sourceUrl": URL,
                "inputKind": "rgb",
                "numChannels": 3,
                "normalizationMeans": [0.485, 0.456, 0.406],
                "normalizationStds": [0.229, 0.224, 0.225],
                "patchSize": patch_size,
                "padding": padding,
                "batchSize": 8,
                "numWorkers": 2,
                "prefetchFactor": 2,
            },
            additionalInfo={
                "sourceCheckpoint": {
                    "url": URL,
                    "etag": ETAG.strip('"'),
                    "contentMd5": MD5,
                    "sizeBytes": evidence["sizeBytes"],
                },
                "assetValidation": validation,
                "provenance": provenance,
                "provenanceSha256": provenance_sha,
                "provenanceVerification": (
                    "Asset bindings verified locally. Training/config source "
                    "evidence is recorded in provenance; embedded checkpoint "
                    "metadata is not an independently signed training record."
                ),
                "sourceCode": {
                    "repository": "microsoft/building-damage-assessment",
                    "revision": SOURCE_REVISION,
                    "license": "MIT",
                    "copyright": "Copyright (c) Microsoft Corporation.",
                },
                "backboneLicense": {
                    "notice": (
                        "Meta DINOv3 assets retain the separate DINOv3 License; "
                        "the runtime's MIT license does not relicense them."
                    ),
                    "url": (
                        "https://ai.meta.com/resources/models-and-libraries/"
                        "dinov3-downloads/"
                    ),
                },
            },
        )
        # No timestamps or local paths: repeated preparation is deterministic.
        return entry.model_dump(mode="json", exclude_none=True)
    except Exception as error:
        return blocked(stage, f"{type(error).__name__}: {error}", evidence)


def write_recipe(path, document, directory):
    """Optionally materialize an accepted recipe, without clobber or redirection."""
    if document.get("status") == "blocked":
        raise ValueError("A blocked result is not a catalog recipe")
    if (
        not path.resolve().is_relative_to(directory.resolve())
        or path.is_symlink()
        or path.suffix != ".json"
    ):
        raise ValueError("Recipe output must be JSON inside pretrained-assets")
    payload = (
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError("Refusing to overwrite a different recipe")
        return
    with path.open("xb") as stream:
        stream.write(payload)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument(
        "--fetch-backbone-config",
        action="store_true",
        help="Fetch/export authorized pinned config only; emit its provenance",
    )
    parser.add_argument("--backbone-config", type=Path)
    parser.add_argument(
        "--record-original-provenance",
        action="store_true",
        help="Corroborate this checkpoint's original-any run and write provenance",
    )
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--catalogued-by")
    parser.add_argument("--name", default="xview2-dinov3-upernet-any")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--patch-size", type=int, default=512)
    parser.add_argument("--padding", type=int, default=64)
    parser.add_argument("--recipe-output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.fetch_backbone_config:
            document = fetch_backbone_config()
            print(json.dumps(document, indent=2, sort_keys=True))
            return 0
        if args.record_original_provenance:
            if args.backbone_config is None:
                raise ValueError("--backbone-config is required")
            document = original_any_provenance(args.backbone_config)
            print(json.dumps(document, indent=2, sort_keys=True))
            return 0
        document = prepare_recipe(
            stage_checkpoint(args.download),
            args.backbone_config,
            args.provenance,
            args.catalogued_by,
            args.name,
            args.device,
            args.patch_size,
            args.padding,
        )
        if args.recipe_output and document.get("status") != "blocked":
            write_recipe(args.recipe_output, document, asset_directory())
    except Exception as error:
        document = blocked(
            "asset_preparation", f"{type(error).__name__}: {error}"
        )
    print(json.dumps(document, indent=2, sort_keys=True, allow_nan=False))
    return 2 if document.get("status") == "blocked" else 0


if __name__ == "__main__":
    sys.exit(main())
