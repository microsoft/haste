# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from hastegeo.core.config import Config
from hastegeo.core.models.projects import (
    ImageLayer,
    LabelProject,
    Model,
    Project,
)
from hastegeo.core.processors.labels import (
    LabelTaskGenerator,
    materialize_label_project_urls,
)
from hastegeo.core.processors.visualizer import build_visualizer


class TestLabelMaterialization(unittest.TestCase):
    def setUp(self) -> None:
        self.layer = ImageLayer(
            projectId="p1",
            imageLayerId="layer1",
            postEventProcessedImageryUrl=(
                "https://acct.blob.core.windows.net/data/post.tif"
            ),
        )
        self.label = {
            "projectId": "p1",
            "imageLayerId": "layer1",
            "imagery": {
                "tileUrl": "https://untrusted.example/?url=some-other-project",
                "bounds": [1, 2, 3, 4],
            },
        }

    def test_rebuilds_tiles_from_trusted_layer_without_mutation(self) -> None:
        with patch(
            "hastegeo.core.processors.labels.sign_project_raster_url",
            side_effect=lambda url, *_args: (
                f"{url}?sig=fresh" if url else None
            ),
        ) as signer:
            result = materialize_label_project_urls(
                self.label, self.layer, "/api/titiler/"
            )
        tile = result["imagery"]["tileUrl"]
        self.assertTrue(tile.startswith("/api/titiler/cog/tiles/"))
        self.assertEqual(
            parse_qs(urlparse(tile).query)["url"],
            [f"{self.layer.postEventProcessedImageryUrl}?sig=fresh"],
        )
        self.assertEqual(result["imagery"]["preEventTileUrl"], "")
        self.assertEqual(result["imagery"]["bounds"], [1, 2, 3, 4])
        self.assertIn("untrusted", self.label["imagery"]["tileUrl"])
        self.assertEqual(
            signer.call_args.args[1:],
            ("p1", "blob"),
        )

    def test_wrong_project_or_layer_fails_before_signing(self) -> None:
        for field in ("projectId", "imageLayerId"):
            with self.subTest(field=field), patch(
                "hastegeo.core.processors.labels.sign_project_raster_url"
            ) as signer:
                with self.assertRaises(ValueError):
                    materialize_label_project_urls(
                        {**self.label, field: "another"},
                        self.layer,
                        "/api/titiler/",
                    )
                signer.assert_not_called()

    def test_local_filesystem_source_does_not_require_blob_configuration(
        self,
    ) -> None:
        self.layer.postEventProcessedImageryUrl = "/data/project/image.tif"
        result = materialize_label_project_urls(
            self.label, self.layer, "/api/titiler/", "local"
        )
        self.assertEqual(
            parse_qs(urlparse(result["imagery"]["tileUrl"]).query)["url"],
            ["/data/project/image.tif"],
        )

    def test_local_label_generation_opens_the_filesystem_path(self) -> None:
        self.layer.postEventProcessedImageryUrl = "/data/project/image.tif"
        config = Config()
        config.storage_type = "local"
        dataset = MagicMock()
        dataset.bounds = (0, 0, 1, 1)
        dataset.crs.to_epsg.return_value = 4326
        with patch(
            "hastegeo.core.processors.labels.rasterio.open"
        ) as raster_open:
            raster_open.return_value.__enter__.return_value = dataset
            LabelTaskGenerator(self.layer, config).generate_task_files()
        raster_open.assert_called_once_with("/data/project/image.tif")

    def test_local_visualizer_uses_the_filesystem_source(self) -> None:
        self.layer.postEventProcessedImageryUrl = "/data/project/image.tif"
        result = build_visualizer(
            Model(projectId="p1", imageLayerId="layer1", modelId="m1"),
            self.layer,
            Project(projectId="p1"),
            LabelProject(),
            "/tiles/",
            storage_type="local",
        )
        self.assertEqual(
            parse_qs(urlparse(result.postDisasterImagery.url).query)["url"],
            ["/data/project/image.tif"],
        )
