# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Guard that every consumer requests the shared GDAL binding versions."""

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_ROOT = REPO_ROOT / ".github" / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))

import check_image_python  # noqa: E402
import check_protobuf_pin  # noqa: E402
import check_react_pins  # noqa: E402

# Every HASTE API or image dependency file that installs the shared runtime.
REQUIREMENTS_FILES = (
    "api/hastefuncapi/requirements.txt",
    "api/hastefuncqueues/requirements.txt",
    "docker/imageryprep/requirements.txt",
    "docker/training/env/env.yml",
)

DOCKERFILES = (
    "api/hastefuncapi/Dockerfile",
    "api/hastefuncqueues/Dockerfile",
    "docker/imageryprep/Dockerfile",
    "docker/titiler/Dockerfile",
)

PYPROJECT = "hastelib/pyproject.toml"

_GDAL_PINS = {
    "gdal": "3.13.3",
    "rasterio": "1.4.4",
    "fiona": "1.10.1",
    "pyogrio": "0.13.0",
    "pyproj": "3.7.2",
}


def _read(relative_path):
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _dependency_pins(text):
    pins = {}
    for line in text.splitlines():
        content = line.strip()
        if content.startswith("- "):
            content = content[2:].lstrip()
        match = re.match(r"['\"]?([A-Za-z0-9_.-]+)==([^\s;\\'\"]+)", content)
        if match:
            pins[re.sub(r"[-_.]+", "-", match.group(1)).lower()] = match.group(
                2
            )
            continue
        match = re.match(
            r"([A-Za-z0-9_.-]+)\s*@\s*https://\S+/([^/\s]+\.whl)",
            content,
            re.IGNORECASE,
        )
        if match:
            name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
            filename = unquote(match.group(2)).lower()
            wheel_prefix = re.escape(name.replace("-", "_"))
            version = re.match(
                rf"{wheel_prefix}-(\d+\.\d+\.\d+)\+haste\.\d+-", filename
            )
            if version:
                pins[name] = version.group(1)
    return pins


class GdalPinConsistencyTests(unittest.TestCase):
    """All GDAL-linked bindings in HASTE must agree on exact versions."""

    def test_every_consumer_pins_the_shared_binding_set(self):
        expected = _GDAL_PINS
        for relative_path in REQUIREMENTS_FILES:
            actual = _dependency_pins(_read(relative_path))
            with self.subTest(requirements=relative_path):
                self.assertEqual(
                    expected,
                    {name: actual.get(name) for name in expected},
                    f"{relative_path} must pin the same GDAL runtime bindings.",
                )

    def test_hastegeo_metadata_pins_the_same_binding_versions(self):
        actual = _dependency_pins(_read(PYPROJECT))
        self.assertEqual(
            _GDAL_PINS,
            {name: actual.get(name) for name in _GDAL_PINS},
        )

    def test_training_conda_environment_uses_python_311_and_no_conda_gdal(
        self,
    ):
        text = _read("docker/training/env/env.yml")
        self.assertIn("python=3.11", text)
        self.assertNotRegex(text, r"(?m)^\s*-\s*gdal\s*[<=>]")

    def test_consumer_wheel_urls_match_the_locked_runtime_build(self):
        lock = _read("native/gdal-runtime/sources.lock")
        build_match = re.search(r"(?m)^HASTE_GDAL_BUILD\s+(\d+)\s*$", lock)
        self.assertIsNotNone(build_match)
        expected_build = build_match.group(1)
        all_bindings = {
            "gdal",
            "rasterio",
            "fiona",
            "pyogrio",
            "pyproj",
            "haste-gdal-runtime",
        }
        consumer_files = (
            *REQUIREMENTS_FILES,
            "api/titilerfuncapi/requirements.txt",
        )
        for relative_path in consumer_files:
            text = _read(relative_path)
            names = {
                re.sub(r"[-_.]+", "-", name).lower()
                for name in re.findall(
                    r"(?im)^\s*-?\s*([A-Za-z0-9_.-]+)\s*@\s*https://",
                    text,
                )
            }
            expected = (
                {"haste-gdal-runtime", "rasterio"}
                if relative_path.endswith("titilerfuncapi/requirements.txt")
                else all_bindings
            )
            with self.subTest(requirements=relative_path):
                self.assertEqual(expected, names)
                self.assertEqual(
                    {expected_build},
                    set(re.findall(r"\+haste\.(\d+)", unquote(text))),
                )
                filenames = []
                for line in text.splitlines():
                    match = re.match(
                        r"^\s*-?\s*([A-Za-z0-9_.-]+)\s*@\s*(https://\S+)",
                        line,
                    )
                    if not match:
                        continue
                    name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
                    if name in expected:
                        filenames.append(
                            Path(unquote(urlsplit(match.group(2)).path)).name
                        )
                for filename in filenames:
                    if filename.startswith("haste_gdal_runtime-"):
                        self.assertIn(
                            "py3-none-manylinux_2_28_x86_64.whl", filename
                        )
                    else:
                        self.assertIn(
                            "cp311-cp311-manylinux_2_28_x86_64.whl",
                            filename,
                        )

    def test_function_and_geospatial_images_use_python_311(self):
        for relative_path in DOCKERFILES:
            version = check_image_python.base_python_version(
                _read(relative_path)
            )
            with self.subTest(dockerfile=relative_path):
                self.assertEqual("3.11", version)


