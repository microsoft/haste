# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Phase 0 baseline: measure GetProjectDetails logical data-layer calls.

Seeds synthetic projects (small / medium / large) into a temporary local-FS
backend and replays the *exact* read sequence of the ``GetProjectDetails`` handler
(``api/hastefuncapi/function_app.py`` lines ~534-638) with perf instrumentation on.

Reports, per size, the number of logical data-layer calls plus a per-op breakdown
and a local-FS wall-clock (for relative comparison only; absolute latency p50/p95
must be measured against the running Azure/Docker stack via bench_api_http.py).

Run:
    PYTHONPATH=hastelib/src \
    python spec/features/perf-layer-loading/tools/phase0_baseline.py
"""
import json
import os
import statistics
import sys
import tempfile

# Force the local filesystem backend for a self-contained, infra-free baseline.
os.environ.setdefault("METADATA_STORAGE_TYPE", "local")

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))  # for seed import
from seed_synthetic_project import seed  # noqa: E402

from hastegeo.core.config import Config  # noqa: E402
from hastegeo.core.processors.metadata import MetadataProcessor  # noqa: E402
from hastegeo.core.utils import perf  # noqa: E402

SIZES = [
    ("small", 5, 2),
    ("medium", 20, 5),
    ("large", 50, 5),
]
REPEATS = 5


def _mp(data_type, project_id):
    return MetadataProcessor(data_type=data_type, partition_key=project_id)


def replay_get_project_details(project_id, include_models=True):
    """Faithful replay of the GetProjectDetails read+assemble sequence.

    Mirrors api/hastefuncapi/function_app.py:534-638. Returns the serialized
    payload length so we can report response size alongside round-trips.
    """
    types = Config.get_metadata_types()

    project = _mp(types.PROJECT.value, project_id).load(project_id)
    image_layers = _mp(types.IMAGELAYER.value, project_id).load_all_from_partition()
    models = []
    if include_models:
        models = _mp(types.MODEL.value, project_id).load_all_from_partition()

    for image_layer in image_layers:
        image_layer_id = image_layer["imageLayerId"]
        if include_models:
            match_models = [
                m for m in models if m["imageLayerId"] == image_layer_id
            ]
            match_models.sort(key=lambda x: x["creationDate"], reverse=True)
            for model in match_models:
                try:
                    model["artifacts"] = _mp(
                        types.MODEL_ARTIFACTS.value, project_id
                    ).load(model["modelId"])
                except FileNotFoundError:
                    model["artifacts"] = None
                try:
                    if not model.get("labelsUrl"):
                        model["labelsUrl"] = _mp(
                            types.TRAIN_LABELS.value, project_id
                        ).export(key=model["modelId"], data_format="geojson")
                except FileNotFoundError:
                    model["labelsUrl"] = None
            image_layer["models"] = match_models
            image_layer["modelCount"] = len(match_models)

        label_projects = _mp(
            types.LABELS.value, project_id
        ).load_all_from_partition()
        match = next(
            (lp for lp in label_projects
             if lp["imageLayerId"] == image_layer_id),
            None,
        )
        if match is not None and match.get("labels") is not None:
            image_layer["labelProjectCount"] = len(match["labels"])

        try:
            validation = _mp(types.VALIDATION.value, project_id).load(
                image_layer_id
            )
            image_layer["validationLabelCount"] = len(
                validation.get("labels") or {}
            )
        except FileNotFoundError:
            image_layer["validationLabelCount"] = 0

    project["imageLayer"] = image_layers
    project["imageLayerCount"] = len(image_layers)
    project["imageLayer"].sort(key=lambda x: x["creationDate"], reverse=True)
    return len(json.dumps(project))


def run():
    rows = []
    for name, layers, models_per in SIZES:
        with tempfile.TemporaryDirectory(prefix=f"haste-bench-{name}-") as d:
            os.environ["DATA_PATH"] = d
            project_id = f"00000000-0000-4000-8000-{layers:06d}{models_per:06d}"
            total_models = seed(
                project_id, layers, models_per,
                labels_per_layer=20, validation_per_layer=10,
                with_labels_url=False,
            )

            walls, calls, payload, ops = [], None, None, None
            for _ in range(REPEATS):
                counter = perf.begin(True)
                import time
                t0 = time.perf_counter()
                payload = replay_get_project_details(project_id)
                walls.append((time.perf_counter() - t0) * 1000.0)
                calls = counter.calls
                ops = {k: v["calls"] for k, v in counter.by_op.items()}
                perf.end()

            rows.append({
                "size": name, "layers": layers, "models_per": models_per,
                "total_models": total_models, "data_layer_calls": calls,
                "ops": ops, "payload_bytes": payload,
                "wall_p50_ms": round(statistics.median(walls), 1),
                "wall_p95_ms": round(max(walls), 1),
            })

    hdr = (f"{'size':7} {'layers':6} {'mdl/l':5} {'data_calls':10} "
           f"{'payload_kb':10} {'localfs_p50ms':13} {'ops (by type)'}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r['size']:7} {r['layers']:<6} {r['models_per']:<5} "
              f"{r['data_layer_calls']:<10} {r['payload_bytes']/1024:<10.1f} "
              f"{r['wall_p50_ms']:<13} {r['ops']}")
    print()
    for r in rows:
        L, M = r["layers"], r["models_per"]
        print(f"  {r['size']}: data_layer_calls={r['data_layer_calls']}  "
              f"formula 3 + L*(2M+2) = {3 + L * (2 * M + 2)}")


if __name__ == "__main__":
    run()
