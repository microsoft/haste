"""Download the runtime's native sources and verify them against sources.lock.

Usage:
    python fetch_sources.py --dest DIR           download and verify all
    python fetch_sources.py --print-build        print HASTE_GDAL_BUILD
    python fetch_sources.py --print-version NAME print a component version

A file that is already present is re-verified rather than trusted. Any
mismatch is fatal: the build must never compile a source it cannot verify.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

LOCK = Path(__file__).with_name("sources.lock")
CHUNK = 1024 * 1024


@dataclass(frozen=True)
class Source:
    name: str
    version: str
    url: str
    sha256: str

    @property
    def filename(self) -> str:
        return self.url.rsplit("/", 1)[-1]


def parse_lock(text: str) -> tuple[str, list[Source]]:
    build = ""
    sources: list[Source] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        if fields[0] == "HASTE_GDAL_BUILD" and len(fields) == 2:
            build = fields[1]
            continue
        if len(fields) != 4:
            raise ValueError(f"sources.lock line {number}: expected 4 fields")
        name, version, url, digest = fields
        if not url.startswith("https://"):
            raise ValueError(f"sources.lock line {number}: URL must be HTTPS")
        if len(digest) != 64 or any(
            c not in "0123456789abcdef" for c in digest
        ):
            raise ValueError(f"sources.lock line {number}: bad sha256")
        sources.append(Source(name, version, url, digest))
    if not build.isdigit():
        raise ValueError("sources.lock: HASTE_GDAL_BUILD must be a number")
    names = [source.name for source in sources]
    if len(names) != len(set(names)):
        raise ValueError("sources.lock: duplicate component")
    return build, sources


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def download(source: Source, target: Path, attempts: int = 4) -> None:
    partial = target.with_suffix(target.suffix + ".part")
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(
                source.url, headers={"User-Agent": "haste-gdal-runtime"}
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                with partial.open("wb") as handle:
                    for block in iter(lambda: response.read(CHUNK), b""):
                        handle.write(block)
            partial.replace(target)
            return
        except OSError as error:
            if attempt == attempts:
                raise
            print(f"  retrying {source.filename} ({error})", file=sys.stderr)
            time.sleep(5 * attempt)


def fetch(sources: list[Source], dest: Path) -> list[str]:
    dest.mkdir(parents=True, exist_ok=True)
    problems = []
    for source in sources:
        target = dest / source.filename
        if not target.exists():
            print(f"downloading {source.name} {source.version}")
            download(source, target)
        actual = sha256_of(target)
        if actual != source.sha256:
            target.unlink()
            problems.append(
                f"{source.filename}: sha256 {actual} != locked {source.sha256}"
            )
        else:
            print(f"verified    {source.filename}")
    return problems


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(newline="\n")
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dest", type=Path)
    group.add_argument("--print-build", action="store_true")
    group.add_argument("--print-version", metavar="NAME")
    args = parser.parse_args(argv)

    build, sources = parse_lock(LOCK.read_text(encoding="utf-8"))
    if args.print_build:
        print(build)
        return 0
    if args.print_version:
        for source in sources:
            if source.name == args.print_version:
                print(source.version)
                return 0
        print(f"unknown component {args.print_version!r}", file=sys.stderr)
        return 2

    problems = fetch(sources, args.dest)
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
