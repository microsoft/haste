"""Resolve operator size variables into validated decimal byte counts."""

import os
import re
import sys
from collections.abc import Mapping

DEFAULTS = {
    "HASTE_MAX_UPLOAD_BYTES": 5 * 1024**3,
    "HASTE_MAX_IMAGERY_DOWNLOAD_BYTES": 8 * 1024**3,
    "PUBLISH_ASSESSMENT_MAX_TOTAL_BYTES": 512 * 1024**2,
}
MIN_BYTES = 1024**2
MAX_BYTES = 1024**4
MULTIPLIERS = {"": 1}
for power, prefix in enumerate(("K", "M", "G", "T"), start=1):
    MULTIPLIERS[prefix] = 1024**power
    MULTIPLIERS[prefix + "IB"] = 1024**power
    MULTIPLIERS[prefix + "B"] = 1000**power


def parse_size(value: str) -> int:
    normalized = re.sub(r"[\s,_]", "", value).upper()
    match = re.fullmatch(r"([0-9]+)([KMGT](?:IB|B)?)?", normalized)
    if match is None:
        raise ValueError("use integer bytes or a size such as 30GiB or 30GB")
    byte_count = int(match[1], 10) * MULTIPLIERS[match[2] or ""]
    if not MIN_BYTES <= byte_count <= MAX_BYTES:
        raise ValueError("size must be between 1 MiB and 1 TiB")
    return byte_count


def resolve_limits(environment: Mapping[str, str]) -> dict[str, int]:
    resolved = {}
    for name, default in DEFAULTS.items():
        value = environment.get(name, "").strip()
        try:
            resolved[name] = parse_size(value) if value else default
        except ValueError as error:
            raise ValueError(f"{name}: {error}") from error
    return resolved


def main() -> int:
    sys.stdout.reconfigure(newline="\n")
    try:
        resolved = resolve_limits(os.environ)
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    for name, byte_count in resolved.items():
        print(f"{name}={byte_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())