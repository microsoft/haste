# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Contract test for the work-directory resolution used by
docker/training/scripts/entrypoint.sh's post-command chmod step.

entrypoint.sh runs the training command in a `bash -c "$FULL_COMMAND"`
*subshell*, so by the time it reaches the chmod step it cannot see any
exports made by set_dirs.sh inside that subshell — it must resolve
HASTE_JOB_WORKDIR / AZ_BATCH_TASK_WORKING_DIR directly from its own
environment. This test extracts the actual resolution expression from
entrypoint.sh (so it can't silently drift from what's tested here) and
proves canonical-only and legacy-only environments resolve identically.
"""

import os
import platform
import re
import shutil
import subprocess
import unittest

ENTRYPOINT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "entrypoint.sh",
)


def _find_bash():
    if platform.system() == "Windows":
        for candidate in (
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
        ):
            if os.path.isfile(candidate):
                return candidate
    return shutil.which("bash")


BASH = _find_bash()


def _extract_resolution_line():
    """Pull the `JOB_WORKDIR=...` assignment straight out of entrypoint.sh
    so this test exercises the real expression, not a hand-copied one.
    """
    with open(ENTRYPOINT_PATH) as f:
        content = f.read()
    match = re.search(r'^JOB_WORKDIR=.*$', content, re.MULTILINE)
    if not match:
        raise AssertionError(
            "Could not find JOB_WORKDIR resolution line in entrypoint.sh; "
            "has it been renamed or removed?"
        )
    return match.group(0)


@unittest.skipUnless(BASH, "no usable bash found for shell-script tests")
class TestEntrypointWorkdirResolution(unittest.TestCase):
    def setUp(self):
        self.resolution_line = _extract_resolution_line()

    def _resolve(self, extra_env):
        env = dict(os.environ)
        env.pop("HASTE_JOB_WORKDIR", None)
        env.pop("AZ_BATCH_TASK_WORKING_DIR", None)
        env.update(extra_env)

        wrapper = f'{self.resolution_line}\necho "JOB_WORKDIR=$JOB_WORKDIR"'
        result = subprocess.run(
            [BASH, "-c", wrapper],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for line in result.stdout.splitlines():
            if line.startswith("JOB_WORKDIR="):
                return line[len("JOB_WORKDIR="):]
        raise AssertionError(f"JOB_WORKDIR not found in output: {result.stdout!r}")

    def test_canonical_only(self):
        self.assertEqual(
            self._resolve({"HASTE_JOB_WORKDIR": "/canonical/dir"}),
            "/canonical/dir",
        )

    def test_legacy_only(self):
        self.assertEqual(
            self._resolve({"AZ_BATCH_TASK_WORKING_DIR": "/legacy/dir"}),
            "/legacy/dir",
        )

    def test_canonical_and_legacy_resolve_identically(self):
        shared = "/shared/dir"
        canonical = self._resolve({"HASTE_JOB_WORKDIR": shared})
        legacy = self._resolve({"AZ_BATCH_TASK_WORKING_DIR": shared})
        self.assertEqual(canonical, legacy)
        self.assertEqual(canonical, shared)

    def test_canonical_takes_precedence_when_both_set(self):
        self.assertEqual(
            self._resolve(
                {
                    "HASTE_JOB_WORKDIR": "/canonical/dir",
                    "AZ_BATCH_TASK_WORKING_DIR": "/legacy/dir",
                }
            ),
            "/canonical/dir",
        )

    def test_neither_set_resolves_empty(self):
        """Unlike set_dirs.sh, entrypoint.sh's chmod is best-effort: an
        empty result means the `if [ -n "$JOB_WORKDIR" ]` guard skips the
        chmod instead of failing the whole container run.
        """
        self.assertEqual(self._resolve({}), "")


if __name__ == "__main__":
    unittest.main()
