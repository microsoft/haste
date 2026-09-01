# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for the results-viewer payload builder.

The viewer has to serve BOTH workflows from one payload:

* **trained inference** writes two COGs, so it keeps the raster tile
  layers it always had, and
* **embedding** writes no rasters at all, so those fields must be
  ``None`` rather than TiTiler templates over a URL that does not exist.

Both get the vector artifacts (footprint PMTiles + attribute sidecar) as
API-relative ``GetModelArtifact`` routes, plus a readiness block so the
UI can show "still preparing" instead of an empty map.

No I/O happens here: ``build_visualizer_results`` is a pure assembler
and the prediction flavor is passed in by the HTTP layer.
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
    raster_layer_urls,
)
from hastegeo.core.utils.model_readiness import (
    REASON_NOT_PROCESSED,
    REASON_READY,
)

STATUSES = Config.get_status_types()
PROCESSED = STATUSES.COMPLETED.value

TITILER = "https://titiler.example.net/"
PROJECT_ID = "11111111-1111-1111-1111-111111111111"
LAYER_ID = "22222222-2222-2222-2222-222222222222"

PRE_URL = "https://acct.blob/c/hash/pre_cog.tif?sas=a&b=c"
POST_URL = "https://acct.blob/c/hash/post_cog.tif?sas=a&b=c"
VISUALIZER_URL = "https://acct.blob/c/hash/5557_visualizer.tif?sas=a&b=c"
PREDICTIONS_URL = "https://acct.blob/c/hash/5557_predictions.tif?sas=a&b=c"
GPKG_URL = "https://acct.blob/c/hash/predicted_damage_m.gpkg?sas"
LAYER_PMTILES = "https://acct.blob/c/hash/footprints_layer.pmtiles?sas"
ATTRS_URL = "https://acct.blob/c/hash/prediction_attrs_5557.json?sas"

BBOX = [-1.0, -2.0, 3.0, 4.0]


class _Feature:
    """Stand-in for a LabelProject feature (only ``bbox`` is read)."""

    def __init__(self, bbox):
        self.bbox = bbox


def _project(**overrides) -> Project:
    data = {
        "projectId": PROJECT_ID,
        "name": "Hurricane Test",
        "eventDate": "2026-01-02T00:00:00Z",
    }
    data.update(overrides)
    return Project(**data)


def _layer(**overrides) -> ImageLayer:
    data = {
        "imageLayerId": LAYER_ID,
        "projectId": PROJECT_ID,
        "preEventImageryUrls": ["https://acct.blob/c/raw/pre.tif"],
        "preEventProcessedImageryUrl": PRE_URL,
        "postEventProcessedImageryUrl": POST_URL,
        "buildingFootprintsUrl": "https://acct.blob/c/hash/fp.gpkg?sas",
        "footprintPmtilesUrl": LAYER_PMTILES,
        "sourceTypePreEvent": "Maxar",
        "sourceTypePostEvent": "Maxar",
        "imageryCaptureDatePreEvent": "2026-01-01",
        "imageryCaptureDatePostEvent": "2026-01-03",
    }
    data.update(overrides)
    return ImageLayer(**data)


def _trained_model(**overrides) -> Model:
    data = {
        "modelId": "5557",
        "projectId": PROJECT_ID,
        "imageLayerId": LAYER_ID,
        "modelType": "trained",
        "status": PROCESSED,
        "inferenceStatus": PROCESSED,
        "gpkgUrl": GPKG_URL,
        "predictedDamageLayerUrl": VISUALIZER_URL,
        "predictionAttrsUrl": ATTRS_URL,
        "predictionTilesStatus": PROCESSED,
    }
    data.update(overrides)
    return Model(**data)


