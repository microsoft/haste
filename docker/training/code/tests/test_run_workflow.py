# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for the provider-neutral work-directory resolution in
``run_workflow.py``.

``HASTE_JOB_WORKDIR`` is the canonical, provider-neutral variable for the
job's writable working directory. ``AZ_BATCH_TASK_WORKING_DIR`` is preserved
as a legacy alias so already-published images and not-yet-migrated compute
adapters keep working. These tests prove the two environments resolve to
identical paths.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

# The run_workflow module lives in the parent directory and is not installed
# as a package.
CODE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

import run_workflow  # noqa: E402


class TestResolveJobWorkdir(unittest.TestCase):
    """Canonical-only and legacy-only environments must agree."""

    def test_canonical_only(self):
        with mock.patch.dict(
            os.environ,
            {"HASTE_JOB_WORKDIR": "/canonical/workdir"},
            clear=True,
        ):
            self.assertEqual(
                run_workflow._resolve_job_workdir(), "/canonical/workdir"
            )

    def test_legacy_only(self):
        with mock.patch.dict(
            os.environ,
            {"AZ_BATCH_TASK_WORKING_DIR": "/legacy/workdir"},
            clear=True,
        ):
            self.assertEqual(
                run_workflow._resolve_job_workdir(), "/legacy/workdir"
            )

    def test_canonical_and_legacy_agree_on_same_path(self):
        """Deterministic proof: same underlying path, different var names."""
        shared_path = "/shared/workdir"
        with mock.patch.dict(
            os.environ, {"HASTE_JOB_WORKDIR": shared_path}, clear=True
        ):
            canonical_result = run_workflow._resolve_job_workdir()
        with mock.patch.dict(
            os.environ, {"AZ_BATCH_TASK_WORKING_DIR": shared_path}, clear=True
        ):
            legacy_result = run_workflow._resolve_job_workdir()

        self.assertEqual(canonical_result, legacy_result)
        self.assertEqual(canonical_result, shared_path)

    def test_canonical_takes_precedence_when_both_set(self):
        """HASTE_JOB_WORKDIR is read first per the container-scripts contract."""
        with mock.patch.dict(
            os.environ,
            {
                "HASTE_JOB_WORKDIR": "/canonical/workdir",
                "AZ_BATCH_TASK_WORKING_DIR": "/legacy/workdir",
            },
            clear=True,
        ):
            self.assertEqual(
                run_workflow._resolve_job_workdir(), "/canonical/workdir"
            )

    def test_neither_set_falls_back_to_dot(self):
        """Matches the pre-existing default when no adapter var is present."""
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(run_workflow._resolve_job_workdir(), ".")


class TestLogProgressUsesResolvedWorkdir(unittest.TestCase):
    """log_progress() must land in the same place under both variable sets."""

    def _log_dir_for_env(self, tmp_path, env):
        with mock.patch.dict(os.environ, env, clear=True):
            run_workflow.log_progress("hello")
        return os.path.join(tmp_path, "logs", "workflow_progress.log")

    def test_canonical_and_legacy_write_identical_relative_layout(self):
        with tempfile.TemporaryDirectory() as canonical_dir:
            with tempfile.TemporaryDirectory() as legacy_dir:
                canonical_log = self._log_dir_for_env(
                    canonical_dir, {"HASTE_JOB_WORKDIR": canonical_dir}
                )
                legacy_log = self._log_dir_for_env(
                    legacy_dir, {"AZ_BATCH_TASK_WORKING_DIR": legacy_dir}
                )

                self.assertTrue(os.path.isfile(canonical_log))
                self.assertTrue(os.path.isfile(legacy_log))
                # Same relative layout (logs/workflow_progress.log) under
                # each adapter's resolved working directory.
                self.assertTrue(
                    canonical_log.endswith(
                        os.path.join("logs", "workflow_progress.log")
                    )
                )
                self.assertTrue(
                    legacy_log.endswith(
                        os.path.join("logs", "workflow_progress.log")
                    )
                )
                with open(canonical_log) as f:
                    canonical_content = f.read()
                with open(legacy_log) as f:
                    legacy_content = f.read()
                self.assertIn("hello", canonical_content)
                self.assertIn("hello", legacy_content)


if __name__ == "__main__":
    unittest.main()
