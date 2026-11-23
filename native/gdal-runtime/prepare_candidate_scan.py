"""Prepare and verify candidate-only Grype exceptions for the runtime SBOM."""

import argparse
import json
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath

from fetch_sources import LOCK, parse_lock
from inspect_sqlite_archives import inspect_archive
from prepare_openssl_scan_proposal import FIXES, ROOT, validate_bundle

SQLITE_CVE = "CVE-2026-119586"
SQLITE_VERSION = "3.54.1"


def verify_sqlite(wheels: tuple[Path, ...], bom: dict) -> None:
    _, sources = parse_lock(LOCK.read_text(encoding="utf-8"))
    sqlite = next(source for source in sources if source.name == "sqlite")
    if sqlite.version != SQLITE_VERSION:
        raise ValueError("SQLite version is outside the reviewed scope")
    components = [
        item
        for item in bom.get("components", [])
        if item.get("name") == "sqlite"
    ]
    if len(components) != 1:
        raise ValueError("Expected one SQLite SBOM component")
    component = components[0]
    if (
        component.get("version") != sqlite.version
        or component.get("purl") != f"pkg:generic/sqlite@{sqlite.version}"
        or {"alg": "SHA-256", "content": sqlite.sha256}
        not in component.get("hashes", [])
    ):
        raise ValueError("SQLite SBOM source does not match the source lock")

    libraries = []
    for wheel in wheels:
        if wheel.suffix != ".whl":
            continue
        report = inspect_archive(wheel)
        if (
            report["sqlite_cli_names"]
            or report["sqlite_cli_symlinks"]
            or report["sqlite_shell_fingerprint_matches"]
        ):
            raise ValueError(f"SQLite shell evidence in {wheel.name}")
        with zipfile.ZipFile(wheel) as archive:
            for name in report["sqlite_library_names"]:
                libraries.append((wheel.name, name))
                content = archive.read(name)
                if (
                    not content.startswith(b"\x7fELF")
                    or b"sqlite3_recover" in content
                    or b".recover" in content
                ):
                    raise ValueError("SQLite recovery code may be present")
    if (
        len(libraries) != 1
        or not libraries[0][0].startswith("haste_gdal_runtime-")
        or not PurePosixPath(libraries[0][1]).name.startswith("libsqlite3")
    ):
        raise ValueError("Expected one SQLite library in the runtime wheel")


def compare_scans(baseline: dict, result: dict) -> None:
    def counts(report: dict, key: str) -> Counter:
        return Counter(
            (
                item["artifact"]["id"],
                item["artifact"]["purl"],
                item["vulnerability"]["id"],
            )
            for item in report.get(key, [])
        )

    before = counts(baseline, "matches")
    after = counts(result, "matches")
    removed = before - after
    expected = {
        entry
        for entry in before
        if (entry[1] == "pkg:generic/openssl@3.5.9" and entry[2] in FIXES)
        or (
            entry[1] == f"pkg:generic/sqlite@{SQLITE_VERSION}"
            and entry[2] == SQLITE_CVE
        )
    }
    if (
        {entry[2] for entry in expected} != set(FIXES) | {SQLITE_CVE}
        or removed != Counter({entry: before[entry] for entry in expected})
        or after != before - removed
        or removed - counts(result, "ignoredMatches")
    ):
        raise ValueError("Candidate scan changed unexpected findings")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compare-baseline", type=Path)
    parser.add_argument("--compare-result", type=Path)
    args = parser.parse_args()
    if args.compare_baseline or args.compare_result:
        if not args.compare_baseline or not args.compare_result:
            parser.error("Both scan reports are required")
        compare_scans(
            json.loads(args.compare_baseline.read_text(encoding="utf-8")),
            json.loads(args.compare_result.read_text(encoding="utf-8")),
        )
        print("Only the six candidate-specific findings were excepted")
        return
    if not args.artifact_dir or not args.output:
        parser.error("--artifact-dir and --output are required")
    bundle = validate_bundle(args.artifact_dir)
    bom = json.loads(
        (args.artifact_dir / "bom.cdx.json").read_text(encoding="utf-8")
    )
    verify_sqlite(bundle.assets, bom)
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "native/gdal-runtime/prepare_openssl_scan_proposal.py"),
            "--artifact-dir",
            str(args.artifact_dir),
            "--output",
            str(args.output),
        ],
        check=True,
    )
    lines = args.output.read_text(encoding="utf-8").splitlines()
    ignore = lines.index("ignore:")
    insertion = next(
        (
            index
            for index in range(ignore + 1, len(lines))
            if lines[index]
            and not lines[index][0].isspace()
            and not lines[index].startswith("#")
        ),
        len(lines),
    )
    lines[insertion:insertion] = [
        "  # SQLite recovery shell is absent from the verified wheels.",
        "  # Upstream fix: https://sqlite.org/src/info/d684ccc9ec4e41d8",
        "  # Remove when inventory distinguishes the shell from the library.",
        f"  - vulnerability: {SQLITE_CVE}",
        "    package:",
        "      name: sqlite",
        f"      version: {SQLITE_VERSION}",
    ]
    lines[0] = (
        "# Candidate-only: OpenSSL upstream fix identities are verified "
        "against openssl-patches.lock."
    )
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
