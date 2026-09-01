# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Seed a synthetic HASTE project for perf baselining (Phase 0).

Writes a project with ``--layers`` image layers, each with ``--models`` models,
plus per-layer LABELS + VALIDATION records and per-model MODEL_ARTIFACTS, using the
real ``MetadataProcessor`` against whatever backend the environment is configured
for (defaults to the ``local`` filesystem layer, so no Azure/Docker is required).

Usage (local FS, no infra):
    METADATA_STORAGE_TYPE=local DATA_PATH=/tmp/haste-bench \
    PYTHONPATH=hastelib/src \
    python spec/features/perf-layer-loading/tools/seed_synthetic_project.py \
        --project-id 00000000-0000-4000-8000-000000000050 --layers 50 --models 5

The project id is a canonical GUID so the same seed is reusable against the real
HTTP API (which validates ``projectId`` as a GUID).
"""
import argparse
import uuid

from hastegeo.core.config import Config
from hastegeo.core.processors.metadata import MetadataProcessor

# Fixed base date so seeds are deterministic (no wall-clock dependency).
_BASE_DATE = "2026-01-01T00:00:00Z"


def _iso(seq):
    # Distinct, sortable creationDate values without importing time.
    return f"2026-01-{(seq % 27) + 1:02d}T00:00:00Z"


def _mp(data_type, project_id):
    return MetadataProcessor(data_type=data_type, partition_key=project_id)


def seed(project_id, layers, models, labels_per_layer, validation_per_layer,
         with_labels_url):
    types = Config.get_metadata_types()

    _mp(types.PROJECT.value, project_id).save(
        project_id,
        {
            "projectId": project_id,
            "name": f"Perf baseline {layers}x{models}",
            "description": "Synthetic project for perf-layer-loading Phase 0.",
            "creationDate": _BASE_DATE,
        },
    )

    model_total = 0
    for li in range(layers):
        layer_id = f"layer-{li:04d}"
        _mp(types.IMAGELAYER.value, project_id).save(
            layer_id,
            {
                "imageLayerId": layer_id,
                "projectId": project_id,
                "name": f"Layer {li}",
                "creationDate": _iso(li),
                "userId": "bench@example.com",
                "status": "Processed",
                "statusMessage": "",
                "currentStep": 10,
                "totalSteps": 10,
                "progressPct": 100,
            },
        )

        # One label project per layer, with N labels.
        _mp(types.LABELS.value, project_id).save(
            f"labelproj-{li:04d}",
            {
                "labelprojectId": f"labelproj-{li:04d}",
                "imageLayerId": layer_id,
                "labels": [{"id": j} for j in range(labels_per_layer)],
            },
        )

        # Validation record keyed by imageLayerId.
        _mp(types.VALIDATION.value, project_id).save(
            layer_id,
            {"imageLayerId": layer_id,
             "labels": {str(j): {"id": j} for j in range(validation_per_layer)}},
        )

        for mi in range(models):
            model_id = f"{li:04d}{mi:02d}"
            # Fields below mirror what the UI's ModelRow / ModelResultsButton read
            # so the real React tree renders without crashing (e.g. inferenceJobs
            # must be an array). This enriches the record but does NOT change the
            # GetProjectDetails round-trip count.
            model = {
                "modelId": model_id,
                "imageLayerId": layer_id,
                "projectId": project_id,
                "name": f"Model {li}-{mi}",
                "userId": "bench@example.com",
                "modelType": "segmentation",
                "status": "Trained",
                "statusMessage": "",
                "trainDate": _iso(mi),
                "creationDate": _iso(mi),
                "labelsCount": 100,
                "currentStep": 10,
                "totalSteps": 10,
                "progressPct": 100,
                "inferenceJobs": [],
                "inferenceStatus": None,
                "inferenceStatusMessage": "",
                "inferenceCurrentStep": 0,
                "inferenceTotalSteps": 0,
                "inferenceProgressPct": 0,
                "labelsUrl": None,
                "artifacts": None,
            }
            if with_labels_url:
                model["labelsUrl"] = f"https://example/{model_id}.geojson"
            _mp(types.MODEL.value, project_id).save(model_id, model)

            _mp(types.MODEL_ARTIFACTS.value, project_id).save(
                model_id,
                {"modelId": model_id, "metrics": {"iou": 0.5, "f1": 0.6}},
            )
            model_total += 1

    return model_total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-id", default=str(uuid.uuid4()))
    ap.add_argument("--layers", type=int, default=50)
    ap.add_argument("--models", type=int, default=5)
    ap.add_argument("--labels-per-layer", type=int, default=20)
    ap.add_argument("--validation-per-layer", type=int, default=10)
    ap.add_argument(
        "--with-labels-url",
        action="store_true",
        help="Seed models with labelsUrl set (skips the per-model TRAIN_LABELS "
        "export round-trip; omit to reproduce the worst-case N+1).",
    )
    args = ap.parse_args()

    total = seed(
        args.project_id,
        args.layers,
        args.models,
        args.labels_per_layer,
        args.validation_per_layer,
        args.with_labels_url,
    )
    print(
        f"Seeded project {args.project_id}: {args.layers} layers, "
        f"{total} models, with_labels_url={args.with_labels_url}"
    )


if __name__ == "__main__":
    main()
