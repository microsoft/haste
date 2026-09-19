# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Exercise the real pinned backend, including metadata prepared before build."""

import ast
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from email.parser import BytesParser
from pathlib import Path

from build import BuildBackendException, ProjectBuilder
from build.env import DefaultIsolatedEnv

HASTELIB_ROOT = Path(__file__).resolve().parents[2]
LOCAL_VERSION = "0.0.0+local"


def source_version(content: str) -> str:
    for node in ast.parse(content).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("Version assignment is missing")


class WheelVersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.environment = cls.enterClassContext(DefaultIsolatedEnv())
        cls.environment.install(
            ProjectBuilder(HASTELIB_ROOT).build_system_requires
        )

    def setUp(self) -> None:
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.project = self.directory / "project"
        self.project.mkdir()
        for name in ("pyproject.toml", "haste_build.py", "README.md"):
            shutil.copy2(HASTELIB_ROOT / name, self.project / name)
        shutil.copytree(
            HASTELIB_ROOT / "src",
            self.project / "src",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        self.version_path = self.project / "src/hastegeo/__about__.py"
        self.original_source = self.version_path.read_text(encoding="utf-8")
        self.override: str | None = None
        self.builder = ProjectBuilder.from_isolated_env(
            self.environment, self.project, runner=self.run_backend
        )

    def run_backend(
        self,
        command: list[str],
        cwd: str | None = None,
        extra_environ: dict[str, str] | None = None,
    ) -> None:
        environment = {
            **os.environ,
            **(extra_environ or {}),
        }
        for name in (
            "HASTE_SET_VERSION",
            "GITHUB_OUTPUT",
            "GH_TOKEN",
            "GITHUB_TOKEN",
        ):
            environment.pop(name, None)
        if self.override is not None:
            environment["HASTE_SET_VERSION"] = self.override
        subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    def assert_wheel_version(
        self, path: str, expected: str, *, editable: bool = False
    ) -> None:
        wheel = Path(path)
        self.assertEqual(wheel.name, f"hastegeo-{expected}-py3-none-any.whl")
        with zipfile.ZipFile(wheel) as archive:
            metadata_paths = [
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/METADATA")
            ]
            self.assertEqual(
                metadata_paths, [f"hastegeo-{expected}.dist-info/METADATA"]
            )
            metadata = BytesParser().parsebytes(
                archive.read(metadata_paths[0])
            )
            self.assertEqual(metadata["Version"], expected)
            if not editable:
                self.assertEqual(
                    source_version(
                        archive.read("hastegeo/__about__.py").decode("utf-8")
                    ),
                    expected,
                )

    def test_rc_and_stable_wheels_have_consistent_versions(self) -> None:
        for version in ("1.0.52rc4", "1.0.52"):
            with self.subTest(version=version):
                self.override = version
                self.assert_wheel_version(
                    self.builder.build("wheel", self.directory / version),
                    version,
                )

    def test_explicit_version_is_canonicalized_before_metadata(self) -> None:
        self.override = " 1.00.52RC04 "
        self.assert_wheel_version(
            self.builder.build("wheel", self.directory / "wheel"),
            "1.0.52rc4",
        )

    def test_prepared_metadata_matches_the_built_wheel(self) -> None:
        self.override = "1.0.52rc4"
        metadata_directory = self.builder.prepare(
            "wheel", self.directory / "metadata"
        )
        self.assertIsNotNone(metadata_directory)
        metadata = BytesParser().parsebytes(
            (Path(metadata_directory) / "METADATA").read_bytes()
        )
        self.assertEqual(metadata["Version"], self.override)
        self.assertEqual(
            self.version_path.read_text(encoding="utf-8"), self.original_source
        )
        wheel = self.builder.build(
            "wheel",
            self.directory / "wheel",
            metadata_directory=metadata_directory,
        )
        self.assert_wheel_version(wheel, self.override)

    def test_local_wheel_keeps_the_committed_version(self) -> None:
        self.assert_wheel_version(
            self.builder.build("wheel", self.directory / "wheel"),
            LOCAL_VERSION,
        )
        self.assertEqual(
            self.version_path.read_text(encoding="utf-8"), self.original_source
        )

    def test_wheel_from_sdist_keeps_version_without_override(self) -> None:
        self.override = "1.0.52rc4"
        sdist = self.builder.build("sdist", self.directory / "dist")
        extracted = self.directory / "extracted"
        with tarfile.open(sdist) as archive:
            archive.extractall(extracted, filter="data")
        builder = ProjectBuilder.from_isolated_env(
            self.environment,
            extracted / f"hastegeo-{self.override}",
            runner=self.run_backend,
        )
        self.override = None
        self.assert_wheel_version(
            builder.build("wheel", self.directory / "wheel"),
            "1.0.52rc4",
        )

    def test_editable_build_keeps_local_source_unchanged(self) -> None:
        self.environment.install(
            self.builder.get_requires_for_build("editable")
        )
        self.assert_wheel_version(
            self.builder.build("editable", self.directory / "wheel"),
            LOCAL_VERSION,
            editable=True,
        )
        self.assertEqual(
            self.version_path.read_text(encoding="utf-8"), self.original_source
        )

    def test_editable_override_does_not_rewrite_source(self) -> None:
        self.override = "1.0.52rc4"
        self.environment.install(
            self.builder.get_requires_for_build("editable")
        )
        self.assert_wheel_version(
            self.builder.build("editable", self.directory / "wheel"),
            self.override,
            editable=True,
        )
        self.assertEqual(
            self.version_path.read_text(encoding="utf-8"), self.original_source
        )

    def test_invalid_override_fails_without_stamping_source(self) -> None:
        for version in ("", "   ", "not-a-version"):
            with self.subTest(version=version):
                self.override = version
                with self.assertRaises(BuildBackendException):
                    self.builder.build("wheel", self.directory / "wheel")
                self.assertEqual(
                    self.version_path.read_text(encoding="utf-8"),
                    self.original_source,
                )
                self.assertFalse(
                    list((self.directory / "wheel").glob("*.whl"))
                )