def _embedding_model(**overrides) -> Model:
    data = {
        "modelId": "5558",
        "projectId": PROJECT_ID,
        "imageLayerId": LAYER_ID,
        "modelType": "embedding",
        "status": PROCESSED,
        "gpkgUrl": GPKG_URL,
        "predictedBuildingCount": 1200,
        "predictionAttrsUrl": ATTRS_URL,
        "predictionTilesStatus": PROCESSED,
    }
    data.update(overrides)
    return Model(**data)


def _build(model: Model, layer: ImageLayer = None, **kwargs):
    return build_visualizer_results(
        project=_project(),
        image_layer=layer or _layer(),
        model=model,
        titiler_endpoint=TITILER,
        study_area=[_Feature(BBOX)],
        **kwargs,
    )


class TestTrainedInferencePayload(unittest.TestCase):
    """Workflow A must keep exactly the shape the viewer already uses."""

    def test_raster_layers_are_present(self):
        visualizer = _build(_trained_model())

        self.assertIsNotNone(visualizer.predictedDamageLayer)
        self.assertIsNotNone(visualizer.predictionsLayer)

    def test_predicted_damage_layer_points_at_the_visualizer_cog(self):
        visualizer = _build(_trained_model())

        url = visualizer.predictedDamageLayer.url
        self.assertTrue(url.startswith(f"{TITILER}cog/tiles/"))
        self.assertIn("{z}/{x}/{y}", url)
        # The SAS-bearing blob URL must be fully percent-encoded.
        self.assertNotIn(VISUALIZER_URL, url)
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query["url"], [VISUALIZER_URL])

    def test_predictions_layer_derives_the_sibling_cog_with_a_colormap(self):
        visualizer = _build(_trained_model())

        query = parse_qs(urlparse(visualizer.predictionsLayer.url).query)
        self.assertEqual(query["url"], [PREDICTIONS_URL])
        self.assertIn("colormap", query)

    def test_layers_are_bounded_by_the_study_area(self):
        visualizer = _build(_trained_model())

        self.assertEqual(visualizer.predictedDamageLayer.bounds, BBOX)
        self.assertEqual(visualizer.preDisasterImagery.bounds, BBOX)
        self.assertEqual(visualizer.postDisasterImagery.bounds, BBOX)

    def test_imagery_and_metadata_are_carried_through(self):
        visualizer = _build(_trained_model())

        self.assertEqual(visualizer.projectId, PROJECT_ID)
        self.assertEqual(visualizer.imageLayerId, LAYER_ID)
        self.assertEqual(visualizer.modelId, "5557")
        self.assertEqual(visualizer.projectName, "Hurricane Test")
        self.assertEqual(visualizer.eventDate, "2026-01-02T00:00:00Z")
        self.assertEqual(visualizer.sourceTypePostEvent, "Maxar")
        self.assertEqual(visualizer.imageryCaptureDatePreEvent, "2026-01-01")
        self.assertIn("url=", visualizer.postDisasterImagery.url)

    def test_pre_event_imagery_is_empty_without_uploads(self):
        # No pre-event upload: the viewer falls back to the base map.
        visualizer = _build(
            _trained_model(), layer=_layer(preEventImageryUrls=[])
        )

        self.assertEqual(visualizer.preDisasterImagery.url, "")

    def test_flavor_comes_from_the_prediction_reader(self):
        visualizer = _build(
            _trained_model(),
            predictions=PredictionInfo(
                flavor="inference",
                supports_threshold=True,
                building_count=1234,
            ),
        )

        self.assertEqual(visualizer.flavor, "inference")
        self.assertTrue(visualizer.supportsThreshold)
        self.assertEqual(visualizer.buildingCount, 1234)

    def test_payload_is_json_serializable(self):
        import json

        payload = _build(
            _trained_model(), predictions=PredictionInfo(flavor="inference")
        ).dict()
        payload["studyArea"] = []

        self.assertIn("predictedDamageLayer", json.loads(json.dumps(payload)))


