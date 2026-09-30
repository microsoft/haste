# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import importlib.util
import os
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "run_workflow.py"
spec = importlib.util.spec_from_file_location(
    "workflow_streaming_subject", SCRIPT
)
workflow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workflow)


class TestWorkflowStreaming(unittest.TestCase):
    def test_streams_stdout_and_stderr_before_child_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            child = (
                "import sys; "
                "print('stdout-ready'); "
                "print('stderr-ready', file=sys.stderr); "
                "sys.stdin.readline()"
            )
            wrapper = (
                "import importlib.util,sys; "
                f"s=importlib.util.spec_from_file_location('w', {str(SCRIPT)!r}); "
                "w=importlib.util.module_from_spec(s); s.loader.exec_module(w); "
                f"w.run_subprocess([sys.executable,'-c',{child!r}], 'test-step')"
            )
            env = dict(
                os.environ,
                AZ_BATCH_TASK_WORKING_DIR=tmp,
                PYTHONUNBUFFERED="",
            )
            process = subprocess.Popen(
                [sys.executable, "-c", wrapper],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            observed = queue.Queue()
            readers = [
                threading.Thread(
                    target=lambda stream=stream, name=name: observed.put(
                        (name, stream.readline().strip())
                    )
                )
                for name, stream in (
                    ("stdout", process.stdout),
                    ("stderr", process.stderr),
                )
            ]
            for reader in readers:
                reader.start()
            try:
                messages = dict(observed.get(timeout=10) for _ in readers)
                self.assertEqual(messages["stdout"], "stdout-ready")
                self.assertEqual(messages["stderr"], "stderr-ready")
                self.assertIsNone(process.poll())
                progress = (
                    Path(tmp) / "logs" / "workflow_progress.log"
                ).read_text()
                self.assertIn("Starting test-step", progress)
                self.assertNotIn("Completed test-step", progress)
            finally:
                process.stdin.write("finish\n")
                process.stdin.flush()
                process.communicate(timeout=10)
                for reader in readers:
                    reader.join(timeout=1)
            self.assertEqual(process.returncode, 0)
            progress = (
                Path(tmp) / "logs" / "workflow_progress.log"
            ).read_text()
            self.assertIn("Starting test-step", progress)
            self.assertIn("Completed test-step", progress)

    def test_child_environment_is_unbuffered_without_changing_arguments(
        self,
    ) -> None:
        command = ["python", "fine_tune.py", "--config", "config.yaml"]
        result = subprocess.CompletedProcess(command, 0)
        with (
            patch.dict(
                os.environ,
                {"PYTHONUNBUFFERED": "", "WORKFLOW_TEST_VALUE": "retained"},
            ),
            patch.object(workflow, "log_progress"),
            patch.object(
                workflow.subprocess, "run", return_value=result
            ) as run,
        ):
            self.assertIs(
                workflow.run_subprocess(command, "fine_tune.py"), result
            )
            self.assertEqual(os.environ["PYTHONUNBUFFERED"], "")
            run.assert_called_once_with(
                command,
                text=True,
                env=dict(os.environ, PYTHONUNBUFFERED="1"),
            )
            self.assertEqual(
                run.call_args.kwargs["env"]["WORKFLOW_TEST_VALUE"],
                "retained",
            )

    def test_nonzero_exit_remains_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AZ_BATCH_TASK_WORKING_DIR": tmp}
        ):
            with self.assertRaises(subprocess.CalledProcessError) as error:
                workflow.run_subprocess(
                    [sys.executable, "-c", "raise SystemExit(17)"],
                    "failing-step",
                )
            self.assertEqual(error.exception.returncode, 17)
            log = (Path(tmp) / "logs" / "workflow_progress.log").read_text()
            self.assertIn("Error running failing-step", log)
            self.assertNotIn("Completed failing-step", log)
