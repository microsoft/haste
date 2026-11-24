"""Inventory SQLite CLI evidence in runtime wheels and Function ZIPs."""

import argparse
import hashlib
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath

CLI_NAMES = {"sqlite3", "sqlite3.exe"}
SHELL_MARKERS = (b"sqlite> ",)
CHUNK_SIZE = 1024 * 1024


def has_shell_markers(
    archive: zipfile.ZipFile, member: zipfile.ZipInfo
) -> bool:
    with archive.open(member) as stream:
        header = stream.read(4)
        if not header.startswith((b"\x7fELF", b"MZ")):
            return False
        missing = set(SHELL_MARKERS)
        overlap = max(map(len, missing)) - 1
        tail = header
        while chunk := stream.read(CHUNK_SIZE):
            block = tail + chunk
            missing = {marker for marker in missing if marker not in block}
            if not missing:
                return True
            tail = block[-overlap:]
    return False


def inspect_archive(path: Path) -> dict[str, str | list[str]]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_SIZE):
            digest.update(chunk)
    with zipfile.ZipFile(path) as archive:
        members = [
            member for member in archive.infolist() if not member.is_dir()
        ]
        names = [member.filename for member in members]
        fingerprints = [
            member.filename
            for member in members
            if has_shell_markers(archive, member)
        ]
        aliases = [
            member.filename
            for member in members
            if stat.S_ISLNK(member.external_attr >> 16)
            and PurePosixPath(
                archive.read(member).decode(errors="replace")
            ).name.casefold()
            in CLI_NAMES
        ]
    return {
        "archive": path.name,
        "sha256": digest.hexdigest(),
        "sqlite_cli_names": [
            name
            for name in names
            if PurePosixPath(name).name.casefold() in CLI_NAMES
        ],
        "sqlite_cli_symlinks": aliases,
        "sqlite_shell_fingerprint_matches": fingerprints,
        "sqlite_library_names": [
            name
            for name in names
            if PurePosixPath(name).name.casefold().startswith("libsqlite3")
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory", action="append", type=Path, required=True
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    archives = [
        path
        for directory in args.directory
        for path in sorted(directory.iterdir())
        if path.suffix.casefold() in {".zip", ".whl"} and path.is_file()
    ]
    if not any(path.suffix.casefold() == ".whl" for path in archives):
        raise ValueError("No runtime wheels found for SQLite inspection")
    if not any(path.suffix.casefold() == ".zip" for path in archives):
        raise ValueError("No Function packages found for SQLite inspection")
    report = {
        "scope": (
            "Archive names, direct symlink targets and ELF/PE shell markers. "
            "This heuristic does not establish image contents or reachability "
            "and may miss modified shells or embedded archives."
        ),
        "archives": [inspect_archive(path) for path in archives],
    }
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
