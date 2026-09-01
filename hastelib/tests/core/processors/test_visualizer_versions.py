# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Viewer payload tests for per-version prediction rendering.

Switching versions in the results viewer must be nothing more than the
same renderer pointed at a different sidecar, so the payload has to:

* pin ``predictionAttrsUrl`` to the SELECTED version rather than always
  handing back the model-level (raw) sidecar;
* judge readiness against that version's sidecar, so a version saved
  before per-version sidecars existed reports "still preparing" instead
  of drawing the raw model's classes under an edited version's name;
* state whether the selection is the newest version, because version
  selection changes the map only — the Assessment and Validation reports
  keep reading the newest version, and the UI must be able to say when
  the two diverge without recomputing it.
"""

import unittest
from urllib.parse import parse_qs, urlparse

from hastegeo.core.config import Config
from hastegeo.core.models.projects import ImageLayer, Model, Project
from hastegeo.core.processors.visualizer import (
    REASON_PREPARING,
    PredictionInfo,
    build_visualizer_results,
    model_artifact_url,
)

STATUSES = Config.get_status_types()
PROCESSED = STATUSES.COMPLETED.value

TITILER = "https://titiler.example.net/"
PROJECT_ID = "11111111-1111-1111-1111-111111111111"
LAYER_ID = "22222222-2222-2222-2222-222222222222"
GPKG_URL = "https://acct.blob/c/hash/predicted_damage_m.gpkg?sas"
ATTRS_URL = "https://acct.blob/c/hash/prediction_attrs_5557.json?sas"
LAYER_PMTILES = "https://acct.blob/c/hash/footprints_layer.pmtiles?sas"


def _project() -> Project:
    return Project(
        projectId=PROJECT_ID,
        name="Hurricane Test",
        eventDate="2026-01-02T00:00:00Z",
    )


def _layer(**overrides) -> ImageLayer:
    data = {
        "imageLayerId": LAYER_ID,
        "projectId": PROJECT_ID,
        "postEventProcessedImageryUrl": "https://acct.blob/c/h/post.tif?s",
        "buildingFootprintsUrl": "https://acct.blob/c/hash/fp.gpkg?sas",
        "footprintPmtilesUrl": LAYER_PMTILES,
    }
    data.update(overrides)
    return ImageLayer(**data)


def _edited(version: int, attrs: bool = True) -> dict:
    return {
        "version": version,
        "gpkgUrl": f"https://acct.blob/c/hash/edited_v{version}.gpkg?sas",
        "predictionAttrsUrl": (
            f"https://acct.blob/c/hash/attrs_v{version}.json?sas"
            if attrs
            else None
        ),
        "createdAt": "2026-08-21T05:10:48+00:00",
        "editedCount": 5,
    }


def _model(*edits, **overrides) -> Model:
    data = {
        "modelId": "5557",
        "projectId": PROJECT_ID,
        "imageLayerId": LAYER_ID,
        "modelType": "trained",
        "status": PROCESSED,
        "inferenceStatus": PROCESSED,
        "gpkgUrl": GPKG_URL,
        "predictionAttrsUrl": ATTRS_URL,
        "predictionTilesStatus": PROCESSED,
        "editedPredictions": list(edits),
    }
    data.update(overrides)
    return Model(**data)


def _build(model: Model, **kwargs):
    return build_visualizer_results(
        project=_project(),
        image_layer=_layer(),
        model=model,
        titiler_endpoint=TITILER,
        study_area=[],
        **kwargs,
    )


def _params(url: str) -> dict:
    return {
        key: values[0] for key, values in parse_qs(urlparse(url).query).items()
    }


class TestVersionPinnedAttrsUrl(unittest.TestCase):
    def test_raw_selection_has_no_version_parameter(self):
        visualizer = _build(
            _model(), predictions=PredictionInfo(attrs_url=ATTRS_URL)
        )

        params = _params(visualizer.predictionAttrsUrl)
        self.assertEqual(params["kind"], "prediction_attrs")
        self.assertEqual(params["modelId"], "5557")
        self.assertNotIn("version", params)

    def test_selected_version_is_pinned_on_the_route(self):
        model = _model(_edited(1), _edited(2))

        visualizer = _build(
            model,
            predictions=PredictionInfo(
                version=2,
                attrs_url="https://acct.blob/c/hash/attrs_v2.json?sas",
            ),
        )

        params = _params(visualizer.predictionAttrsUrl)
        self.assertEqual(params["version"], "2")
        self.assertEqual(params["kind"], "prediction_attrs")

    def test_older_version_gets_its_own_route(self):
        model = _model(_edited(1), _edited(2))

        first = _build(
            model,
            predictions=PredictionInfo(
                version=1,
                attrs_url="https://acct.blob/c/hash/attrs_v1.json?sas",
                is_latest=False,
            ),
        )
        second = _build(
            model,
            predictions=PredictionInfo(
                version=2,
                attrs_url="https://acct.blob/c/hash/attrs_v2.json?sas",
            ),
        )

        self.assertNotEqual(
            first.predictionAttrsUrl, second.predictionAttrsUrl
        )
        self.assertEqual(_params(first.predictionAttrsUrl)["version"], "1")

    def test_route_builder_omits_an_absent_version(self):
        self.assertNotIn(
            "version",
            model_artifact_url(PROJECT_ID, "5557", "prediction_attrs"),
        )
        self.assertIn(
            "version=3",
            model_artifact_url(
                PROJECT_ID, "5557", "prediction_attrs", version=3
            ),
        )


class TestReadinessFollowsTheSelectedVersion(unittest.TestCase):
    def test_version_without_a_sidecar_reports_preparing(self):
        # Models 0448/5553 in dev: an edited version exists, its sidecar
        # does not. Falling back to the model-level sidecar here would
        # draw the RAW classes while claiming to show the edit.
        model = _model(_edited(1, attrs=False))

        visualizer = _build(model, predictions=PredictionInfo(version=1))

        self.assertFalse(visualizer.predictionsReady)
        self.assertEqual(
            visualizer.predictionsReadiness.reason, REASON_PREPARING
        )
        self.assertFalse(visualizer.predictionsReadiness.attrsReady)
        self.assertIsNone(visualizer.predictionAttrsUrl)

    def test_version_with_a_sidecar_is_ready(self):
        model = _model(_edited(1))

        visualizer = _build(
            model,
            predictions=PredictionInfo(
                version=1,
                attrs_url="https://acct.blob/c/hash/attrs_v1.json?sas",
            ),
        )

        self.assertTrue(visualizer.predictionsReady)
        self.assertTrue(visualizer.predictionsReadiness.attrsReady)
        self.assertIsNotNone(visualizer.predictionAttrsUrl)

    def test_raw_selection_still_uses_the_model_level_sidecar(self):
        # An unbuilt model-level sidecar is still "preparing" even when
        # no version is selected.
        visualizer = _build(_model(predictionAttrsUrl=None))

        self.assertFalse(visualizer.predictionsReadiness.attrsReady)
        self.assertIsNone(visualizer.predictionAttrsUrl)


class TestVersionIsLatestFlag(unittest.TestCase):
    def test_defaults_to_true_for_an_unedited_model(self):
        visualizer = _build(
            _model(), predictions=PredictionInfo(attrs_url=ATTRS_URL)
        )

        self.assertTrue(visualizer.predictionVersionIsLatest)

    def test_false_when_an_older_version_is_pinned(self):
        model = _model(_edited(1), _edited(2))

        visualizer = _build(
            model,
            predictions=PredictionInfo(
                version=1,
                attrs_url="https://acct.blob/c/hash/attrs_v1.json?sas",
                is_latest=False,
            ),
        )

        self.assertEqual(visualizer.predictionVersion, 1)
        self.assertFalse(visualizer.predictionVersionIsLatest)
        # The reports keep reading the newest version, which is still v2.
        self.assertEqual(
            [entry["version"] for entry in visualizer.predictionVersions],
            [2, 1],
        )

    def test_true_when_the_newest_version_is_selected(self):
        model = _model(_edited(1), _edited(2))

        visualizer = _build(
            model,
            predictions=PredictionInfo(
                version=2,
                attrs_url="https://acct.blob/c/hash/attrs_v2.json?sas",
                is_latest=True,
            ),
        )

        self.assertTrue(visualizer.predictionVersionIsLatest)

    def test_false_for_the_raw_output_of_an_edited_model(self):
        model = _model(_edited(1))

        visualizer = _build(
            model,
            predictions=PredictionInfo(attrs_url=ATTRS_URL, is_latest=False),
        )

        self.assertIsNone(visualizer.predictionVersion)
        self.assertFalse(visualizer.predictionVersionIsLatest)

    def test_flag_survives_serialization(self):
        model = _model(_edited(1), _edited(2))

        payload = _build(
            model,
            predictions=PredictionInfo(
                version=1,
                attrs_url="https://acct.blob/c/hash/attrs_v1.json?sas",
                is_latest=False,
            ),
        ).model_dump()

        self.assertIn("predictionVersionIsLatest", payload)
        self.assertFalse(payload["predictionVersionIsLatest"])


if __name__ == "__main__":
    unittest.main()
