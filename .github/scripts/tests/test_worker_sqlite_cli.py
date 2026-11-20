import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "docker" / "common" / "remove_worker_sqlite_cli.py"
SPEC = importlib.util.spec_from_file_location("worker_sqlite_cli", SCRIPT)
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


class WorkerSqliteCliTests(unittest.TestCase):
    def test_shared_helper_changes_trigger_both_worker_builds(self):
        workflow = (
            ROOT / ".github/workflows/docker-build-and-push.yml"
        ).read_text(encoding="utf-8")
        filters = workflow.split("          filters: |", 1)[1].split(
            "\n  build-and-push:", 1
        )[0]
        training = filters.split("            training:", 1)[1].split(
            "            imageryprep:", 1
        )[0]
        imageryprep = filters.split("            imageryprep:", 1)[1].split(
            "            hastelib:", 1
        )[0]
        self.assertIn("'docker/common/**'", training)
        self.assertIn("'docker/common/**'", imageryprep)
        gdal = (ROOT / ".github/workflows/gdal-runtime-build.yml").read_text(
            encoding="utf-8"
        )
        self.assertEqual(gdal.count('"docker/common/**"'), 2)

    def test_removes_only_known_shells_and_keeps_libraries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in worker.CLI_PATHS:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"shell")
            library = root / "opt/miniconda/lib/libsqlite3.so"
            library.parent.mkdir(parents=True, exist_ok=True)
            library.write_bytes(b"library")
            with patch.object(worker.shutil, "which", return_value=None):
                removed = worker.remove_worker_sqlite_cli(root)
                self.assertEqual(len(removed), len(worker.CLI_PATHS))
                self.assertEqual(worker.remove_worker_sqlite_cli(root), [])
            self.assertEqual(library.read_bytes(), b"library")
            self.assertTrue(
                all(not (root / name).exists() for name in removed)
            )

    def test_unknown_shell_on_path_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                worker.shutil, "which", return_value="/unexpected/sqlite3"
            ), self.assertRaisesRegex(RuntimeError, "unexpected sqlite3"):
                worker.remove_worker_sqlite_cli(Path(directory))

    def test_removes_off_path_nsight_shell_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nsight = (
                root
                / "opt/nvidia/nsight-compute/2024.1.1/host/target-linux-x64"
            )
            nsight.mkdir(parents=True)
            shell = nsight / "sqlite3"
            shell.write_bytes(b"shell")
            library = nsight / "libsqlite3.so"
            library.write_bytes(b"library")
            with patch.object(worker.shutil, "which", return_value=None):
                worker.remove_worker_sqlite_cli(root)
            self.assertFalse(shell.exists())
            self.assertTrue(library.is_file())

    def test_relative_root_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "absolute"):
            worker.remove_worker_sqlite_cli(Path("relative"))


if __name__ == "__main__":
    unittest.main()
