import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from check_gdal_hardening import find_violations  # noqa: E402


class GdalHardeningGuardTests(unittest.TestCase):
    def test_hardening_settings_are_persisted_in_each_deployment_surface(self):
        from check_gdal_hardening import REPO_ROOT

        surfaces = (
            "infra/modules/functions.bicep",
            ".github/scripts/deploy_apps.sh",
            "api/hastefuncapi/Dockerfile",
            "api/hastefuncqueues/Dockerfile",
            "docker/docker-compose.yml",
            "docker/imageryprep/Dockerfile",
            "docker/training/Dockerfile",
            "docker/titiler/Dockerfile",
        )
        settings = (
            "GDAL_VRT_ENABLE_RAWRASTERBAND",
            "GDAL_VRT_ENABLE_PYTHON",
            "GDAL_DRIVER_PATH",
            "CPL_VSIL_CURL_HEADER_FILE_KVP_ENABLED",
        )
        for relative_path in surfaces:
            with self.subTest(path=relative_path):
                text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
                for setting in settings:
                    self.assertIn(setting, text)
        titiler_docker = (
            REPO_ROOT / "docker" / "titiler" / "Dockerfile"
        ).read_text(encoding="utf-8")
        self.assertIn('GDAL_SKIP="VRT ', titiler_docker)

    def test_rejects_relaxed_settings(self) -> None:
        values = (
            "GDAL_VRT_ENABLE_RAWRASTERBAND=YES",
            'os.environ["GDAL_VRT_ENABLE_PYTHON"] = "YES"',
            'GDAL_VRT_RAWRASTERBAND_ALLOWED_SOURCE = "ALL"',
            'GDAL_PYTHON_DRIVER_PATH = "/tmp/plugins"',
            'GDAL_DRIVER_PATH = "/tmp/plugins"',
            "CPL_VSIL_CURL_HEADER_FILE_KVP_ENABLED=ONLY_IN_TEMP",
            "CPL_ENABLE_PATH_TRAVERSAL_DETECTION=NO",
            'gdal.SetConfigOption("GDAL_HTTP_UNSAFESSL", "YES")',
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.py"
            path.write_text("\n".join(values), encoding="utf-8")
            violations = find_violations([path])

        self.assertEqual(len(violations), len(values))

    def test_accepts_enforced_values_and_disabled_driver_path(self) -> None:
        lines = (
            "GDAL_VRT_ENABLE_RAWRASTERBAND=NO",
            "GDAL_VRT_ENABLE_PYTHON=NO",
            "GDAL_DRIVER_PATH=disable",
            'GDAL_SKIP="VRT HDF5"',
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.env"
            path.write_text("\n".join(lines), encoding="utf-8")
            self.assertEqual(find_violations([path]), [])

    def test_repository_has_no_relaxed_gdal_configuration(self) -> None:
        from check_gdal_hardening import REPO_ROOT, _candidate_files

        self.assertEqual(find_violations(_candidate_files(REPO_ROOT)), [])


if __name__ == "__main__":
    unittest.main()
