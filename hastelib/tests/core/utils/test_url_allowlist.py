# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Tests for the URL allowlist helpers.

These cover both the long-standing :func:`validate_imagery_url` and the
new :func:`validate_footprint_url`, which extends the imagery allowlist
with the configured local upload host so the chunked uploader's output
URL works end-to-end in local dev without opening a broader hole.
"""

import os
import unittest
from unittest.mock import patch

from hastegeo.core.utils.url_allowlist import (
    validate_footprint_url,
    validate_imagery_url,
)


class TestValidateImageryUrl(unittest.TestCase):
    def test_accepts_azure_blob_host(self):
        self.assertEqual(
            validate_imagery_url(
                "https://researchlabwuopendata.blob.core.windows.net/c/img.tif"
            ),
            "azureblobstorage",
        )

    def test_accepts_aws_s3_host(self):
        self.assertEqual(
            validate_imagery_url(
                "https://maxar-opendata.s3.amazonaws.com/x/y.tif"
            ),
            "awss3",
        )
        self.assertEqual(
            validate_imagery_url(
                "https://my-bucket.s3.us-east-1.amazonaws.com/k/img.tif"
            ),
            "awss3",
        )

    def test_accepts_source_cooperative_host(self):
        # Planet Open Data STAC catalogs/COGs surfaced by the Open Data
        # Catalog explorer are served from data.source.coop.
        self.assertEqual(
            validate_imagery_url(
                "https://data.source.coop/planet/venezuela-earthquake"
                "-2026-06-24/post-event/scene.tif"
            ),
            "sourcecoop",
        )

    def test_rejects_arbitrary_host(self):
        with self.assertRaises(ValueError):
            validate_imagery_url("https://evil.example.com/x.tif")

    def test_rejects_unsupported_scheme(self):
        with self.assertRaises(ValueError):
            validate_imagery_url("ftp://blob.core.windows.net/c/x.tif")

    def test_rejects_missing_host(self):
        with self.assertRaises(ValueError):
            validate_imagery_url("https:///path/only")


class TestValidateFootprintUrl(unittest.TestCase):
    """:func:`validate_footprint_url` is :func:`validate_imagery_url` plus the
    configured local upload host (so the chunked uploader's outputUrl is
    accepted in dev). Production behavior is identical to the imagery
    allowlist because BLOB_ACCOUNT_URL there resolves to a
    ``*.blob.core.windows.net`` host which is already on the imagery
    allowlist."""

    def setUp(self):
        # Ensure no leftover env vars leak between tests.
        self._saved_blob = os.environ.pop("BLOB_ACCOUNT_URL", None)
        self._saved_dev = os.environ.pop(
            "HASTE_ALLOW_LOCAL_FOOTPRINT_HOSTS", None
        )

    def tearDown(self):
        if self._saved_blob is not None:
            os.environ["BLOB_ACCOUNT_URL"] = self._saved_blob
        else:
            os.environ.pop("BLOB_ACCOUNT_URL", None)
        if self._saved_dev is not None:
            os.environ["HASTE_ALLOW_LOCAL_FOOTPRINT_HOSTS"] = self._saved_dev
        else:
            os.environ.pop("HASTE_ALLOW_LOCAL_FOOTPRINT_HOSTS", None)

    def test_passes_through_to_imagery_allowlist_for_azure(self):
        self.assertEqual(
            validate_footprint_url(
                "https://my.blob.core.windows.net/c/footprints.gpkg"
            ),
            "azureblobstorage",
        )

    def test_passes_through_to_imagery_allowlist_for_aws(self):
        self.assertEqual(
            validate_footprint_url(
                "https://b.s3.amazonaws.com/footprints.gpkg"
            ),
            "awss3",
        )

    def test_accepts_configured_blob_account_url_host(self):
        os.environ[
            "BLOB_ACCOUNT_URL"
        ] = "http://azurite:10000/devstoreaccount1"
        self.assertEqual(
            validate_footprint_url(
                "http://azurite:10000/devstoreaccount1/c/f.gpkg?sig=x"
            ),
            "localupload",
        )

    def test_rejects_when_port_differs_from_blob_account_url(self):
        os.environ[
            "BLOB_ACCOUNT_URL"
        ] = "http://azurite:10000/devstoreaccount1"
        # Different port — not the same upload endpoint.
        with self.assertRaises(ValueError):
            validate_footprint_url(
                "http://azurite:20000/devstoreaccount1/c/f.gpkg"
            )

    def test_rejects_when_scheme_differs_from_blob_account_url(self):
        os.environ[
            "BLOB_ACCOUNT_URL"
        ] = "http://azurite:10000/devstoreaccount1"
        with self.assertRaises(ValueError):
            validate_footprint_url(
                "https://azurite:10000/devstoreaccount1/c/f.gpkg"
            )

    def test_dev_hosts_rejected_when_opt_in_flag_unset(self):
        # No BLOB_ACCOUNT_URL and no opt-in flag: the conventional dev
        # hostnames must be rejected. This is the SSRF guard — production
        # misconfiguration must not silently accept loopback hosts.
        for url in (
            "http://azurite:10000/devstoreaccount1/c/f.gpkg",
            "http://localhost:10000/devstoreaccount1/c/f.gpkg",
            "http://127.0.0.1:22/c/f.gpkg",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    validate_footprint_url(url)

    def test_dev_hosts_allowed_only_when_opt_in_flag_set(self):
        # Operators in dev can opt in to permit the conventional Azurite
        # hosts (the docker-compose dev stack sets this env var). Only
        # the specific dev hostnames are allowed even with the flag on.
        os.environ["HASTE_ALLOW_LOCAL_FOOTPRINT_HOSTS"] = "1"
        for url in (
            "http://azurite:10000/devstoreaccount1/c/f.gpkg",
            "http://localhost:10000/devstoreaccount1/c/f.gpkg",
            "http://127.0.0.1:10000/devstoreaccount1/c/f.gpkg",
        ):
            with self.subTest(url=url):
                self.assertEqual(validate_footprint_url(url), "localupload")

    def test_opt_in_flag_does_not_allow_arbitrary_loopback(self):
        # Even with the flag set, only the specific dev hostnames are
        # accepted — not e.g. ``0.0.0.0``, ``[::1]``, or external
        # addresses pretending to be loopback.
        os.environ["HASTE_ALLOW_LOCAL_FOOTPRINT_HOSTS"] = "1"
        for url in (
            "http://0.0.0.0:8080/x.gpkg",
            "http://[::1]:80/x.gpkg",
            "http://169.254.169.254/latest/meta-data/",  # AWS metadata
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    validate_footprint_url(url)

    def test_dev_fallback_suppressed_when_env_set(self):
        # When BLOB_ACCOUNT_URL points somewhere specific, the broader
        # fallback to localhost/127.0.0.1 is suppressed.
        os.environ[
            "BLOB_ACCOUNT_URL"
        ] = "http://azurite:10000/devstoreaccount1"
        with self.assertRaises(ValueError):
            validate_footprint_url(
                "http://localhost:10000/devstoreaccount1/c/f.gpkg"
            )

    def test_rejects_arbitrary_internet_host(self):
        with self.assertRaises(ValueError):
            validate_footprint_url("https://evil.example.com/f.gpkg")

    def test_rejects_unsupported_scheme(self):
        with self.assertRaises(ValueError):
            validate_footprint_url("ftp://my.blob.core.windows.net/c/f.gpkg")

    def test_unparseable_blob_account_url_is_ignored(self):
        # Setting a garbage env var must not blow up validation; it just
        # disables the local-upload exception (and the dev fallback).
        with patch.dict(os.environ, {"BLOB_ACCOUNT_URL": "::::not a url::::"}):
            with self.assertRaises(ValueError):
                validate_footprint_url(
                    "http://azurite:10000/devstoreaccount1/c/f.gpkg"
                )


class _FakeImageLayer:
    """Minimal stand-in for hastegeo.core.models.projects.ImageLayer.

    Only the attributes the validators actually read are populated;
    using a real ImageLayer would pull a heavy Pydantic + storage
    import chain into this test module for no behavioral benefit.
    """

    def __init__(
        self,
        *,
        preEventImageryUrls=None,
        postEventImageryUrls=None,
        userBuildingFootprintsUrl=None,
    ):
        self.preEventImageryUrls = preEventImageryUrls
        self.postEventImageryUrls = postEventImageryUrls
        self.userBuildingFootprintsUrl = userBuildingFootprintsUrl


class TestValidateImageLayerImageryUrls(unittest.TestCase):
    """Tests for validate_image_layer_imagery_urls (ImageLayer-shaped wrapper)."""

    def test_all_urls_on_allowlist_returns_none(self):
        from hastegeo.core.utils.url_allowlist import (
            validate_image_layer_imagery_urls,
        )

        layer = _FakeImageLayer(
            preEventImageryUrls=[
                "https://x.blob.core.windows.net/c/a.tif",
                "https://y.s3.amazonaws.com/a.tif",
            ],
            postEventImageryUrls=[
                "https://z.blob.core.windows.net/c/b.tif",
            ],
        )
        self.assertIsNone(validate_image_layer_imagery_urls(layer))

    def test_empty_layer_returns_none(self):
        from hastegeo.core.utils.url_allowlist import (
            validate_image_layer_imagery_urls,
        )

        self.assertIsNone(validate_image_layer_imagery_urls(_FakeImageLayer()))

    def test_one_bad_url_reports_rejected_host(self):
        from hastegeo.core.utils.url_allowlist import (
            validate_image_layer_imagery_urls,
        )

        layer = _FakeImageLayer(
            preEventImageryUrls=[
                "https://x.blob.core.windows.net/c/ok.tif",
                "https://evil.example/bad.tif",
            ],
        )
        msg = validate_image_layer_imagery_urls(layer)
        self.assertIsNotNone(msg)
        self.assertIn("evil.example", msg)
        self.assertIn("allowlist", msg.lower())
        # Other allowlisted URL is not surfaced
        self.assertNotIn("x.blob.core.windows.net", msg)

    def test_dedupe_rejected_hosts(self):
        from hastegeo.core.utils.url_allowlist import (
            validate_image_layer_imagery_urls,
        )

        layer = _FakeImageLayer(
            preEventImageryUrls=["https://evil.example/a.tif"],
            postEventImageryUrls=["https://evil.example/b.tif"],
        )
        msg = validate_image_layer_imagery_urls(layer)
        self.assertEqual(msg.count("evil.example"), 1)

    def test_skips_falsy_urls_in_list(self):
        from hastegeo.core.utils.url_allowlist import (
            validate_image_layer_imagery_urls,
        )

        layer = _FakeImageLayer(
            preEventImageryUrls=[
                None,
                "",
                "https://x.blob.core.windows.net/c/a.tif",
            ],
        )
        self.assertIsNone(validate_image_layer_imagery_urls(layer))


class TestValidateImageLayerUserFootprintsUrl(unittest.TestCase):
    """Tests for validate_image_layer_user_footprints_url."""

    def test_no_url_returns_none(self):
        from hastegeo.core.utils.url_allowlist import (
            validate_image_layer_user_footprints_url,
        )

        self.assertIsNone(
            validate_image_layer_user_footprints_url(_FakeImageLayer())
        )

    def test_allowlisted_url_returns_none(self):
        from hastegeo.core.utils.url_allowlist import (
            validate_image_layer_user_footprints_url,
        )

        layer = _FakeImageLayer(
            userBuildingFootprintsUrl=(
                "https://x.blob.core.windows.net/c/footprints.gpkg"
            )
        )
        self.assertIsNone(validate_image_layer_user_footprints_url(layer))

    def test_bad_url_reports_rejected_host(self):
        from hastegeo.core.utils.url_allowlist import (
            validate_image_layer_user_footprints_url,
        )

        layer = _FakeImageLayer(
            userBuildingFootprintsUrl="https://evil.example/x.gpkg"
        )
        msg = validate_image_layer_user_footprints_url(layer)
        self.assertIsNotNone(msg)
        self.assertIn("evil.example", msg)


class TestValidateClipBbox(unittest.TestCase):
    """Tests for validate_clip_bbox (server-side clip AOI on an ImageLayer)."""

    def _layer(self, bbox):
        from types import SimpleNamespace

        return SimpleNamespace(clipBbox=bbox)

    def test_none_returns_none(self):
        from hastegeo.core.utils.url_allowlist import validate_clip_bbox

        self.assertIsNone(validate_clip_bbox(self._layer(None)))

    def test_valid_bbox_returns_none(self):
        from hastegeo.core.utils.url_allowlist import validate_clip_bbox

        self.assertIsNone(
            validate_clip_bbox(self._layer([-67.03, 10.54, -66.97, 10.61]))
        )

    def test_wrong_length_rejected(self):
        from hastegeo.core.utils.url_allowlist import validate_clip_bbox

        self.assertIsNotNone(validate_clip_bbox(self._layer([1, 2, 3])))

    def test_non_numeric_rejected(self):
        from hastegeo.core.utils.url_allowlist import validate_clip_bbox

        self.assertIsNotNone(
            validate_clip_bbox(self._layer([-67, "x", -66, 11]))
        )

    def test_out_of_range_rejected(self):
        from hastegeo.core.utils.url_allowlist import validate_clip_bbox

        self.assertIsNotNone(
            validate_clip_bbox(self._layer([-67, 10, -66, 99]))
        )

    def test_inverted_bounds_rejected(self):
        from hastegeo.core.utils.url_allowlist import validate_clip_bbox

        # west >= east
        self.assertIsNotNone(
            validate_clip_bbox(self._layer([-66, 10.5, -67, 10.6]))
        )
        # south >= north
        self.assertIsNotNone(
            validate_clip_bbox(self._layer([-67, 10.6, -66, 10.5]))
        )


if __name__ == "__main__":
    unittest.main()
