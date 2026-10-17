# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""The dataset url check must admit only plain https URLs on exact hosts."""

import socket
import unittest
import urllib.error
from unittest.mock import MagicMock

from api.titilerfuncapi.app.dataset_url import (
    DatasetUrlError,
    DatasetUrlPolicy,
    DestinationChecker,
    check_destination_addresses,
    validate_dataset_url,
)

STORAGE_HOST = "examplestorage.blob.core.windows.net"
POLICY = DatasetUrlPolicy.from_env({"TITILER_ALLOWED_HOSTS": STORAGE_HOST})
DEV_POLICY = DatasetUrlPolicy.from_env(
    {"TITILER_DEV_ALLOWED_ORIGINS": "http://azurite:10000"}
)

ACCEPTED = [
    "https://vantor-opendata.s3.amazonaws.com/events/a/B1.tif",
    "https://data.source.coop/planet/disasterdata/x/items/L15.tif",
    f"https://{STORAGE_HOST}/data/p/l/post.tif?sv=2024-11-04&sig=abc%2Bdef%3D",
]

REJECTED = {
    "inline VRT": '<VRTDataset rasterXSize="1"></VRTDataset>',
    "inline VRT after whitespace": " <VRTDataset/>",
    "absolute path": "/etc/passwd",
    "relative path": "data/post.tif",
    "parent path": "../../home/site/wwwroot/local.settings.json",
    "file url": "file:///etc/passwd",
    "vsicurl": f"/vsicurl/https://{STORAGE_HOST}/data/a.tif",
    "vsi in scheme": "vsicurl://evil/a.tif",
    "zip scheme": f"zip+https://{STORAGE_HOST}/data/a.zip!/a.tif",
    "archive member": f"https://{STORAGE_HOST}/data/a.zip!/a.tif",
    "http": f"http://{STORAGE_HOST}/data/a.tif",
    "upper-case scheme": f"HTTPS://{STORAGE_HOST}/data/a.tif",
    "ftp": "ftp://data.source.coop/a.tif",
    "unknown host": "https://example.com/a.tif",
    "other storage account": "https://attacker.blob.core.windows.net/c/a.tif",
    "other bucket": "https://evil.s3.amazonaws.com/a.tif",
    "suffix trick": "https://data.source.coop.evil.com/a.tif",
    "userinfo": "https://user:pw@data.source.coop/a.tif",  # pragma: allowlist secret
    "userinfo host swap": "https://data.source.coop@evil.com/a.tif",
    "explicit port": "https://data.source.coop:8443/a.tif",
    "port 443": "https://data.source.coop:443/a.tif",
    "ip literal": "https://169.254.169.254/metadata",
    "ipv6 literal": "https://[::1]/a.tif",
    "trailing dot host": "https://data.source.coop./a.tif",
    "upper-case host": "https://DATA.source.coop/a.tif",
    "traversal": "https://data.source.coop/planet/../../a.tif",
    "encoded traversal": "https://data.source.coop/planet/%2e%2e/a.tif",
    "double-encoded traversal": "https://data.source.coop/p/%252e%252e/a",
    "encoded backslash": "https://data.source.coop/p/%5c..%5ca.tif",
    "encoded nul": "https://data.source.coop/a.tif%00.png",
    "backslash": "https://data.source.coop\\@evil.com/a.tif",
    "newline": "https://data.source.coop/a.tif\nHost: evil",
    "space": "https://data.source.coop/a b.tif",
    "non-ascii": "https://data.source.coop/é.tif",
    "fragment": "https://data.source.coop/a.tif#frag",
    "no path": "https://data.source.coop",
    "root path": "https://data.source.coop/",
    "bad port": "https://data.source.coop:99999/a.tif",
    "empty": "",
    "too long": "https://data.source.coop/" + "a" * 5000,
}


class TestValidateDatasetUrl(unittest.TestCase):
    def test_accepts_approved_urls_unchanged(self):
        for url in ACCEPTED:
            with self.subTest(url=url):
                self.assertEqual(validate_dataset_url(url, POLICY), url)

    def test_rejects_everything_else(self):
        for name, url in REJECTED.items():
            with self.subTest(name):
                with self.assertRaises(DatasetUrlError):
                    validate_dataset_url(url, POLICY)

    def test_storage_host_needs_configuration(self):
        url = ACCEPTED[2]
        with self.assertRaises(DatasetUrlError):
            validate_dataset_url(url, DatasetUrlPolicy.from_env({}))

    def test_http_only_for_the_exact_dev_origin(self):
        ok = "http://azurite:10000/devstoreaccount1/data/a.tif?sig=x"
        self.assertEqual(validate_dataset_url(ok, DEV_POLICY), ok)
        for url in (
            "http://azurite:10001/devstoreaccount1/data/a.tif",
            "http://azurite/devstoreaccount1/data/a.tif",
            "http://localhost:10000/devstoreaccount1/data/a.tif",
        ):
            with self.subTest(url=url):
                with self.assertRaises(DatasetUrlError):
                    validate_dataset_url(url, DEV_POLICY)
        with self.assertRaises(DatasetUrlError):
            validate_dataset_url(ok, POLICY)

    def test_rejects_bad_configuration(self):
        for env in (
            {"TITILER_ALLOWED_HOSTS": "*.blob.core.windows.net"},
            {"TITILER_ALLOWED_HOSTS": "10.0.0.4"},
            {"TITILER_ALLOWED_HOSTS": "https://x.blob.core.windows.net"},
            {"TITILER_DEV_ALLOWED_ORIGINS": "https://azurite:10000"},
            {"TITILER_DEV_ALLOWED_ORIGINS": "http://azurite"},
        ):
            with self.subTest(env=env):
                with self.assertRaises(ValueError):
                    DatasetUrlPolicy.from_env(env)


