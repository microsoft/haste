"""Prepare review-only Grype rules for the verified OpenSSL backports.

The generated config is not an approval and is not used by the blocking scan.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".github" / "scripts"))

from apply_openssl_patches import PATCH_LOCK, load_patches  # noqa: E402
from fetch_sources import LOCK, parse_lock  # noqa: E402
from publish_gdal_runtime import validate_bundle  # noqa: E402

FIXES = {
    "CVE-2026-88822": "1a73dc590cbad62d6f0329ea4779eadaa8d8fd75",  # pragma: allowlist secret
    "CVE-2026-88823": "159e1de0c448d7b9f09ad768c8e141def4aa1eb4",  # pragma: allowlist secret
    "CVE-2026-95691": "f6244675833e097c2429a40d1b206d95385bd42f",  # pragma: allowlist secret
    "CVE-2026-95692": "257a3427aa0ef8d9dd2ef5b3e2d1c021a221b116",  # pragma: allowlist secret
    "CVE-2026-107496": "a0051cfe699bf5a047bc1c4faef65f80f7987366",  # pragma: allowlist secret
    "CVE-2026-107493": "c8f6d04f8e6d40b1bf83334e4a2ec9daf5943a3d",  # pragma: allowlist secret
    "CVE-2026-35190": "9491b0d9cc7950af1f3dc89499bd5433b9cd4f43",  # pragma: allowlist secret
    "CVE-2026-124709": "f3acb0a3328046741479482c51cec815839e1b05",  # pragma: allowlist secret
    "CVE-2026-121482": "468c287cf451a834b370b69ab321b8ffdfac23aa",  # pragma: allowlist secret
    "CVE-2026-107494": "734c6cd7444bdbf589bfec917e47598c1b21ddd3",  # pragma: allowlist secret
    "CVE-2026-84786": "1ad851363d5b8588b0d40edcc045fd633e93f0c2",  # pragma: allowlist secret
}


def build_proposal(
    manifest: dict,
    wheel_manifest: dict,
    bom: dict,
    patches: list[dict],
    runtime_version: str,
    build_number: str,
    openssl_version: str,
    openssl_sha256: str,
    base_config: str,
) -> str:
    if not runtime_version.endswith(f"+haste.{build_number}"):
        raise ValueError("Runtime bundle is not the locked candidate build")
    if (
        manifest != wheel_manifest
        or manifest.get("openssl_patches") != patches
    ):
        raise ValueError(
            "OpenSSL patch evidence differs from the locked build"
        )
    actual_fixes = {
        item["cve"]: item["commit"]
        for item in patches
        if item["kind"] in {"fix", "fix-and-test"}
    }
    if actual_fixes != FIXES:
        raise ValueError("OpenSSL fix identities do not match the proposal")
    if (
        bom.get("metadata", {}).get("component", {}).get("version")
        != runtime_version
    ):
        raise ValueError("SBOM does not identify this runtime build")
    properties = bom["metadata"].get("properties", [])
    entries = [
        item["value"]
        for item in properties
        if item.get("name") == "gdal_runtime.openssl_patches"
    ]
    if len(entries) != 1 or json.loads(entries[0]) != patches:
        raise ValueError("SBOM patch evidence does not match the lock")
    components = [
        item
        for item in bom.get("components", [])
        if item.get("name") == "openssl"
    ]
    if len(components) != 1:
        raise ValueError("Expected exactly one OpenSSL SBOM component")
    component = components[0]
    if (
        component.get("version") != openssl_version
        or component.get("purl") != f"pkg:generic/openssl@{openssl_version}"
        or {"alg": "SHA-256", "content": openssl_sha256}
        not in component.get("hashes", [])
    ):
        raise ValueError("OpenSSL SBOM source does not match the source lock")

    lines = base_config.splitlines()
    ignore_lines = [i for i, line in enumerate(lines) if line == "ignore:"]
    if len(ignore_lines) != 1:
        raise ValueError("Expected a single top-level Grype ignore list")
    insertion = next(
        (
            index
            for index in range(ignore_lines[0] + 1, len(lines))
            if lines[index]
            and not lines[index][0].isspace()
            and not lines[index].startswith("#")
        ),
        len(lines),
    )
    rules = []
    for cve in sorted(FIXES):
        rules.extend(
            [
                f"  - vulnerability: {cve}",
                "    package:",
                "      name: openssl",
                f"      version: {openssl_version}",
            ]
        )
    lines[insertion:insertion] = rules
    return (
        "# REVIEW-ONLY: use solely with the verified candidate SBOM.\n"
        + "\n".join(lines)
        + "\n"
    )


def compare_scans(baseline: dict, proposed: dict) -> None:
    def counts(report: dict, section: str) -> Counter:
        return Counter(
            (
                item["artifact"]["id"],
                item["artifact"]["purl"],
                item["vulnerability"]["id"],
            )
            for item in report.get(section, [])
        )

    before = counts(baseline, "matches")
    after = counts(proposed, "matches")
    removed = before - after
    expected = {
        entry
        for entry in before
        if entry[1] == "pkg:generic/openssl@3.5.9" and entry[2] in FIXES
    }
    if (
        {entry[2] for entry in expected} != set(FIXES)
        or removed != Counter({entry: before[entry] for entry in expected})
        or after != before - removed
        or removed - counts(proposed, "ignoredMatches")
    ):
        raise ValueError("Proposal changed findings beyond verified backports")
    if not any(
        purl == "pkg:generic/sqlite@3.54.1" and cve == "CVE-2026-119586"
        for _, purl, cve in after
    ):
        raise ValueError("SQLite CLI finding must remain visible")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compare-baseline", type=Path)
    parser.add_argument("--compare-proposal", type=Path)
    args = parser.parse_args()
    if args.compare_baseline or args.compare_proposal:
        if not args.compare_baseline or not args.compare_proposal:
            parser.error("Both scan reports are required for comparison")
        compare_scans(
            json.loads(args.compare_baseline.read_text(encoding="utf-8")),
            json.loads(args.compare_proposal.read_text(encoding="utf-8")),
        )
        print("Review-only proposal changes only verified OpenSSL findings")
        return
    if not args.artifact_dir or not args.output:
        parser.error("--artifact-dir and --output are required")
    if args.output.exists():
        raise FileExistsError("Refusing to overwrite an existing proposal")
    bundle = validate_bundle(args.artifact_dir)
    build, sources = parse_lock(LOCK.read_text(encoding="utf-8"))
    openssl = next(source for source in sources if source.name == "openssl")
    patches = load_patches(PATCH_LOCK)
    manifest = json.loads(
        (args.artifact_dir / "manifest.json").read_text(encoding="utf-8")
    )
    bom = json.loads(
        (args.artifact_dir / "bom.cdx.json").read_text(encoding="utf-8")
    )
    wheel = next(
        path
        for path in bundle.assets
        if path.name.startswith("haste_gdal_runtime-")
    )
    with zipfile.ZipFile(wheel) as archive:
        wheel_manifest = json.loads(
            archive.read("haste_gdal_runtime/manifest.json")
        )
    config = build_proposal(
        manifest,
        wheel_manifest,
        bom,
        patches,
        bundle.runtime_version,
        build,
        openssl.version,
        openssl.sha256,
        (ROOT / ".grype.yaml").read_text(encoding="utf-8"),
    )
    args.output.write_text(config, encoding="utf-8")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    print(
        f"Review-only proposal for {bundle.runtime_version}; wheel SHA-256 {digest}"
    )


if __name__ == "__main__":
    main()
