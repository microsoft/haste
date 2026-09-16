# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Container-contract tests for docker/imageryprep/scripts/set_dirs.sh.

``HASTE_JOB_WORKDIR`` is the provider-neutral canonical variable for the
job's writable working directory. ``AZ_BATCH_TASK_WORKING_DIR`` is preserved
as a legacy alias so already-published images and not-yet-migrated compute
adapters keep working. These tests prove:

* a canonical-only environment (``HASTE_JOB_WORKDIR`` set, legacy unset) and
  a legacy-only environment (``AZ_BATCH_TASK_WORKING_DIR`` set, canonical
  unset) resolve to identical paths and identical on-disk effects
  (CC-001 in spec/features/aml-compute-backend/test-plan.md);
* the script fails fast when neither variable is set.
"""

import os
import platform
import shutil
import subprocess
import tempfile
import unittest

SCRIPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "set_dirs.sh"
)


def _find_bash():
    """Locate a working bash. Prefers Git for Windows' bash on Windows,
    since the stock ``bash.exe`` WSL shim commonly fails without a WSL
    distro installed. Falls back to whatever ``bash`` resolves to on PATH
    (the normal case on Linux/macOS CI runners).
    """
    if platform.system() == "Windows":
        for candidate in (
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
        ):
            if os.path.isfile(candidate):
                return candidate
    return shutil.which("bash")


BASH = _find_bash()


def _to_bash_path(path):
    """Normalize a Windows path (e.g. from tempfile) into a form Git Bash /
    MSYS bash accepts, without changing behavior on POSIX systems.
    """
    return path.replace("\\", "/")


@unittest.skipUnless(BASH, "no usable bash found for shell-script tests")
class TestSetDirsWorkdirResolution(unittest.TestCase):
    def _run(self, work_dir, extra_env, config_contents):
        """Source set_dirs.sh against a config file and report the resolved
        environment plus the post-sed config contents.
        """
        config_path = os.path.join(work_dir, "config.yml")
        with open(config_path, "w") as f:
            f.write(config_contents)

        # Start from the current environment (Windows' MSYS/Git bash needs
        # SYSTEMROOT and friends to function) but make sure the two
        # variables under test are controlled explicitly, not inherited.
        env = dict(os.environ)
        env.pop("HASTE_JOB_WORKDIR", None)
        env.pop("AZ_BATCH_TASK_WORKING_DIR", None)
        env.update(extra_env)

        bash_config_path = _to_bash_path(config_path)
        bash_script_path = _to_bash_path(SCRIPT_PATH)
        wrapper = (
            f'source "{bash_script_path}" "{bash_config_path}" && '
            'echo "HASTE_JOB_WORKDIR=$HASTE_JOB_WORKDIR" && '
            'echo "AZ_BATCH_TASK_WORKING_DIR=$AZ_BATCH_TASK_WORKING_DIR"'
        )
        result = subprocess.run(
            [BASH, "-c", wrapper],
            env=env,
            capture_output=True,
            text=True,
        )
        with open(config_path) as f:
            post_sed_contents = f.read()
        return result, post_sed_contents

    def _parse_vars(self, stdout):
        values = {}
        for line in stdout.splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                values[key] = value
        return values

    def test_canonical_only_environment(self):
        with tempfile.TemporaryDirectory() as work_dir:
            bash_work_dir = _to_bash_path(work_dir)
            result, post_sed = self._run(
                work_dir,
                {"HASTE_JOB_WORKDIR": bash_work_dir},
                "path: AZ_BATCH_TASK_WORKING_DIR/imagery_preprocess/x\n",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            values = self._parse_vars(result.stdout)
            self.assertEqual(values["HASTE_JOB_WORKDIR"], bash_work_dir)
            self.assertEqual(
                values["AZ_BATCH_TASK_WORKING_DIR"], bash_work_dir
            )
            self.assertIn(
                f"path: {bash_work_dir}/imagery_preprocess/x", post_sed
            )

    def test_legacy_only_environment(self):
        with tempfile.TemporaryDirectory() as work_dir:
            bash_work_dir = _to_bash_path(work_dir)
            result, post_sed = self._run(
                work_dir,
                {"AZ_BATCH_TASK_WORKING_DIR": bash_work_dir},
                "path: AZ_BATCH_TASK_WORKING_DIR/imagery_preprocess/x\n",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            values = self._parse_vars(result.stdout)
            self.assertEqual(values["HASTE_JOB_WORKDIR"], bash_work_dir)
            self.assertEqual(
                values["AZ_BATCH_TASK_WORKING_DIR"], bash_work_dir
            )
            self.assertIn(
                f"path: {bash_work_dir}/imagery_preprocess/x", post_sed
            )

    def test_both_set_different_canonical_wins(self):
        """When the two variables disagree, HASTE_JOB_WORKDIR must win and
        AZ_BATCH_TASK_WORKING_DIR must be forced to match it exactly -- a
        stale/divergent legacy value must never survive the script.
        """
        with tempfile.TemporaryDirectory() as canonical_dir, \
                tempfile.TemporaryDirectory() as legacy_dir:
            canonical_bash_dir = _to_bash_path(canonical_dir)
            legacy_bash_dir = _to_bash_path(legacy_dir)
            self.assertNotEqual(canonical_bash_dir, legacy_bash_dir)

            result, post_sed = self._run(
                canonical_dir,
                {
                    "HASTE_JOB_WORKDIR": canonical_bash_dir,
                    "AZ_BATCH_TASK_WORKING_DIR": legacy_bash_dir,
                },
                "path: AZ_BATCH_TASK_WORKING_DIR/imagery_preprocess/x\n",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            values = self._parse_vars(result.stdout)
            self.assertEqual(values["HASTE_JOB_WORKDIR"], canonical_bash_dir)
            self.assertEqual(
                values["AZ_BATCH_TASK_WORKING_DIR"], canonical_bash_dir
            )
            self.assertIn(
                f"path: {canonical_bash_dir}/imagery_preprocess/x", post_sed
            )
            self.assertNotIn(legacy_bash_dir, post_sed)

    def test_canonical_and_legacy_environments_are_deterministically_identical(
        self,
    ):
        """The core compatibility claim: same result regardless of which
        variable name the adapter used.
        """
        with tempfile.TemporaryDirectory() as canonical_dir, \
                tempfile.TemporaryDirectory() as legacy_dir:
            canonical_bash_dir = _to_bash_path(canonical_dir)
            legacy_bash_dir = _to_bash_path(legacy_dir)

            canonical_result, canonical_post_sed = self._run(
                canonical_dir,
                {"HASTE_JOB_WORKDIR": canonical_bash_dir},
                "path: AZ_BATCH_TASK_WORKING_DIR/x\n",
            )
            legacy_result, legacy_post_sed = self._run(
                legacy_dir,
                {"AZ_BATCH_TASK_WORKING_DIR": legacy_bash_dir},
                "path: AZ_BATCH_TASK_WORKING_DIR/x\n",
            )

            canonical_values = self._parse_vars(canonical_result.stdout)
            legacy_values = self._parse_vars(legacy_result.stdout)

            self.assertEqual(
                canonical_values["HASTE_JOB_WORKDIR"],
                canonical_values["AZ_BATCH_TASK_WORKING_DIR"],
            )
            self.assertEqual(
                legacy_values["HASTE_JOB_WORKDIR"],
                legacy_values["AZ_BATCH_TASK_WORKING_DIR"],
            )
            self.assertEqual(
                canonical_post_sed.replace(canonical_bash_dir, "<WORKDIR>"),
                legacy_post_sed.replace(legacy_bash_dir, "<WORKDIR>"),
            )

    def test_neither_variable_set_fails_fast(self):
        with tempfile.TemporaryDirectory() as work_dir:
            result, _ = self._run(work_dir, {}, "path: unused\n")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("neither HASTE_JOB_WORKDIR", result.stderr)


if __name__ == "__main__":
    unittest.main()