def _write(directory, name, payload):
    path = Path(directory) / name
    if isinstance(payload, (dict, list)):
        path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        path.write_text(payload, encoding="utf-8")
    return path


def _pip_report(*packages):
    return {
        "install": [
            {"metadata": {"name": name, "version": version}}
            for name, version in packages
        ]
    }


class ProtobufPinScriptTests(unittest.TestCase):
    """The pin that keeps the Functions worker able to index at all."""

    def test_worker_compatible_protobuf_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _write(
                directory,
                "report.json",
                _pip_report(("protobuf", "5.29.6"), ("azure-core", "1.41.0")),
            )
            self.assertEqual(0, check_protobuf_pin.main([str(path)]))

    def test_protobuf_six_and_above_fails(self):
        # tensorboard 2.21 requires >=6.31.1, which is how 7 arrived.
        for version in ("6.31.1", "7.36.0"):
            with self.subTest(version=version):
                with tempfile.TemporaryDirectory() as directory:
                    path = _write(
                        directory,
                        "report.json",
                        _pip_report(("protobuf", version)),
                    )
                    self.assertEqual(1, check_protobuf_pin.main([str(path)]))

    def test_absent_protobuf_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _write(
                directory, "report.json", _pip_report(("requests", "2.34.2"))
            )
            self.assertEqual(0, check_protobuf_pin.main([str(path)]))

    def test_name_matching_ignores_case(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _write(
                directory, "report.json", _pip_report(("Protobuf", "7.36.0"))
            )
            self.assertEqual(1, check_protobuf_pin.main([str(path)]))

    def test_missing_or_malformed_report_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "nope.json"
            self.assertEqual(2, check_protobuf_pin.main([str(missing)]))
            bad = _write(directory, "bad.json", "{not json")
            self.assertEqual(2, check_protobuf_pin.main([str(bad)]))


class ReactPinScriptTests(unittest.TestCase):
    def test_matching_majors_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _write(
                directory,
                "package.json",
                {
                    "dependencies": {
                        "react": "^18.3.1",
                        "react-dom": "^18.3.1",
                    },
                    "devDependencies": {
                        "@types/react": "^18.3.3",
                        "@types/react-dom": "^18.3.0",
                    },
                },
            )
            self.assertEqual(0, check_react_pins.main([str(path)]))

    def test_the_regression_is_caught(self):
        """react 19 with react-dom 18 -- exactly what shipped."""
        with tempfile.TemporaryDirectory() as directory:
            path = _write(
                directory,
                "package.json",
                {
                    "dependencies": {
                        "react": "^19.2.8",
                        "react-dom": "^18.3.1",
                    }
                },
            )
            self.assertEqual(1, check_react_pins.main([str(path)]))

    def test_types_mismatch_is_caught(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _write(
                directory,
                "package.json",
                {
                    "devDependencies": {
                        "@types/react": "^19.2.18",
                        "@types/react-dom": "^18.3.0",
                    }
                },
            )
            self.assertEqual(1, check_react_pins.main([str(path)]))

    def test_absent_packages_are_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _write(directory, "package.json", {"dependencies": {}})
            self.assertEqual(0, check_react_pins.main([str(path)]))

    def test_the_repository_itself_passes(self):
        self.assertEqual(
            0,
            check_react_pins.main([str(REPO_ROOT / "ui" / "package.json")]),
        )


class ImageryBuildCompatibilityTests(unittest.TestCase):
    def test_pip_install_remains_compatible_with_acr_quick_build(self) -> None:
        dockerfile = _read("docker/imageryprep/Dockerfile")

        self.assertNotRegex(dockerfile, r"(?m)^RUN\s+--mount=")
        self.assertIn("RUN python -m pip install --no-cache-dir", dockerfile)
        self.assertIn("&& python -m pip check", dockerfile)

    def test_local_index_override_has_no_default_or_runtime_setting(
        self,
    ) -> None:
        dockerfile = _read("docker/imageryprep/Dockerfile")

        self.assertRegex(dockerfile, r"(?m)^ARG PIP_INDEX_URL$")
        self.assertNotRegex(dockerfile, r"(?m)^ENV\s+PIP_INDEX_URL(?:=|\s)")


class ImagePythonScriptTests(unittest.TestCase):
    def test_unrelated_image_names_fail_the_python_guard(self) -> None:
        for image in (
            "copy311-runtime",
            "cpython3.11-base",
            "notpython3.11-runtime",
            "numpy311-base",
        ):
            with self.subTest(image=image):
                text = f"FROM example.com/{image}:latest\n"
                self.assertIsNone(check_image_python.base_python_version(text))
                with tempfile.TemporaryDirectory() as directory:
                    path = _write(directory, "Dockerfile", text)
                    self.assertEqual(
                        1, check_image_python.main([str(path), "3.11"])
                    )

    def test_mcr_python_reference_formats(self) -> None:
        cases = (
            ("azureml/curated/minimal-py311-inference:59", "3.11"),
            ("azureml/curated/minimal-py312-inference:10", "3.12"),
            ("azureml/minimal-ubuntu22.04-py39-cpu-inference:latest", "3.9"),
            ("devcontainers/python:3.11-bookworm", "3.11"),
            ("azurelinux/base/python:3.12", "3.12"),
            ("azure-functions/python:4-python3.11-slim", "3.11"),
        )
        for image, version in cases:
            with self.subTest(image=image):
                self.assertEqual(
                    version,
                    check_image_python.base_python_version(
                        f"FROM mcr.microsoft.com/{image}"
                    ),
                )

    def test_digest_does_not_change_the_python_version(self) -> None:
        self.assertEqual(
            "3.11",
            check_image_python.base_python_version(
                "FROM mcr.microsoft.com/azureml/curated/"
                "minimal-py311-inference:59@sha256:" + "a" * 64
            ),
        )

    def test_platform_selector_keeps_the_python_version_readable(self) -> None:
        self.assertEqual(
            "3.11",
            check_image_python.base_python_version(
                "FROM --platform=linux/amd64 mcr.microsoft.com/azureml/"
                "curated/minimal-py311-inference:59 AS runtime"
            ),
        )

    def test_compact_mcr_version_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = _write(
                directory,
                "Dockerfile",
                "FROM mcr.microsoft.com/azureml/curated/"
                "minimal-py312-inference:latest\n",
            )
            self.assertEqual(1, check_image_python.main([str(path), "3.11"]))

    def test_matching_version_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _write(
                directory,
                "Dockerfile",
                "FROM mcr.microsoft.com/azure-functions/"
                "python:4-python3.11-slim\nRUN true\n",
            )
            self.assertEqual(0, check_image_python.main([str(path), "3.11"]))

    def test_drifted_base_image_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _write(
                directory,
                "Dockerfile",
                "FROM mcr.microsoft.com/azure-functions/python:4-python3.12\n",
            )
            self.assertEqual(1, check_image_python.main([str(path), "3.11"]))

    def test_base_without_a_python_tag_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _write(directory, "Dockerfile", "FROM debian:bookworm\n")
            self.assertEqual(1, check_image_python.main([str(path), "3.11"]))

    def test_every_validated_image_matches_its_matrix_entry(self):
        """The workflow matrix and the real Dockerfiles must agree."""
        for dockerfile in DOCKERFILES:
            with self.subTest(dockerfile=dockerfile):
                self.assertEqual(
                    0,
                    check_image_python.main(
                        [str(REPO_ROOT / dockerfile), "3.11"]
                    ),
                )


if __name__ == "__main__":
    unittest.main()
