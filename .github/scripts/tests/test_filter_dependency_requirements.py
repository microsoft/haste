import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

import filter_dependency_requirements as filter_script  # noqa: E402


class FilterDependencyRequirementsTests(unittest.TestCase):
    def test_titiler_tests_filter_unpublished_runtime_wheels(self):
        workflow = (
            SCRIPT_DIR.parent / "workflows" / "titiler-tests.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("filter_dependency_requirements.py", workflow)
        self.assertIn("/tmp/titiler-test-requirements.txt", workflow)
        self.assertNotIn(
            "pip install -r api/titilerfuncapi/requirements.txt", workflow
        )

    def test_removes_runtime_owned_bindings_and_keeps_other_dependencies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "requirements.txt"
            output = root / "filtered.txt"
            source.write_text(
                "azure-functions\n"
                "GDAL @ https://example.test/GDAL.whl\n"
                "rasterio==1.4.4\n"
                "Fiona==1.10.1\n"
                "pyogrio==0.13.0\n"
                "pyproj==3.7.2\n"
                "-e ../../hastelib\n"
                "requests==2.34.2\n",
                encoding="utf-8",
            )

            filter_script.filter_requirements(source, output)
            filtered = output.read_text(encoding="utf-8")

        self.assertIn("azure-functions", filtered)
        self.assertIn("requests==2.34.2", filtered)
        for runtime_package in (
            "GDAL",
            "rasterio",
            "Fiona",
            "pyogrio",
            "pyproj",
            "hastelib",
        ):
            self.assertNotIn(runtime_package, filtered)


if __name__ == "__main__":
    unittest.main()
