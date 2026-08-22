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

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

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


if __name__ == "__main__":
    unittest.main()
