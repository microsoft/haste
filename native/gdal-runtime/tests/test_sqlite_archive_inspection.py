import hashlib
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

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

    def test_detects_renamed_shell_but_not_text_or_library(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.whl"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "off-path/tool", b"\x7fELF sqlite> \x00.recover"
                )
                archive.writestr("docs.txt", b"sqlite> .recover")
                archive.writestr("libsqlite3.so", b"\x7fELF .recover")
            with mock.patch.object(inspect_sqlite_archives, "CHUNK_SIZE", 5):
                report = inspect_sqlite_archives.inspect_archive(path)
            self.assertEqual(
                report["sha256"], hashlib.sha256(path.read_bytes()).hexdigest()
            )
        self.assertEqual(
            report["sqlite_shell_fingerprint_matches"], ["off-path/tool"]
        )

    def test_detects_symlink_to_cli_under_another_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "function.zip"
            alias = zipfile.ZipInfo("bin/db-tool")
            alias.create_system = 3
            alias.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(alias, "../runtime/bin/sqlite3")
            report = inspect_sqlite_archives.inspect_archive(path)
        self.assertEqual(report["sqlite_cli_symlinks"], ["bin/db-tool"])


if __name__ == "__main__":
    unittest.main()
