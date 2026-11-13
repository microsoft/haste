# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from hastegeo.core.models.projects import ImageLayer
from hastegeo.core.processors.labels import materialize_label_project_urls
from hastegeo.core.utils.blob import project_blob_prefix


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
            "hastegeo.core.processors.labels.sign_internal_blob_url",
            side_effect=lambda url, **kwargs: (
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
            signer.call_args.kwargs["required_blob_prefix"],
            project_blob_prefix("p1"),
        )

    def test_wrong_project_or_layer_fails_before_signing(self) -> None:
        for field in ("projectId", "imageLayerId"):
            with self.subTest(field=field), patch(
                "hastegeo.core.processors.labels.sign_internal_blob_url"
            ) as signer:
                with self.assertRaises(ValueError):
                    materialize_label_project_urls(
                        {**self.label, field: "another"},
                        self.layer,
                        "/api/titiler/",
                    )
                signer.assert_not_called()
