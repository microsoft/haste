import copy
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import prepare_candidate_scan as candidate  # noqa: E402
from fetch_sources import LOCK, parse_lock  # noqa: E402


class CandidateScanTests(unittest.TestCase):
    def setUp(self) -> None:
        _, sources = parse_lock(LOCK.read_text(encoding="utf-8"))
        source = next(item for item in sources if item.name == "sqlite")
        self.bom = {
            "components": [
                {
                    "name": "sqlite",
                    "version": source.version,
                    "purl": f"pkg:generic/sqlite@{source.version}",
                    "hashes": [{"alg": "SHA-256", "content": source.sha256}],
                }
            ]
        }

    def test_accepts_library_without_recovery_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "haste_gdal_runtime-example.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("lib/libsqlite3.so", b"\x7fELF sqlite core")
            candidate.verify_sqlite((wheel,), self.bom)

    def test_rejects_shell_recovery_or_wrong_sbom(self) -> None:
        for name, data in (
            ("bin/sqlite3", b"shell"),
            ("bin/renamed", b"\x7fELF sqlite> "),
            ("lib/libsqlite3.so", b"\x7fELF sqlite3_recover_init"),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                wheel = Path(d) / "haste_gdal_runtime-example.whl"
                with zipfile.ZipFile(wheel, "w") as archive:
                    archive.writestr(name, data)
                with self.assertRaises(ValueError):
                    candidate.verify_sqlite((wheel,), self.bom)
        invalid = copy.deepcopy(self.bom)
        invalid["components"][0]["hashes"][0]["content"] = "0" * 64
        with self.assertRaises(ValueError):
            candidate.verify_sqlite((), invalid)

    def test_comparison_rejects_unrelated_or_unaccounted_changes(self) -> None:
        def match(identifier: str, purl: str, cve: str) -> dict:
            return {
                "artifact": {"id": identifier, "purl": purl},
                "vulnerability": {"id": cve},
            }

        fixes = [
            match("openssl", "pkg:generic/openssl@3.5.9", cve)
            for cve in candidate.FIXES
        ]
        sqlite = match(
            "sqlite", "pkg:generic/sqlite@3.54.1", candidate.SQLITE_CVE
        )
        other = [
            match("openssl", "pkg:generic/openssl@3.5.9", cve)
            for cve in ("CVE-2026-95690", "CVE-2000-0001")
        ]
        baseline = {"matches": [*fixes, sqlite, *other]}
        candidate.compare_scans(
            baseline, {"matches": other, "ignoredMatches": [*fixes, sqlite]}
        )
        for result in (
            {"matches": [], "ignoredMatches": [*fixes, sqlite, *other]},
            {"matches": other, "ignoredMatches": fixes},
            {"matches": [sqlite, *other], "ignoredMatches": fixes},
        ):
            with self.subTest(result=result), self.assertRaises(ValueError):
                candidate.compare_scans(baseline, result)


if __name__ == "__main__":
    unittest.main()
