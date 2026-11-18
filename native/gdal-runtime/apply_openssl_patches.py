"""Verify and apply the locked upstream OpenSSL patches."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from fetch_sources import LOCK, Source, fetch, parse_lock

PATCH_LOCK = Path(__file__).with_name("openssl-patches.lock")


def load_patches(lock_path: Path, source_lock: Path = LOCK) -> list[dict]:
    version = ""
    patches = []
    for raw in lock_path.read_text(encoding="utf-8").splitlines():
        fields = raw.split("#", 1)[0].split()
        if not fields:
            continue
        if fields[0] == "OPENSSL_SOURCE_VERSION" and len(fields) == 2:
            if version:
                raise ValueError("Duplicate OpenSSL patch source version")
            version = fields[1]
            continue
        if len(fields) != 4:
            raise ValueError("Invalid OpenSSL patch lock line")
        commit, cve, kind, digest = fields
        patches.append(
            {"commit": commit, "cve": cve, "kind": kind, "sha256": digest}
        )
    _, sources = parse_lock(source_lock.read_text(encoding="utf-8"))
    openssl = [source for source in sources if source.name == "openssl"]
    if len(openssl) != 1 or version != openssl[0].version:
        raise ValueError(
            "OpenSSL patch source version does not match the lock"
        )
    if not patches:
        raise ValueError("OpenSSL patch lock must contain patches")
    seen = set()
    for patch in patches:
        if not isinstance(patch, dict):
            raise ValueError("Invalid OpenSSL patch entry")
        commit, cve, kind, digest = (
            patch.get("commit"),
            patch.get("cve"),
            patch.get("kind"),
            patch.get("sha256"),
        )
        if (
            not isinstance(commit, str)
            or not re.fullmatch(r"[0-9a-f]{40}", commit)
            or commit in seen
            or not isinstance(cve, str)
            or not re.fullmatch(r"CVE-\d{4}-\d{4,}", cve)
            or kind not in {"fix", "test", "fix-and-test"}
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise ValueError("Invalid or duplicate OpenSSL patch entry")
        seen.add(commit)
    return patches


def apply_patches(
    source_dir: Path, cache_dir: Path, report: Path, lock: Path = PATCH_LOCK
) -> None:
    if report.exists():
        raise FileExistsError("Refusing to overwrite an existing patch report")
    patches = load_patches(lock)
    sources = [
        Source(
            name=f"openssl-{patch['commit']}",
            version=patch["commit"],
            url=(
                "https://github.com/openssl/openssl/commit/"
                f"{patch['commit']}.patch"
            ),
            sha256=patch["sha256"],
        )
        for patch in patches
    ]
    problems = fetch(sources, cache_dir)
    if problems:
        raise ValueError("; ".join(problems))
    for source in sources:
        subprocess.run(
            [
                "patch",
                "--batch",
                "--forward",
                "--fuzz=0",
                "-p1",
                "-i",
                str((cache_dir / source.filename).resolve()),
            ],
            cwd=source_dir,
            check=True,
        )
    report.write_text(
        json.dumps(patches, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    apply_patches(args.source_dir, args.cache_dir, args.report)


if __name__ == "__main__":
    main()
