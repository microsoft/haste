import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

import build_function_package as package_builder  # noqa: E402


class FunctionPackageRequirementTests(unittest.TestCase):
    def _wheel(self, directory: Path, name: str, version: str) -> Path:
        normalized = package_builder.normalized_name(name).replace("-", "_")
        path = directory / f"{normalized}-{version}-py3-none-any.whl"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                f"{normalized}-{version}.dist-info/METADATA",
                f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n",
            )
        return path

    def test_replaces_legacy_bindings_with_this_builds_runtime_wheels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel_dir = root / "runtime"
            wheel_dir.mkdir()
            versions = {
                "GDAL": "3.13.3+haste.1",
                "rasterio": "1.4.4+haste.1",
                "fiona": "1.10.1+haste.1",
                "pyogrio": "0.13.0+haste.1",
                "pyproj": "3.7.2+haste.1",
                "haste-gdal-runtime": "3.13.3+haste.1",
            }
            for name, version in versions.items():
                self._wheel(wheel_dir, name, version)
            requirements = root / "requirements.txt"
            requirements.write_text(
                "azure-functions\n"
                "GDAL @ https://example.invalid/GDAL-3.9.2.whl\n"
                "rasterio==1.3.11\n"
                "pyproj==3.6.1\n"
                "pyogrio==0.10.0\n"
                "-e ../../hastelib\n",
                encoding="utf-8",
            )
            hastegeo_wheel = root / "hastegeo-1.0.0-py3-none-any.whl"
            hastegeo_wheel.touch()
            output = root / "resolved.in"

            package_builder.prepare_requirements(
                requirements, output, wheel_dir, hastegeo_wheel
            )
            generated = output.read_text(encoding="utf-8")

            self.assertIn("azure-functions", generated)
            self.assertIn("gdal==3.13.3+haste.1", generated)
            self.assertIn("haste-gdal-runtime==3.13.3+haste.1", generated)
            self.assertIn(hastegeo_wheel.resolve().as_uri(), generated)
            self.assertNotIn("3.9.2", generated)
            self.assertNotIn("1.3.11", generated)
            self.assertNotIn("-e ../../hastelib", generated)

    def test_generated_lock_covers_each_resolved_wheel_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheelhouse = root / "wheelhouse"
            wheelhouse.mkdir()
            wheel = self._wheel(wheelhouse, "attrs", "25.4.0")
            output = root / "requirements.lock"

            package_builder.write_lock(wheelhouse, output)

            expected = (
                f"attrs==25.4.0 --hash=sha256:"
                f"{package_builder.sha256(wheel)}\n"
            )
            self.assertEqual(output.read_text(encoding="utf-8"), expected)


if __name__ == "__main__":
    unittest.main()
