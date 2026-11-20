"""Inspect a streaming Docker export without extracting image files."""

import hashlib
import json
import sys
import tarfile
from pathlib import Path, PurePosixPath


def main() -> None:
    control = hashlib.sha256(Path(sys.argv[1]).read_bytes()).digest()
    markers = (b"sqlite> ", b".recover")
    overlap = max(map(len, markers)) - 1
    names = {"sqlite3", "sqlite3.exe"}
    findings: list[str] = []
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|*") as archive:
        for member in archive:
            if PurePosixPath(member.name).name.casefold() in names or (
                (member.issym() or member.islnk())
                and PurePosixPath(member.linkname).name.casefold() in names
            ):
                findings.append(member.name)
            if not member.isfile():
                continue
            stream = archive.extractfile(member)
            assert stream is not None
            with stream:
                header = stream.read(4)
                if not header.startswith((b"\x7fELF", b"MZ")):
                    continue
                digest = hashlib.sha256(header)
                missing = set(markers)
                tail = header
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    block = tail + chunk
                    missing.difference_update(
                        marker for marker in markers if marker in block
                    )
                    tail = block[-overlap:]
                    if not missing:
                        break
                if not missing or digest.digest() == control:
                    findings.append(member.name)
    print(json.dumps({"merged_filesystem_cli_matches": sorted(set(findings))}))
    if findings:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
