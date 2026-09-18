# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import email
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from hatchling.builders.wheel import WheelBuilder

HASTELIB_ROOT = Path(__file__).resolve().parents[2]


class WheelVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in ("pyproject.toml", "haste_build.py", "README.md"):
            shutil.copyfile(HASTELIB_ROOT / name, self.root / name)
        self.package = self.root / "src" / "hastegeo"
        self.package.mkdir(parents=True)
        self.about = self.package / "__about__.py"
        self.about.write_text('__version__ = "0.0.0+local"\n')
        (self.package / "__init__.py").write_text("")
        environment = dict(os.environ)
        environment.pop("HASTE_SET_VERSION", None)
        environment.pop("GITHUB_OUTPUT", None)
        self.environment = patch.dict(os.environ, environment, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def build(self, target: str = "standard") -> Path:
        builder = WheelBuilder(str(self.root))
        # Hatchling validates/caches metadata before build hooks initialize.
        builder.metadata.validate_fields()
        _ = builder.metadata.core.version
        explicit = os.getenv("HASTE_SET_VERSION")
        if explicit:
            self.assertEqual(builder.metadata.version, explicit.strip())
        artifacts = list(
            builder.build(directory=str(self.root / "dist"), versions=[target])
        )
        self.assertEqual(len(artifacts), 1)
        return Path(artifacts[0])

    def assert_wheel_version(self, wheel: Path, expected: str) -> None:
        self.assertEqual(wheel.name, f"hastegeo-{expected}-py3-none-any.whl")
        with zipfile.ZipFile(wheel) as archive:
            metadata = email.message_from_bytes(
                archive.read(f"hastegeo-{expected}.dist-info/METADATA")
            )
            self.assertEqual(metadata["Version"], expected)
            self.assertIn(
                f'__version__ = "{expected}"',
                archive.read("hastegeo/__about__.py").decode(),
            )

    def test_rc_and_stable_versions_match_filename_metadata_and_source(
        self,
    ) -> None:
        for version in ("1.0.52rc2", "1.0.52"):
            with self.subTest(version=version):
                self.about.write_text('__version__ = "0.0.0+local"\n')
                os.environ["HASTE_SET_VERSION"] = version

                self.assert_wheel_version(self.build(), version)

    def test_default_wheel_keeps_the_committed_local_version(self) -> None:
        self.assert_wheel_version(self.build(), "0.0.0+local")

    def test_editable_build_does_not_rewrite_the_source_version(self) -> None:
        original = self.about.read_bytes()
        builder = WheelBuilder(str(self.root))
        for hook in builder.get_build_hooks(str(self.root / "dist")).values():
            hook.initialize("editable", {})

        self.assertEqual(self.about.read_bytes(), original)
        self.assertEqual(builder.metadata.version, "0.0.0+local")

    def test_invalid_override_fails_before_rewriting_source(self) -> None:
        original = self.about.read_bytes()
        os.environ["HASTE_SET_VERSION"] = "not a version"

        with self.assertRaises(ValueError):
            self.build()

        self.assertEqual(self.about.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