class TestEmbeddingPayload(unittest.TestCase):
    """Workflow B has no rasters — and must still be usable."""

    def test_raster_layers_are_absent(self):
        visualizer = _build(_embedding_model())

        self.assertIsNone(visualizer.predictedDamageLayer)
        self.assertIsNone(visualizer.predictionsLayer)

    def test_vector_artifacts_are_served_through_the_api(self):
        visualizer = _build(_embedding_model())

        self.assertIsNotNone(visualizer.footprintTilesUrl)
        self.assertIsNotNone(visualizer.predictionAttrsUrl)
        for url in (
            visualizer.footprintTilesUrl,
            visualizer.predictionAttrsUrl,
        ):
            # API-relative route, never a raw blob SAS URL.
            self.assertTrue(url.startswith("GetModelArtifact?"))
            self.assertNotIn("blob", url)

    def test_footprint_tiles_come_from_the_layer(self):
        # Footprint geometry belongs to the image layer and one archive is
        # shared by every model on it, so a layer that has not been tiled
        # yet is "preparing" rather than ready — an embedding model has no
        # raster to fall back on, and an empty map is the worst answer.
        visualizer = _build(
            _embedding_model(), layer=_layer(footprintPmtilesUrl=None)
        )

        self.assertFalse(visualizer.predictionsReady)

        # With the layer tiled, the same model is ready.
        ready = _build(_embedding_model(), layer=_layer())
        self.assertTrue(ready.predictionsReady)
        self.assertIsNotNone(ready.footprintTilesUrl)

    def test_embedding_flavor_disables_thresholding(self):
        visualizer = _build(
            _embedding_model(),
            predictions=PredictionInfo(
                flavor="embedding",
                supports_threshold=False,
                building_count=1200,
            ),
        )

        self.assertEqual(visualizer.flavor, "embedding")
        self.assertFalse(visualizer.supportsThreshold)

    def test_ready_payload_is_returned_for_an_embedding_model(self):
        visualizer = _build(_embedding_model())

        self.assertTrue(visualizer.predictionsReady)
        self.assertEqual(visualizer.predictionsReadiness.workflow, "embedding")
        self.assertEqual(visualizer.predictionsReadiness.reason, REASON_READY)


class TestArtifactRoutes(unittest.TestCase):
    def test_route_carries_the_ids_and_kind(self):
        url = model_artifact_url(
            PROJECT_ID, "5557", "footprint_pmtiles", image_layer_id=LAYER_ID
        )

        query = parse_qs(urlparse(url).query)
        self.assertEqual(query["projectId"], [PROJECT_ID])
        self.assertEqual(query["modelId"], ["5557"])
        self.assertEqual(query["kind"], ["footprint_pmtiles"])
        self.assertEqual(query["imageLayerId"], [LAYER_ID])

    def test_attrs_route_is_model_scoped_only(self):
        visualizer = _build(_trained_model())

        query = parse_qs(urlparse(visualizer.predictionAttrsUrl).query)
        self.assertEqual(query["kind"], ["prediction_attrs"])
        self.assertNotIn("imageLayerId", query)


class TestRasterUrlDerivation(unittest.TestCase):
    def test_sibling_predictions_cog_is_derived(self):
        urls = raster_layer_urls(_trained_model())

        self.assertEqual(urls["visualizer"], VISUALIZER_URL)
        self.assertEqual(urls["predictions"], PREDICTIONS_URL)

    def test_no_rasters_without_a_visualizer_cog(self):
        urls = raster_layer_urls(_embedding_model())

        self.assertIsNone(urls["visualizer"])
        self.assertIsNone(urls["predictions"])

    def test_unexpected_name_yields_no_predictions_layer(self):
        # The raw prediction COG is derived by name, so an unfamiliar
        # name must produce no layer rather than a URL that 404s.
        model = _trained_model(
            predictedDamageLayerUrl="https://acct.blob/c/hash/odd.tif?sas"
        )

        urls = raster_layer_urls(model)

        self.assertIsNotNone(urls["visualizer"])
        self.assertIsNone(urls["predictions"])
        self.assertIsNone(_build(model).predictionsLayer)


