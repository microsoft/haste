import unittest
from unittest import mock

import gdal_runtime


class TestSecureGdalRuntime(unittest.TestCase):
    def test_titiler_policy_excludes_vrt(self) -> None:
        self.assertNotIn("VRT", gdal_runtime.ALLOWED_DRIVERS)

    def test_missing_required_runtime_fails_closed(self):
        with (
            mock.patch.dict(
                gdal_runtime.os.environ,
                {"HASTE_GDAL_RUNTIME_REQUIRED": "true"},
            ),
            mock.patch.object(
                gdal_runtime.importlib.util, "find_spec", return_value=None
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "is not installed"):
                gdal_runtime.secure_gdal_runtime()

    def test_installed_runtime_is_configured_before_verification(self):
        calls = []
        runtime = mock.Mock()
        runtime.load_manifest.return_value = {"gdal_release": "3.13.3"}
        runtime.Policy.return_value = object()
        runtime.configure.side_effect = lambda policy: calls.append(
            "configure"
        )
        runtime.secure_startup.side_effect = lambda policy: calls.append(
            "secure_startup"
        ) or {"gdal_release": "3.13.3"}
        with (
            mock.patch.object(
                gdal_runtime.importlib.util, "find_spec", return_value=object()
            ),
            mock.patch.object(
                gdal_runtime.importlib,
                "import_module",
                return_value=runtime,
            ),
        ):
            report = gdal_runtime.secure_gdal_runtime()

        self.assertEqual(calls, ["configure", "secure_startup"])
        self.assertEqual(report, {"gdal_release": "3.13.3"})
        runtime.Policy.assert_called_once_with(
            expected_gdal="3.13.3",
            allowed_drivers=gdal_runtime.ALLOWED_DRIVERS,
            required_bindings=("rasterio",),
        )

    def test_invalid_required_setting_is_rejected(self):
        with mock.patch.dict(
            gdal_runtime.os.environ,
            {"HASTE_GDAL_RUNTIME_REQUIRED": "sometimes"},
        ):
            with self.assertRaisesRegex(ValueError, "boolean value"):
                gdal_runtime.secure_gdal_runtime()


if __name__ == "__main__":
    unittest.main()
