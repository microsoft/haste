#!/usr/bin/env python3
"""Fail when React and its companion packages drift onto different majors.

`react` and `react-dom` must ship as a matched pair, and the `@types`
packages mirror them. A Dependabot PR bumped `react` to `^19.2.8` while
leaving `react-dom` on `^18.3.1`, which is incoherent on its own and also
broke `@azure/msal-react@2.2.0` -- it accepts `^16.8.0 || ^17 || ^18`, so
`npm install` failed outright:

    Could not resolve dependency:
    peer react@"^16.8.0 || ^17 || ^18" from @azure/msal-react@2.2.0

The UI image could not be built at all. `npm install` in CI catches the
peer conflict, but only once something already depends on the older
major; this check fails on the mismatch itself, which is the real defect
and gives a far clearer message.

Usage:  python .github/scripts/check_react_pins.py [ui/package.json]
Exit 0 when the majors agree, 1 otherwise.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[2]
DEFAULT_PACKAGE_JSON = REPO / "ui" / "package.json"

# (left, right, section) -- both must sit on the same major.
PAIRS = (
    ("react", "react-dom", "dependencies"),
    ("@types/react", "@types/react-dom", "devDependencies"),
)

_MAJOR = re.compile(r"(\d+)")


def major_of(spec: str) -> Optional[str]:
    """Return the major number in a semver range such as ``^18.3.1``."""
    match = _MAJOR.search(spec or "")
    return match.group(1) if match else None


def mismatches(package_json: dict) -> list[str]:
    """Return a message for each pair sitting on different majors."""
    failures = []
    for left, right, section_name in PAIRS:
        section = package_json.get(section_name, {})
        if left not in section or right not in section:
            continue
        left_major = major_of(section[left])
        right_major = major_of(section[right])
        if left_major is None or right_major is None:
            failures.append(
                f"{section_name}: cannot read a major version from "
                f"{left} {section[left]!r} / {right} {section[right]!r}"
            )
            continue
        if left_major != right_major:
            failures.append(
                f"{section_name}: {left} {section[left]} and "
                f"{right} {section[right]} are different majors"
            )
    return failures


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) > 1:
        print(
            "usage: check_react_pins.py [package.json]",
            file=sys.stderr,
        )
        return 2

    path = Path(args[0]) if args else DEFAULT_PACKAGE_JSON
    try:
        package_json = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"No package.json at {path}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as error:
        print(f"Malformed package.json: {error}", file=sys.stderr)
        return 2

    failures = mismatches(package_json)
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        print(
            "\nreact and react-dom are released as a pair and must move "
            "together. Note @azure/msal-react caps react at 18.",
            file=sys.stderr,
        )
        return 1

    print("react/react-dom majors agree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
