import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import inspect_sqlite_archives  # noqa: E402


class SqliteArchiveInspectionTests(unittest.TestCase):
    def test_lists_cli_and_library_without_extracting_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.whl"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("data/bin/sqlite3", b"fixture")
                archive.writestr("libs/libsqlite3-a.so", b"fixture")
                archive.writestr("data/sqlite3/", b"")
            report = inspect_sqlite_archives.inspect_archive(path)
        self.assertEqual(report["sqlite_cli_names"], ["data/bin/sqlite3"])
        self.assertEqual(
            report["sqlite_library_names"], ["libs/libsqlite3-a.so"]
        )


if __name__ == "__main__":
    unittest.main()
