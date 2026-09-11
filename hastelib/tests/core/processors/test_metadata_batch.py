# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Tests for the batch metadata primitives added in the perf-layer-loading work:
``MetadataProcessor.load_map`` / ``load_filtered`` / ``list_keys`` / ``build_url``.

Runs against the local filesystem backend so no Azure/Azurite is required.
"""
import importlib
from unittest.mock import Mock

import pytest


@pytest.fixture()
def local_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("METADATA_STORAGE_TYPE", "local")
    monkeypatch.setenv("DATA_PATH", str(tmp_path))
    # Config reads env at construction; import fresh each test.
    metadata = importlib.import_module("hastegeo.core.processors.metadata")
    return metadata.MetadataProcessor


def _seed(MetadataProcessor, partition):
    for i in range(5):
        MetadataProcessor("model", partition).save(
            f"m{i}",
            {"modelId": f"m{i}", "imageLayerId": f"layer-{i % 2}"},
        )


def test_list_keys_returns_all_identifiers(local_metadata):
    MetadataProcessor = local_metadata
    _seed(MetadataProcessor, "p1")
    keys = set(MetadataProcessor("model", "p1").list_keys())
    assert keys == {"m0", "m1", "m2", "m3", "m4"}


def test_partition_scan_excludes_longer_metadata_type(local_metadata):
    MetadataProcessor = local_metadata
    MetadataProcessor("model", "prefix").save("1", {"modelId": "1"})
    MetadataProcessor("model_catalog", "prefix").save(
        "index", {"modelCatalog": []}
    )

    models = MetadataProcessor("model", "prefix")

    assert models.load_all_from_partition() == [{"modelId": "1"}]
    assert models.list_keys() == ["1"]


def test_load_map_parallel_matches_sequential(local_metadata):
    MetadataProcessor = local_metadata
    _seed(MetadataProcessor, "p2")
    mp = MetadataProcessor("model", "p2")
    keys = mp.list_keys()

    mapped = mp.load_map(keys, max_workers=4)
    sequential = {k: mp.load(k) for k in keys}
    assert mapped == sequential


def test_load_map_missing_key_is_none(local_metadata):
    MetadataProcessor = local_metadata
    _seed(MetadataProcessor, "p3")
    mp = MetadataProcessor("model", "p3")
    result = mp.load_map(["m0", "does-not-exist"])
    assert result["m0"]["modelId"] == "m0"
    assert result["does-not-exist"] is None


def test_load_map_empty(local_metadata):
    MetadataProcessor = local_metadata
    assert MetadataProcessor("model", "p4").load_map([]) == {}


def test_load_map_rejects_invalid_worker_count(local_metadata):
    MetadataProcessor = local_metadata
    _seed(MetadataProcessor, "invalid-workers")

    with pytest.raises(ValueError, match="max_workers"):
        MetadataProcessor("model", "invalid-workers").load_map(
            ["m0"], max_workers=0
        )


def test_load_map_deduplicates_keys(local_metadata, mocker):
    MetadataProcessor = local_metadata
    _seed(MetadataProcessor, "duplicate-keys")
    processor = MetadataProcessor("model", "duplicate-keys")
    load = mocker.spy(processor, "load")

    result = processor.load_map(["m0", "m0"], max_workers=2)

    assert result["m0"]["modelId"] == "m0"
    load.assert_called_once_with("m0", data_format="json")


def test_load_map_prefers_backend_native_batch(local_metadata):
    MetadataProcessor = local_metadata
    processor = MetadataProcessor.__new__(MetadataProcessor)
    processor.data_type = "model"
    processor.storage = Mock()
    processor.storage.supports_load_map.return_value = True
    processor.storage.load_map.return_value = {
        "m0": {"modelId": "m0"},
        "missing": None,
    }

    result = processor.load_map(["m0", "m0", "missing"])

    assert result == {"m0": {"modelId": "m0"}, "missing": None}
    processor.storage.load_map.assert_called_once_with(
        identifiers=["m0", "missing"],
        data_type="model",
        data_format="json",
        max_workers=8,
    )


def test_native_load_map_rejects_invalid_worker_count(local_metadata):
    MetadataProcessor = local_metadata
    processor = MetadataProcessor.__new__(MetadataProcessor)
    processor.data_type = "model"
    processor.storage = Mock()
    processor.storage.supports_load_map.return_value = True

    with pytest.raises(ValueError, match="max_workers"):
        processor.load_map(["m0"], max_workers=0)

    processor.storage.load_map.assert_not_called()


def test_load_filtered_by_field(local_metadata):
    MetadataProcessor = local_metadata
    _seed(MetadataProcessor, "p5")
    matched = MetadataProcessor("model", "p5").load_filtered(
        {"imageLayerId": "layer-0"}
    )
    assert {m["modelId"] for m in matched} == {"m0", "m2", "m4"}


def test_load_filtered_rejects_empty_predicate(local_metadata):
    MetadataProcessor = local_metadata

    with pytest.raises(ValueError, match="non-empty"):
        MetadataProcessor("model", "empty-predicate").load_filtered({})


def test_load_filtered_does_not_treat_missing_field_as_none(local_metadata):
    MetadataProcessor = local_metadata
    processor = MetadataProcessor("model", "missing-field")
    processor.save("missing", {"modelId": "missing"})
    processor.save("explicit", {"modelId": "explicit", "status": None})

    matched = processor.load_filtered({"status": None})

    assert [record["modelId"] for record in matched] == ["explicit"]


def test_load_map_counts_round_trips_across_threads(local_metadata):
    MetadataProcessor = local_metadata
    _seed(MetadataProcessor, "p6")
    perf = importlib.import_module("hastegeo.core.utils.perf")
    mp = MetadataProcessor("model", "p6")
    keys = mp.list_keys()

    counter = perf.begin(True)
    mp.load_map(keys, max_workers=4)
    perf.end()
    # Each threaded load records against the shared counter (context bound).
    assert counter.calls >= len(keys)
