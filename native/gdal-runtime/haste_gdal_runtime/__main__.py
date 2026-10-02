"""Command line for the HASTE GDAL runtime.

    python -m haste_gdal_runtime report
    python -m haste_gdal_runtime verify --expected-gdal 3.13.3 \
        [--allow-driver NAME ...] [--allow-vsi PREFIX ...]
    python -m haste_gdal_runtime manifest --library PATH --output FILE

``manifest`` runs at build time against the freshly built libgdal. The
library is always passed explicitly; nothing is read from the environment.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import (
    DEFAULT_ALLOWED_VSI,
    Policy,
    RuntimeCheckError,
    configure,
    evaluate,
    harden,
    load_manifest,
    report,
)
from ._native import NativeGdal


def _dump(data: Any) -> None:
    json.dump(data, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def _policy(args: argparse.Namespace) -> Policy:
    return Policy(
        expected_gdal=args.expected_gdal,
        allowed_drivers=(
            frozenset(args.allow_driver) if args.allow_driver else None
        ),
        allowed_vsi=(
            frozenset(args.allow_vsi)
            if args.allow_vsi
            else DEFAULT_ALLOWED_VSI
        ),
        required_bindings=tuple(args.require_binding or ()),
    )


def _manifest(args: argparse.Namespace) -> int:
    native = NativeGdal(Path(args.library))
    build_info = native.build_info()
    manifest = {
        "schema": 1,
        "gdal_release": native.version_info("RELEASE_NAME"),
        "proj_release": build_info.get("PROJ_RUNTIME_VERSION"),
        "build_info": build_info,
        "drivers": native.drivers(),
        "vsi_prefixes": native.vsi_prefixes(),
        "vrt_raw_band_compiled": native.driver_metadata(
            "VRT", "GDAL_VRT_ENABLE_RAWRASTERBAND"
        )
        == "YES",
        "probes_permissive": native.probes(permissive=True),
    }
    Path(args.output).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _dump(manifest)
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m haste_gdal_runtime")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("report", help="print the runtime evidence report")

    verify = commands.add_parser(
        "verify", help="harden, check against a policy, exit 1 on problems"
    )
    verify.add_argument("--expected-gdal", required=True)
    verify.add_argument("--allow-driver", action="append")
    verify.add_argument("--allow-vsi", action="append")
    verify.add_argument("--require-binding", action="append")

    manifest = commands.add_parser(
        "manifest", help="describe a freshly built libgdal (build time)"
    )
    manifest.add_argument("--library", required=True)
    manifest.add_argument("--output", required=True)

    args = parser.parse_args(argv)
    if args.command == "manifest":
        return _manifest(args)
    if args.command == "report":
        configure()
        _dump(report())
        return 0

    policy = _policy(args)
    configure(policy)
    try:
        removed = harden(policy)
        observed = report()
        observed["removed"] = removed
        problems = evaluate(observed, load_manifest(), policy)
    except RuntimeCheckError as error:
        problems, observed = error.problems, {}
    _dump({"problems": problems, "report": observed})
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
