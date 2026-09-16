# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Acceptance check for plan.md Phase 8's exit criterion:

    rg "get_azure_batch_config|AZ_BATCH_" \\
        hastelib/src/hastegeo/core/processors

must return no matches — no processor may read Azure Batch configuration
or a provider-specific work-directory variable once every workload builds a
``ComputeJobSpec`` and submits through ``ComputeExecutionService``.

Implemented as a test (rather than a shell grep in CI only) so a
regression fails the suite in every environment, with no ripgrep
dependency.
"""

import pathlib
import re
import unittest

import hastegeo.core.processors as processors_package

PROCESSORS_DIR = pathlib.Path(processors_package.__file__).parent

#: The exact pattern from plan.md's exit criterion.
FORBIDDEN = re.compile(r"get_azure_batch_config|AZ_BATCH_")

#: Legacy Batch-shaped runner entry points; no processor may drive a job
#: through them any more (design.md#lifecycle-dispatch).
LEGACY_RUNNER_CALLS = re.compile(
    r"\bUnifiedRunner\b|\bresource_files_for_upload\b|"
    r"\b(add_task|cleanup_task|cancel_task|get_task_status|"
    r"get_filecontent_from_task)\s*\("
)


def _processor_sources():
    for path in sorted(PROCESSORS_DIR.glob("*.py")):
        yield path, path.read_text(encoding="utf-8")


class TestProcessorsAreBackendNeutral(unittest.TestCase):
    def test_no_processor_reads_azure_batch_configuration(self):
        offenders = []
        for path, source in _processor_sources():
            for number, line in enumerate(source.splitlines(), start=1):
                if FORBIDDEN.search(line):
                    offenders.append(f"{path.name}:{number}: {line.strip()}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_no_processor_uses_the_legacy_runner_lifecycle(self):
        offenders = []
        for path, source in _processor_sources():
            for number, line in enumerate(source.splitlines(), start=1):
                if LEGACY_RUNNER_CALLS.search(line):
                    offenders.append(f"{path.name}:{number}: {line.strip()}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_the_check_actually_scans_the_migrated_processors(self):
        names = {path.name for path, _ in _processor_sources()}
        for expected in (
            "train.py",
            "inference.py",
            "embedding.py",
            "imagery.py",
            "artifacts.py",
        ):
            self.assertIn(expected, names)

    def test_every_workload_processor_builds_a_spec(self):
        builders = {
            "train.py": "def build_training_job_spec(",
            "inference.py": "def build_inference_job_spec(",
            "embedding.py": "def build_embedding_job_spec(",
            "imagery.py": "def build_imagery_job_spec(",
            "artifacts.py": "def build_artifact_zip_job_spec(",
        }
        sources = {path.name: source for path, source in _processor_sources()}
        for name, builder in builders.items():
            with self.subTest(processor=name):
                self.assertIn(builder, sources[name])
                # ...and submits it through the execution service.
                self.assertIn("execution_service.submit(", sources[name])


if __name__ == "__main__":
    unittest.main()
