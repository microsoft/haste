"""List SQLite CLI and library names in runtime wheels and Function ZIPs."""

import argparse
import json
import zipfile
from pathlib import Path, PurePosixPath


def inspect_archive(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
    return {
        "archive": path.name,
        "sqlite_cli_names": [
            name
            for name in names
            if PurePosixPath(name).name.casefold()
            in {"sqlite3", "sqlite3.exe"}
        ],
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
            "Archive names only; this does not establish image contents, "
            "renamed executables or reachability."
        ),
        "archives": [inspect_archive(path) for path in archives],
    }
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