class TestReadiness(unittest.TestCase):
    def test_not_ready_while_inference_runs(self):
        visualizer = _build(_trained_model(inferenceStatus="InProgress"))

        self.assertFalse(visualizer.predictionsReady)
        self.assertEqual(
            visualizer.predictionsReadiness.reason, REASON_NOT_PROCESSED
        )
        self.assertTrue(visualizer.predictionsReadiness.detail)

    def test_preparing_when_the_sidecar_is_missing(self):
        visualizer = _build(
            _trained_model(
                predictionAttrsUrl=None,
                predictionTilesStatus="Queued",
                predictionTilesStatusMessage="\nQueued for preparation",
            )
        )

        readiness = visualizer.predictionsReadiness
        self.assertFalse(visualizer.predictionsReady)
        self.assertEqual(readiness.reason, REASON_PREPARING)
        self.assertTrue(readiness.tilesReady)
        self.assertFalse(readiness.attrsReady)
        self.assertEqual(readiness.predictionTilesStatus, "Queued")
        self.assertIn("Queued", readiness.predictionTilesStatusMessage)
        # The artifact URL is withheld until the artifact exists.
        self.assertIsNone(visualizer.predictionAttrsUrl)

    def test_preparing_when_the_tiles_are_missing(self):
        visualizer = _build(
            _trained_model(), layer=_layer(footprintPmtilesUrl=None)
        )

        readiness = visualizer.predictionsReadiness
        self.assertFalse(visualizer.predictionsReady)
        self.assertEqual(readiness.reason, REASON_PREPARING)
        self.assertFalse(readiness.tilesReady)
        self.assertIsNone(visualizer.footprintTilesUrl)

    def test_rasters_survive_an_unprepared_vector_layer(self):
        # A classic model whose tiles are not built yet still shows its
        # rasters; only the vector layer waits.
        visualizer = _build(
            _trained_model(), layer=_layer(footprintPmtilesUrl=None)
        )

        self.assertIsNotNone(visualizer.predictedDamageLayer)


class TestVersionSelection(unittest.TestCase):
    def _edited(self, version: int) -> dict:
        return {
            "version": version,
            "gpkgUrl": f"https://acct.blob/c/hash/edited_v{version}.gpkg",
            "createdAt": "2026-08-21T05:10:48+00:00",
            "editedCount": 5,
        }

    def test_raw_source_reports_no_version(self):
        visualizer = _build(_trained_model())

        self.assertIsNone(visualizer.predictionVersion)
        self.assertEqual(visualizer.predictionVersions, [])

    def test_selected_version_and_history_are_reported(self):
        model = _trained_model(
            editedPredictions=[self._edited(1), self._edited(2)]
        )

        visualizer = _build(model, predictions=PredictionInfo(version=2))

        self.assertEqual(visualizer.predictionVersion, 2)
        self.assertEqual(
            [v["version"] for v in visualizer.predictionVersions], [2, 1]
        )


class TestStudyArea(unittest.TestCase):
    def test_missing_study_area_leaves_bounds_unset(self):
        visualizer = build_visualizer_results(
            project=_project(),
            image_layer=_layer(),
            model=_trained_model(),
            titiler_endpoint=TITILER,
            study_area=None,
        )

        self.assertEqual(visualizer.studyArea, [])
        self.assertIsNone(visualizer.postDisasterImagery.bounds)

    def test_dict_features_are_supported(self):
        visualizer = build_visualizer_results(
            project=_project(),
            image_layer=_layer(),
            model=_trained_model(),
            titiler_endpoint=TITILER,
            study_area=[{"bbox": BBOX}],
        )

        self.assertEqual(visualizer.postDisasterImagery.bounds, BBOX)


if __name__ == "__main__":
    unittest.main()
