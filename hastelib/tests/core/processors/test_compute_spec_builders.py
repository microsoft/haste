# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Deterministic tests for the five workload ``ComputeJobSpec`` builders.

One builder per workload (training, inference, embedding, imagery
preparation, artifact packaging). These tests pin the parts that must not
drift: the work-directory contract in commands, HASTE's
``<project-hash>/<task-id>`` output prefix and destination URIs, the
input/output shapes, live-mount selection where HASTE reads progress while
a job runs, the AML environment reference, and the CPU-capable artifact
packaging request.

See spec/features/aml-compute-backend/plan.md Phase 8.
"""

import os
import platform
import shutil
import subprocess
import tempfile
import unittest
from fnmatch import fnmatch
from unittest.mock import patch

from hastegeo.core.config import Config
from hastegeo.core.models.compute import (
    ComputeBackend,
    ComputeWorkload,
    InputKind,
    OutputPersistenceMode,
)
from hastegeo.core.models.projects import ImageLayer, Model, ModelArtifacts
from hastegeo.core.processors.artifacts import (
    MERGE_DIR,
    STAGE_DIR,
    build_artifact_zip_job_spec,
)
from hastegeo.core.processors.embedding import build_embedding_job_spec
from hastegeo.core.processors.imagery import build_imagery_job_spec
from hastegeo.core.processors.inference import build_inference_job_spec
from hastegeo.core.processors.train import build_training_job_spec
from hastegeo.core.utils.compute_specs import output_prefix
from hastegeo.core.utils.metadata import MetadataUtils

PROJECT_ID = "proj-1"
PROJECT_HASH = MetadataUtils.hash_string(PROJECT_ID)
CONTAINER_URL = "https://acct.blob.core.windows.net/data"


def _find_bash():
    """Locate a usable bash for shell-fragment tests (see the same helper
    in docker/*/scripts/tests). Prefers Git for Windows' bash, since the
    stock ``bash.exe`` shim needs a WSL distro."""
    if platform.system() == "Windows":
        for candidate in (
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
        ):
            if os.path.isfile(candidate):
                return candidate
    return shutil.which("bash")


BASH = _find_bash()


def _covered_live(spec, workspace_path):
    """True when a live-mounted declared output covers ``workspace_path``.

    Ties a spec's declared outputs to the file a processor actually reads:
    a log the processor streams must be inside a declared output — and a
    live-mounted one — or a backend that binds outputs statically (Azure
    ML) never makes it durable.
    """
    return any(
        fnmatch(workspace_path, output.sourceRelativePattern)
        and output.persistenceMode == OutputPersistenceMode.LIVE_MOUNT
        for output in spec.outputs
    )


def _config():
    return Config()


def _runtime_env(**extra):
    env = {
        "COMPUTE_OUTPUT_CONTAINER_URL": CONTAINER_URL,
        "COMPUTE_IMAGE_TRAINING": "acr.example.io/haste-training:v2",
        "COMPUTE_IMAGE_IMAGERYPREP": "acr.example.io/haste-imageryprep:v2",
        "COMPUTE_BACKEND_DEFAULT": "azure_batch",
    }
    env.update(extra)
    return patch.dict("os.environ", env, clear=False)


def _model(**overrides):
    values = {
        "modelId": "42",
        "projectId": PROJECT_ID,
        "imageLayerId": "layer-1",
        "name": "damage-model",
    }
    values.update(overrides)
    return Model(**values)


def _image_layer(**overrides):
    values = {"imageLayerId": "layer-1", "projectId": PROJECT_ID}
    values.update(overrides)
    return ImageLayer(**values)


def _training_inputs():
    return {
        "labels": {
            "http_url": "https://acct.blob.core.windows.net/data/l.geojson",
            "file_path": "inputs/l.geojson",
        },
        "raw_cog_image": {
            "http_url": "https://acct.blob.core.windows.net/data/raw.tif",
            "file_path": "inputs/raw.tif",
        },
        "config": {
            "http_url": "https://acct.blob.core.windows.net/data/c.yaml",
            "file_path": "inputs/c.yaml",
        },
    }


class TestTrainingSpec(unittest.TestCase):
    def _build(self, **kwargs):
        with _runtime_env():
            return build_training_job_spec(
                model=_model(),
                execution_id="trn-1",
                input_files=_training_inputs(),
                config=_config(),
                **kwargs,
            )

    def test_command_uses_the_canonical_workdir_only(self):
        spec = self._build()
        self.assertIn("$HASTE_JOB_WORKDIR/inputs/c.yaml", spec.command)
        self.assertNotIn("AZ_BATCH", spec.command)
        self.assertIn("--step training", spec.command)

    def test_inputs_map_one_to_one_to_their_destinations(self):
        spec = self._build()
        destinations = {i.destinationRelativePath for i in spec.inputs}
        self.assertEqual(
            destinations,
            {"inputs/l.geojson", "inputs/raw.tif", "inputs/c.yaml"},
        )
        self.assertTrue(all(i.kind == InputKind.FILE for i in spec.inputs))

    def test_output_keeps_the_existing_haste_prefix_and_is_live(self):
        spec = self._build()
        self.assertEqual(len(spec.outputs), 1)
        output = spec.outputs[0]
        self.assertEqual(output.sourceRelativePattern, "**/*")
        self.assertEqual(
            output.destinationUri, f"{CONTAINER_URL}/{PROJECT_HASH}/trn-1"
        )
        # TensorBoard events/progress are read while the job runs.
        self.assertEqual(
            output.persistenceMode, OutputPersistenceMode.LIVE_MOUNT
        )

    def test_gpu_resources_and_timeout_come_from_configuration(self):
        with _runtime_env(COMPUTE_TIMEOUT_SECONDS_TRAINING="7200"):
            spec = build_training_job_spec(
                model=_model(),
                execution_id="trn-1",
                input_files=_training_inputs(),
                config=_config(),
            )
        self.assertEqual(spec.resources.accelerator, "gpu")
        self.assertEqual(spec.resources.sharedMemoryMb, 32768)
        self.assertEqual(spec.timeoutSeconds, 7200)

    def test_environment_reference_is_set_when_configured(self):
        with _runtime_env(AML_ENVIRONMENT_TRAINING="haste-training:9"):
            spec = build_training_job_spec(
                model=_model(),
                execution_id="trn-1",
                input_files=_training_inputs(),
                config=_config(),
            )
        self.assertEqual(
            spec.container.environmentReference, "haste-training:9"
        )

    def test_backend_preference_resolution_order(self):
        explicit = self._build(backend=ComputeBackend.LOCAL)
        self.assertEqual(explicit.backendPreference, ComputeBackend.LOCAL)

        with _runtime_env(COMPUTE_BACKEND_TRAINING="azure_ml"):
            override = build_training_job_spec(
                model=_model(),
                execution_id="trn-1",
                input_files=_training_inputs(),
                config=_config(),
            )
        self.assertEqual(override.backendPreference, ComputeBackend.AZURE_ML)

    def test_tags_carry_workload_identity(self):
        spec = self._build()
        self.assertEqual(spec.tags.workload, ComputeWorkload.TRAINING)
        self.assertEqual(spec.tags.model, "42")
        self.assertEqual(spec.tags.task, "trn-1")
        self.assertEqual(spec.workload, ComputeWorkload.TRAINING)


class TestInferenceSpec(unittest.TestCase):
    def _build(self, **kwargs):
        with _runtime_env():
            return build_inference_job_spec(
                model=_model(),
                execution_id="inf-1",
                input_files=_training_inputs(),
                config=_config(),
                gdal_translate_params="BIGTIFF=YES",
                **kwargs,
            )

    def test_command_runs_the_inference_step_under_the_workdir(self):
        spec = self._build()
        self.assertIn("--step inference", spec.command)
        self.assertIn("$HASTE_JOB_WORKDIR/inputs/c.yaml", spec.command)
        self.assertNotIn("AZ_BATCH", spec.command)

    def test_output_pattern_and_prefix_are_unchanged(self):
        spec = self._build()
        patterns = [output.sourceRelativePattern for output in spec.outputs]
        self.assertEqual(
            patterns,
            ["inference/**/*", "logs/*.*"],
        )
        for output in spec.outputs:
            self.assertEqual(
                output.destinationUri,
                f"{CONTAINER_URL}/{PROJECT_HASH}/inf-1",
            )
            self.assertEqual(
                output.persistenceMode, OutputPersistenceMode.LIVE_MOUNT
            )

    def test_gdal_parameters_travel_as_non_secret_environment(self):
        spec = self._build()
        self.assertEqual(
            spec.environment, {"GDAL_TRANSLATE_PARAMS": "BIGTIFF=YES"}
        )

    def test_uses_the_training_image_family(self):
        spec = self._build()
        self.assertEqual(
            spec.container.imageReference, "acr.example.io/haste-training:v2"
        )

    def test_declared_outputs_cover_the_progress_log_that_is_read(self):
        # run_workflow.py writes logs/workflow_progress.log, and
        # InferencePostprocessor reads it while the job runs and again for
        # failure detail. A backend with a static output layout only makes
        # it durable if a declared, live-mounted output covers it.
        spec = self._build()
        self.assertTrue(
            _covered_live(spec, "logs/workflow_progress.log"),
            [o.sourceRelativePattern for o in spec.outputs],
        )


class TestEmbeddingSpec(unittest.TestCase):
    def _build(self, **kwargs):
        with _runtime_env():
            return build_embedding_job_spec(
                model=_model(),
                execution_id="emb-1",
                input_files=_training_inputs(),
                config=_config(),
                **kwargs,
            )

    def test_command_creates_and_enters_the_workdir(self):
        spec = self._build()
        self.assertIn("mkdir -p $HASTE_JOB_WORKDIR", spec.command)
        self.assertIn("cd $HASTE_JOB_WORKDIR", spec.command)
        self.assertIn("embed-buildings --config", spec.command)
        self.assertNotIn("AZ_BATCH", spec.command)

    def test_outputs_directory_is_preserved(self):
        spec = self._build()
        patterns = [output.sourceRelativePattern for output in spec.outputs]
        self.assertEqual(patterns, ["outputs/*.*", "logs/*.*"])
        for output in spec.outputs:
            self.assertEqual(
                output.destinationUri,
                f"{CONTAINER_URL}/{PROJECT_HASH}/emb-1",
            )
            self.assertEqual(
                output.persistenceMode, OutputPersistenceMode.LIVE_MOUNT
            )

    def test_runs_on_gpu_with_the_training_image(self):
        spec = self._build()
        self.assertEqual(spec.resources.accelerator, "gpu")
        self.assertEqual(
            spec.container.imageReference, "acr.example.io/haste-training:v2"
        )

    def test_declared_outputs_cover_the_friendly_log_that_is_read(self):
        # embed_buildings writes logs/embedding_friendly.log, which
        # EmbeddingPostprocessor surfaces in the status message.
        spec = self._build()
        self.assertTrue(
            _covered_live(spec, "logs/embedding_friendly.log"),
            [o.sourceRelativePattern for o in spec.outputs],
        )


class TestImagerySpec(unittest.TestCase):
    def _build(self, **kwargs):
        with _runtime_env():
            return build_imagery_job_spec(
                image_layer=_image_layer(),
                execution_id="img-1",
                input_files={
                    "config": {
                        "http_url": "https://acct/c/imagery.yaml",
                        "file_path": "imagery.yaml",
                    }
                },
                config=_config(),
                **kwargs,
            )

    def test_command_invokes_prepare_imagery_under_the_workdir(self):
        spec = self._build()
        self.assertIn(
            "prepare-imagery --config $HASTE_JOB_WORKDIR/imagery.yaml",
            spec.command,
        )
        self.assertNotIn("AZ_BATCH", spec.command)

    def test_both_outputs_and_logs_are_persisted(self):
        spec = self._build()
        patterns = [o.sourceRelativePattern for o in spec.outputs]
        self.assertIn("outputs/*.*", patterns)
        # Without this the progress log only ever exists on the node.
        self.assertIn("logs/*.*", patterns)
        for output in spec.outputs:
            self.assertEqual(
                output.destinationUri,
                f"{CONTAINER_URL}/{PROJECT_HASH}/img-1",
            )
            self.assertEqual(
                output.persistenceMode, OutputPersistenceMode.LIVE_MOUNT
            )

    def test_uses_the_imageryprep_image_without_a_gpu_request(self):
        spec = self._build()
        self.assertEqual(
            spec.container.imageReference,
            "acr.example.io/haste-imageryprep:v2",
        )
        self.assertIsNone(spec.resources.accelerator)

    def test_environment_reference_uses_the_imageryprep_family(self):
        with _runtime_env(
            AML_ENVIRONMENT_IMAGERYPREP="haste-imageryprep:4",
            AML_ENVIRONMENT_TRAINING="haste-training:9",
        ):
            spec = build_imagery_job_spec(
                image_layer=_image_layer(),
                execution_id="img-1",
                input_files={
                    "config": {
                        "http_url": "https://acct/c/imagery.yaml",
                        "file_path": "imagery.yaml",
                    }
                },
                config=_config(),
            )
        self.assertEqual(
            spec.container.environmentReference, "haste-imageryprep:4"
        )


class TestArtifactPackagingSpec(unittest.TestCase):
    def _build(self, paths, **kwargs):
        with _runtime_env():
            return build_artifact_zip_job_spec(
                model_artifacts=ModelArtifacts(
                    modelId="42",
                    projectId=PROJECT_ID,
                    imageLayerId="layer-1",
                ),
                execution_id="zip-1",
                source_artifact_paths=paths,
                artifact_container_url=CONTAINER_URL,
                training_zip_name="model_training.zip",
                inference_zip_name="model_inference.zip",
                config=_config(),
                **kwargs,
            )

    def test_each_source_folder_gets_its_own_staging_destination(self):
        training = f"{PROJECT_HASH}/trn-1"
        inference = f"{PROJECT_HASH}/inf-1"
        spec = self._build([training, inference])

        self.assertEqual(len(spec.inputs), 2)
        self.assertTrue(all(i.kind == InputKind.FOLDER for i in spec.inputs))
        # Numbered by position, never by the provider-dependent layout
        # inside the staged directory.
        self.assertEqual(
            [i.destinationRelativePath for i in spec.inputs],
            [f"{STAGE_DIR}/source-0", f"{STAGE_DIR}/source-1"],
        )
        self.assertEqual(
            [i.sourceUri for i in spec.inputs],
            [
                f"{CONTAINER_URL}/{training}",
                f"{CONTAINER_URL}/{inference}",
            ],
        )

    def test_command_rebuilds_the_layout_the_zip_workflow_expects(self):
        training = f"{PROJECT_HASH}/trn-1"
        inference = f"{PROJECT_HASH}/inf-1"
        spec = self._build([training, inference])

        self.assertIn(f"mkdir -p $HASTE_JOB_WORKDIR/{MERGE_DIR}", spec.command)
        # Each source resolves its own staged layout at runtime: the
        # nested blob-prefix directory when a backend preserved it
        # (Azure Batch/local), the staged directory itself when the
        # backend presented the folder's contents directly (Azure ML).
        # Only the directory test may choose the branch — a failed link
        # must not fall through to the other layout.
        for path, task in ((training, "trn-1"), (inference, "inf-1")):
            index = 0 if task == "trn-1" else 1
            staged = f"$HASTE_JOB_WORKDIR/{STAGE_DIR}/source-{index}"
            link = f"$HASTE_JOB_WORKDIR/{MERGE_DIR}/{task}"
            self.assertIn(
                f"if [ -d {staged}/{path} ]; "
                f"then ln -sfn {staged}/{path} {link}; "
                f"else ln -sfn {staged} {link}; "
                f"fi",
                spec.command,
            )
        self.assertNotIn("|| ln -sfn", spec.command)
        self.assertTrue(
            spec.command.rstrip('"').endswith(
                "python -m hastegeo.workflows.zip_artifacts"
            )
        )
        self.assertEqual(spec.environment["INPUT_DIR"], MERGE_DIR)
        self.assertEqual(
            spec.environment["OUTPUT_TRAINING_ZIP_NAME"],
            "model_training.zip",
        )

    def test_command_never_branches_on_the_backend(self):
        spec = self._build([f"{PROJECT_HASH}/trn-1"])
        # One command for every provider: no backend name may appear in
        # it, and the layout choice is made by a filesystem test.
        for backend in ("azure_batch", "azure_ml", "local", "AZ_BATCH"):
            self.assertNotIn(backend, spec.command)
        self.assertIn("[ -d ", spec.command)

    def test_no_sources_still_produces_a_runnable_command(self):
        spec = self._build([])
        self.assertEqual(spec.inputs, [])
        self.assertIn("zip_artifacts", spec.command)

    def test_rejects_a_source_path_outside_the_haste_layout(self):
        with self.assertRaises(ValueError):
            self._build(["../etc/passwd"])
        with self.assertRaises(ValueError):
            self._build(["hash/task; rm -rf /"])

    def test_packaging_stays_cpu_capable(self):
        spec = self._build([f"{PROJECT_HASH}/trn-1"])
        self.assertIsNone(spec.resources.accelerator)
        self.assertIsNone(spec.resources.sharedMemoryMb)
        self.assertEqual(
            spec.container.imageReference,
            "acr.example.io/haste-imageryprep:v2",
        )

    def test_zip_outputs_upload_on_completion_at_the_haste_prefix(self):
        spec = self._build([f"{PROJECT_HASH}/trn-1"])
        output = spec.outputs[0]
        self.assertEqual(output.sourceRelativePattern, "outputs/*.*")
        self.assertEqual(
            output.destinationUri,
            f"{CONTAINER_URL}/{output_prefix(PROJECT_ID, 'zip-1')}",
        )
        self.assertEqual(
            output.persistenceMode, OutputPersistenceMode.UPLOAD_ON_COMPLETION
        )


@unittest.skipUnless(BASH, "no usable bash found for shell-fragment tests")
class TestArtifactStagingRunsOnBothProviderLayouts(unittest.TestCase):
    """Execute the generated staging fragment against both legitimate
    provider layouts and assert the merged tree is identical.

    * Azure Batch / local Docker preserve the source blob prefix, so a
      staged folder contains ``<project-hash>/<task-id>/...``;
    * Azure ML mounts a ``uri_folder`` whose contents *are* the input, so
      the same files sit directly in the staged folder.

    ``hastegeo.workflows.zip_artifacts`` reads ``INPUT_DIR`` and
    classifies its children by their ``trn-``/``inf-`` prefix, so both
    layouts must end up with the same ``merged/<task-id>/<file>`` view.
    """

    TRAINING = f"{PROJECT_HASH}/trn-1"
    INFERENCE = f"{PROJECT_HASH}/inf-1"

    def _command(self):
        with _runtime_env():
            spec = build_artifact_zip_job_spec(
                model_artifacts=ModelArtifacts(
                    modelId="42",
                    projectId=PROJECT_ID,
                    imageLayerId="layer-1",
                ),
                execution_id="zip-1",
                source_artifact_paths=[self.TRAINING, self.INFERENCE],
                artifact_container_url=CONTAINER_URL,
                training_zip_name="t.zip",
                inference_zip_name="i.zip",
                config=_config(),
            )
        # Drop the workload invocation (no container here) and the
        # command's outer quoting; keep the mkdir + link fragments.
        inner = spec.command.strip('"')
        return inner.rsplit(" && python -m ", 1)[0]

    def _stage(self, work_dir, *, nested):
        """Create staged/source-N in the given provider shape."""
        for index, path in enumerate((self.TRAINING, self.INFERENCE)):
            staged = os.path.join(work_dir, STAGE_DIR, f"source-{index}")
            target = (
                os.path.join(staged, *path.split("/")) if nested else staged
            )
            os.makedirs(target, exist_ok=True)
            with open(os.path.join(target, "artifact.txt"), "w") as handle:
                handle.write(path)

    def _run(self, *, nested, prelude="", command=None):
        with tempfile.TemporaryDirectory() as work_dir:
            self._stage(work_dir, nested=nested)
            bash_work_dir = work_dir.replace("\\", "/")
            result = subprocess.run(
                [
                    BASH,
                    "-c",
                    prelude
                    + f'export HASTE_JOB_WORKDIR="{bash_work_dir}"\n'
                    + (command if command is not None else self._command()),
                ],
                capture_output=True,
                text=True,
            )
            if prelude:
                # The caller is exercising a failure path; hand back the
                # process result instead of a merged view.
                return result
            self.assertEqual(result.returncode, 0, result.stderr)
            merged = os.path.join(work_dir, MERGE_DIR)
            contents = {}
            for task in sorted(os.listdir(merged)):
                artifact = os.path.join(merged, task, "artifact.txt")
                self.assertTrue(
                    os.path.isfile(artifact),
                    f"{task} did not resolve to the staged artifacts",
                )
                with open(artifact) as handle:
                    contents[task] = handle.read()
            return contents

    def test_batch_shaped_staging_resolves_the_nested_prefix(self):
        self.assertEqual(
            self._run(nested=True),
            {"trn-1": self.TRAINING, "inf-1": self.INFERENCE},
        )

    def test_aml_shaped_staging_resolves_the_staged_directory(self):
        self.assertEqual(
            self._run(nested=False),
            {"trn-1": self.TRAINING, "inf-1": self.INFERENCE},
        )

    def test_both_layouts_produce_the_same_merged_view(self):
        self.assertEqual(self._run(nested=True), self._run(nested=False))

    #: Replaces ``ln`` with one that fails for the nested (correct)
    #: target and succeeds for anything else — i.e. exactly the situation
    #: where a fallback would substitute the wrong layout.
    _FAILING_LN = (
        "ln() {\n"
        '  case "$2" in\n'
        f"    *{PROJECT_HASH}*) return 1 ;;\n"
        "  esac\n"
        "  return 0\n"
        "}\n"
    )

    def _legacy_fallback_command(self):
        """The rejected ``[ -d x ] && ln nested || ln flat`` form, used to
        show this test actually detects the masking it guards against."""
        parts = ["mkdir -p $HASTE_JOB_WORKDIR/merged"]
        for index, path in enumerate((self.TRAINING, self.INFERENCE)):
            staged = f"$HASTE_JOB_WORKDIR/{STAGE_DIR}/source-{index}"
            link = f"$HASTE_JOB_WORKDIR/{MERGE_DIR}/{path.split('/')[-1]}"
            parts.append(
                f"( [ -d {staged}/{path} ] "
                f"&& ln -sfn {staged}/{path} {link} "
                f"|| ln -sfn {staged} {link} )"
            )
        return " && ".join(parts)

    def test_a_failed_link_on_a_detected_layout_is_fatal(self):
        """A link failure must not be masked by the other layout.

        The staged tree here *is* the nested (Batch) shape, so the nested
        link is the correct one. With an ``ln`` that fails for the nested
        target, an ``[ -d x ] && ln nested || ln flat`` fragment quietly
        links the flat directory and reports success — producing a
        wrong-but-"successful" ZIP layout. Only the directory test may
        pick the branch, so the failure has to propagate.
        """
        masked = self._run(
            nested=True,
            prelude=self._FAILING_LN,
            command=self._legacy_fallback_command(),
        )
        # Guard the guard: the rejected form really does swallow it.
        self.assertEqual(
            masked.returncode,
            0,
            "expected the &&/|| form to mask the failure; "
            f"stderr={masked.stderr!r}",
        )

        result = self._run(nested=True, prelude=self._FAILING_LN)

        self.assertNotEqual(
            result.returncode,
            0,
            "a failing link on the detected layout must abort the job, "
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )


class TestSpecsAreAdapterAgnostic(unittest.TestCase):
    """A spec is data only: the same logical job must be describable for
    any backend without changing anything but the preference."""

    def test_same_spec_shape_for_every_backend_preference(self):
        shapes = {}
        for backend in (
            ComputeBackend.AZURE_BATCH,
            ComputeBackend.AZURE_ML,
            ComputeBackend.LOCAL,
        ):
            with _runtime_env():
                spec = build_training_job_spec(
                    model=_model(),
                    execution_id="trn-1",
                    input_files=_training_inputs(),
                    config=_config(),
                    backend=backend,
                )
            shapes[backend] = spec.model_dump(exclude={"backendPreference"})
        self.assertEqual(
            shapes[ComputeBackend.AZURE_BATCH], shapes[ComputeBackend.AZURE_ML]
        )
        self.assertEqual(
            shapes[ComputeBackend.AZURE_BATCH], shapes[ComputeBackend.LOCAL]
        )


if __name__ == "__main__":
    unittest.main()
