# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Guards against dependency pins that cannot actually be installed.

PR #153 bumped ``gdal`` to 3.13.3 in ``hastelib/pyproject.toml`` while every
container kept installing the prebuilt GDAL **3.9.2** wheel. Because the
Functions images install hastegeo from the local tree (``-e ../../hastelib``),
pip saw ``gdal==3.13.3`` and ``gdal 3.9.2`` at once and failed with
``ResolutionImpossible``. Nothing caught it: the image build is skipped when a
pull request touches ``hastelib/**``, and the wheel build never installs the
images.

The same bump also set ``rasterio==1.5.1``, which requires Python >= 3.12 while
all three images run 3.11. That class of break is caught by the dependency
resolution job in ``.github/workflows/dependency-validation.yml``; the checks
here are the fast, offline half that needs no network.
"""

import json
import re
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_ROOT = REPO_ROOT / ".github" / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))

import check_image_python  # noqa: E402
import check_protobuf_pin  # noqa: E402
import check_react_pins  # noqa: E402

# Every requirements file that installs hastegeo from the local tree and so
# must agree with the pin in pyproject.toml.
REQUIREMENTS_FILES = (
    "api/hastefuncapi/requirements.txt",
    "api/hastefuncqueues/requirements.txt",
    "docker/imageryprep/requirements.txt",
)

DOCKERFILES = (
    "api/hastefuncapi/Dockerfile",
    "api/hastefuncqueues/Dockerfile",
    "docker/imageryprep/Dockerfile",
)

PYPROJECT = "hastelib/pyproject.toml"
AZURE_ML_PIN = "azure-ai-ml==1.34.1"

# GDAL @ https://.../GDAL-3.9.2-cp311-cp311-manylinux...whl
_GDAL_WHEEL_RE = re.compile(
    r"GDAL-(?P<version>\d+\.\d+\.\d+)-cp(?P<py>\d+)-", re.IGNORECASE
)
_PYPROJECT_GDAL_RE = re.compile(r'"gdal==(?P<version>\d+\.\d+\.\d+)"')
_DOCKER_PYTHON_RE = re.compile(r"python(?P<py>3\.\d+)")


def _read(relative_path):
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _pyproject_gdal_version():
    match = _PYPROJECT_GDAL_RE.search(_read(PYPROJECT))
    if match is None:
        raise AssertionError(f"No pinned gdal dependency in {PYPROJECT}")
    return match.group("version")


def _wheel_pins(relative_path):
    """Return ``(version, cpython_tag)`` for the GDAL wheel, or ``None``."""
    for line in _read(relative_path).splitlines():
        match = _GDAL_WHEEL_RE.search(line)
        if match:
            return match.group("version"), match.group("py")
    return None


class GdalPinConsistencyTests(unittest.TestCase):
    """The regression PR #153 introduced, expressed as an invariant."""

    def test_gdal_wheel_matches_the_pyproject_pin(self):
        expected = _pyproject_gdal_version()

        mismatches = []
        for relative_path in REQUIREMENTS_FILES:
            pins = _wheel_pins(relative_path)
            if pins is None:
                mismatches.append(f"{relative_path}: no GDAL wheel pinned")
                continue
            version, _ = pins
            if version != expected:
                mismatches.append(
                    f"{relative_path}: wheel GDAL {version} != "
                    f"{PYPROJECT} gdal=={expected}"
                )

        self.assertEqual(
            [],
            mismatches,
            "The GDAL wheel installed by each image must match the gdal pin "
            "hastegeo declares, or pip cannot resolve the two together.",
        )

    def test_gdal_wheel_targets_the_image_python_version(self):
        """A cp311 wheel cannot be installed on a 3.12 base image."""
        image_pythons = {}
        for relative_path in DOCKERFILES:
            for line in _read(relative_path).splitlines():
                if not line.startswith("FROM "):
                    continue
                match = _DOCKER_PYTHON_RE.search(line)
                if match:
                    image_pythons[relative_path] = match.group("py")
                    break

        self.assertEqual(
            sorted(image_pythons),
            sorted(DOCKERFILES),
            "Could not determine the Python version of every image.",
        )

        mismatches = []
        for dockerfile, requirements in zip(DOCKERFILES, REQUIREMENTS_FILES):
            pins = _wheel_pins(requirements)
            if pins is None:
                continue
            _, wheel_py = pins
            image_py = image_pythons[dockerfile].replace(".", "")
            if wheel_py != image_py:
                mismatches.append(
                    f"{requirements}: GDAL wheel is cp{wheel_py} but "
                    f"{dockerfile} runs Python "
                    f"{image_pythons[dockerfile]}"
                )

        self.assertEqual([], mismatches)


class AzureMlDependencyTests(unittest.TestCase):
    def test_sdk_is_pinned_in_optional_extra_and_test_environment(self):
        pyproject = tomllib.loads(_read(PYPROJECT))

        self.assertEqual(
            [AZURE_ML_PIN],
            pyproject["project"]["optional-dependencies"]["azure-ml"],
        )
        self.assertIn(
            "azure-ml",
            pyproject["tool"]["hatch"]["envs"]["test"]["features"],
        )

    def test_sdk_is_installed_only_in_the_submitting_function_app(self):
        self.assertIn(
            AZURE_ML_PIN,
            _read("api/hastefuncqueues/requirements.txt").splitlines(),
        )
        self.assertNotIn(
            AZURE_ML_PIN,
            _read("api/hastefuncapi/requirements.txt").splitlines(),
        )
        self.assertNotIn(
            AZURE_ML_PIN,
            _read("docker/imageryprep/requirements.txt").splitlines(),
        )

    def test_sdk_is_available_in_the_developer_environment(self):
        self.assertIn(AZURE_ML_PIN, _read("env.yml"))


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


class ImagePythonScriptTests(unittest.TestCase):
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
