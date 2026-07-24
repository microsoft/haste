# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Hatch build hook for stamping an explicitly resolved hastegeo version.

Version selection and GitHub publication deliberately live outside this hook.
Pull-request source executes the hook while building a wheel, so it must never
receive or use repository write credentials.
"""

import os
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """Stamp the requested version before build and expose the built artifact."""

    PLUGIN_NAME = "haste_build"

    def get_plugin_name(self) -> str:
        return self.PLUGIN_NAME

    def get_plugin_type(self) -> str:
        return "haste_hook"

    def get_plugin_description(self) -> str:
        return "Stamp an explicit hastegeo version before packaging."

    def get_plugin_author(self) -> str:
        return "HASTE Maintainers"

    def get_plugin_license(self) -> str:
        return "MIT"

    def _write_version_file(self, version_str: str) -> None:
        version_path = Path(self.root) / "src" / "hastegeo" / "__about__.py"
        lines = version_path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if line.startswith("__version__"):
                lines[index] = f'__version__ = "{version_str}"'
                break
        else:
            raise RuntimeError(f"__version__ not found in {version_path}")
        version_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Wrote version {version_str} to {version_path}")

    @staticmethod
    def _emit_output(key: str, value: str) -> None:
        print(f"{key}={value}")
        output_path = os.getenv("GITHUB_OUTPUT")
        if output_path:
            with open(output_path, "a", encoding="utf-8") as handle:
                handle.write(f"{key}={value}\n")

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if version == "editable":
            print("Editable build detected; keeping the local source version.")
            return

        explicit_version = os.getenv("HASTE_SET_VERSION")
        if not explicit_version:
            print(
                "HASTE_SET_VERSION is not set; building the committed local "
                f"version {self.metadata.version}."
            )
            return

        explicit_version = explicit_version.strip()
        self.metadata._version = explicit_version
        self._write_version_file(self.metadata.version)
        print(f"Set package version to {self.metadata.version}.")

    def finalize(
        self,
        version: str,
        build_data: dict[str, Any],
        artifact: str,
    ) -> None:
        if version == "editable":
            return

        artifact_path = Path(artifact)
        if not artifact_path.is_file():
            raise RuntimeError(f"Built wheel not found: {artifact_path}")

        self._emit_output("built_version", self.metadata.version)
        self._emit_output("wheel_name", artifact_path.name)
        self._emit_output("wheel_path", str(artifact_path.resolve()))