def _resolver(*addresses):
    def resolve(host, port, proto=0):
        family = socket.AF_INET6 if ":" in addresses[0] else socket.AF_INET
        return [
            (family, socket.SOCK_STREAM, 6, "", (a, port)) for a in addresses
        ]

    return resolve


class TestCheckDestinationAddresses(unittest.TestCase):
    def test_public_address_passes(self):
        check_destination_addresses(
            "data.source.coop", 443, False, _resolver("104.18.1.1")
        )

    def test_private_address_needs_configured_host(self):
        with self.assertRaises(DatasetUrlError):
            check_destination_addresses(
                "data.source.coop", 443, False, _resolver("10.1.2.3")
            )
        check_destination_addresses(
            STORAGE_HOST, 443, True, _resolver("10.1.2.3")
        )

    def test_blocked_addresses_fail_even_for_configured_hosts(self):
        for addr in (
            "127.0.0.1",
            "169.254.169.254",
            "168.63.129.16",
            "100.100.1.1",
            "0.0.0.0",
            "::1",
            "fe80::1",
            "::ffff:127.0.0.1",
        ):
            with self.subTest(addr=addr):
                with self.assertRaises(DatasetUrlError):
                    check_destination_addresses(
                        STORAGE_HOST, 443, True, _resolver(addr)
                    )

    def test_any_bad_address_fails(self):
        with self.assertRaises(DatasetUrlError):
            check_destination_addresses(
                "data.source.coop",
                443,
                False,
                _resolver("104.18.1.1", "127.0.0.1"),
            )

    def test_unresolvable_host_fails(self):
        def fail(*args, **kwargs):
            raise socket.gaierror("nope")

        with self.assertRaises(DatasetUrlError):
            check_destination_addresses("data.source.coop", 443, False, fail)


def _opener(status=None, error=None):
    opener = MagicMock()
    if error is not None:
        opener.open.side_effect = error
    else:
        response = MagicMock(status=status)
        opener.open.return_value.__enter__.return_value = response
    return opener


class TestDestinationChecker(unittest.TestCase):
    URL = "https://data.source.coop/planet/a.tif"

    def _checker(self, opener, clock=lambda: 0.0):
        return DestinationChecker(
            POLICY,
            resolver=_resolver("104.18.1.1"),
            opener=opener,
            clock=clock,
        )

    def test_direct_response_passes_and_is_cached(self):
        opener = _opener(200)
        checker = self._checker(opener)
        checker.check(self.URL)
        checker.check(self.URL)
        self.assertEqual(opener.open.call_count, 1)
        request = opener.open.call_args[0][0]
        self.assertEqual(request.get_method(), "HEAD")
        self.assertEqual(request.get_header("User-agent"), "haste-titiler")

    def test_cache_expires(self):
        now = [0.0]
        opener = _opener(200)
        checker = self._checker(opener, clock=lambda: now[0])
        checker.check(self.URL)
        now[0] = 601.0
        checker.check(self.URL)
        self.assertEqual(opener.open.call_count, 2)

    def test_redirect_fails(self):
        for code in (301, 302, 303, 307, 308):
            error = urllib.error.HTTPError(
                self.URL, code, "redirect", {"Location": "http://x"}, None
            )
            with self.subTest(code=code):
                with self.assertRaises(DatasetUrlError):
                    self._checker(_opener(error=error)).check(self.URL)

    def test_error_status_fails_and_is_not_cached(self):
        error = urllib.error.HTTPError(self.URL, 403, "no", {}, None)
        opener = _opener(error=error)
        checker = self._checker(opener)
        for _ in range(2):
            with self.assertRaises(DatasetUrlError):
                checker.check(self.URL)
        self.assertEqual(opener.open.call_count, 2)

    def test_network_error_fails(self):
        opener = _opener(error=urllib.error.URLError("down"))
        with self.assertRaises(DatasetUrlError):
            self._checker(opener).check(self.URL)

    def test_private_resolution_fails_before_any_request(self):
        opener = _opener(200)
        checker = DestinationChecker(
            POLICY, resolver=_resolver("10.0.0.5"), opener=opener
        )
        with self.assertRaises(DatasetUrlError):
            checker.check(self.URL)
        opener.open.assert_not_called()

    def test_cache_is_bounded(self):
        checker = self._checker(_opener(200))
        checker.max_entries = 3
        for i in range(5):
            checker.check(f"https://data.source.coop/a{i}.tif")
        self.assertEqual(len(checker._cache), 3)

    def test_real_opener_does_not_follow_redirects(self):
        from api.titilerfuncapi.app.dataset_url import _NoRedirect

        handler = _NoRedirect()
        self.assertIsNone(
            handler.redirect_request(None, None, 302, "", {}, "http://x")
        )


if __name__ == "__main__":
    unittest.main()
