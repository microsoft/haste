import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

import prepare_training_runtime_env as prepare_script  # noqa: E402


class PrepareTrainingRuntimeEnvironmentTests(unittest.TestCase):
    def test_rewrites_every_runtime_wheel_url_to_the_local_bundle(self):
        filenames = (
            "haste_gdal_runtime-3.13.3+haste.1-py3-none-manylinux_2_28_x86_64.whl",
            "gdal-3.13.3+haste.1-cp311-cp311-manylinux_2_28_x86_64.whl",
            "rasterio-1.4.4+haste.1-cp311-cp311-manylinux_2_28_x86_64.whl",
            "fiona-1.10.1+haste.1-cp311-cp311-manylinux_2_28_x86_64.whl",
            "pyogrio-0.13.0+haste.1-cp311-cp311-manylinux_2_28_x86_64.whl",
            "pyproj-3.7.2+haste.1-cp311-cp311-manylinux_2_28_x86_64.whl",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel_dir = root / "wheels"
            wheel_dir.mkdir()
            urls = []
            for filename in filenames:
                (wheel_dir / filename).touch()
                urls.append(
                    "https://example.test/" + filename.replace("+", "%2B")
                )
            source = root / "env.yml"
            source.write_text(
                "dependencies:\n  - pip:\n"
                + "".join(f"    - {url}\n" for url in urls),
                encoding="utf-8",
            )
            output = root / "prepared.yml"

            resolved = prepare_script.prepare_environment(
                source, wheel_dir, output
            )
            result = output.read_text(encoding="utf-8")

        self.assertEqual(len(resolved), 6)
        self.assertNotIn("https://example.test/", result)
        self.assertIn("file:///", result)
        self.assertEqual(result.count("file:///"), 6)

    def test_missing_runtime_wheel_fails_instead_of_using_remote_url(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "env.yml"
            source.write_text(
                "dependencies:\n"
                "  - pip:\n"
                "    - https://example.test/gdal-3.13.3+haste.1.whl\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(FileNotFoundError, "gdal-3.13.3"):
                prepare_script.prepare_environment(
                    source, root, root / "out.yml"
                )


if __name__ == "__main__":
    unittest.main()
