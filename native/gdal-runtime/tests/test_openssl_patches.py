import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import apply_openssl_patches  # noqa: E402
from haste_gdal_runtime import __main__ as runtime_cli  # noqa: E402
from verify_build_manifest import validate  # noqa: E402


class OpenSslPatchTests(unittest.TestCase):
    def test_locked_fixes_cover_all_reported_openssl_cves(self):
        patches = apply_openssl_patches.load_patches(
            apply_openssl_patches.PATCH_LOCK
        )
        self.assertEqual(
            {
                patch["cve"]
                for patch in patches
                if patch["kind"] in {"fix", "fix-and-test"}
            },
            {
                "CVE-2026-88822",
                "CVE-2026-88823",
                "CVE-2026-95691",
                "CVE-2026-95692",
                "CVE-2026-107496",
            },
        )

    def test_tampered_cached_patch_fails_before_application(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            patches = apply_openssl_patches.load_patches(
                apply_openssl_patches.PATCH_LOCK
            )
            for entry in patches:
                (root / f"{entry['commit']}.patch").write_bytes(b"tampered")
            with patch.object(
                apply_openssl_patches.subprocess, "run"
            ) as apply, self.assertRaisesRegex(ValueError, "sha256"):
                apply_openssl_patches.apply_patches(
                    root, root, root / "report.json"
                )
            apply.assert_not_called()
            self.assertFalse((root / "report.json").exists())

    def test_failed_patch_does_not_produce_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.object(
                apply_openssl_patches, "fetch", return_value=[]
            ), patch.object(
                apply_openssl_patches.subprocess,
                "run",
                side_effect=subprocess.CalledProcessError(1, "patch"),
            ), self.assertRaises(
                subprocess.CalledProcessError
            ):
                apply_openssl_patches.apply_patches(
                    root, root, root / "report.json"
                )
            self.assertFalse((root / "report.json").exists())

    def test_existing_patch_report_is_never_reused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = root / "report.json"
            report.write_text("stale", encoding="utf-8")
            with patch.object(
                apply_openssl_patches, "fetch"
            ) as fetch, self.assertRaises(FileExistsError):
                apply_openssl_patches.apply_patches(root, root, report)
            fetch.assert_not_called()
            self.assertEqual(report.read_text(encoding="utf-8"), "stale")

    def test_manifest_records_applied_patch_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            patch_report = root / "patches.json"
            patch_report.write_text(
                json.dumps([{"cve": "CVE-2026-88823"}]),
                encoding="utf-8",
            )
            native = Mock()
            native.build_info.return_value = {"PROJ_RUNTIME_VERSION": "9.8.1"}
            native.version_info.return_value = "3.13.3"
            native.drivers.return_value = []
            native.vsi_prefixes.return_value = []
            native.driver_metadata.return_value = "NO"
            native.probes.return_value = {}
            args = SimpleNamespace(
                library="libgdal.so",
                output=str(root / "manifest.json"),
                patch_report=str(patch_report),
            )
            with patch.object(runtime_cli, "NativeGdal", return_value=native):
                runtime_cli._manifest(args)
            manifest = json.loads((root / "manifest.json").read_text())
            self.assertEqual(
                manifest["openssl_patches"], [{"cve": "CVE-2026-88823"}]
            )

    def test_build_manifest_rejects_missing_or_different_patch_evidence(self):
        expected = [{"cve": "CVE-2026-88823", "commit": "expected"}]
        for actual in (None, [], [{"cve": "CVE-2026-88823"}]):
            with self.subTest(actual=actual):
                errors = validate({"openssl_patches": actual}, expected)
                self.assertIn(
                    "OpenSSL patch evidence differs from the patch lock",
                    errors,
                )


if __name__ == "__main__":
    unittest.main()
