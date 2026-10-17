"""Decide what reconcile-titiler-baseline.ps1 removes.

TiTiler's identity may hold data roles only on its own host storage account,
and its APIM API may expose only the get-tiles operation. Bicep adds the
allowed state but never deletes what an earlier template or hook created, so
the reconcile script lists what exists and removes what this module names.

Reads JSON on stdin and prints one id or name per line:

    az role assignment list --all -o json | python titiler_baseline.py
        stale-roles --principal-id <id> --allowed-scope <storage account id>

    az apim api operation list ... -o json | python titiler_baseline.py
        stale-operations
"""

import argparse
import json
import sys

ALLOWED_OPERATIONS = frozenset({"get-tiles"})


def _normalize(scope: str) -> str:
    return scope.strip().rstrip("/").lower()


def stale_role_assignments(
    assignments: list, principal_id: str, allowed_scope: str
) -> list:
    """Ids of the principal's assignments outside ``allowed_scope``.

    Assignments on ``allowed_scope`` itself or on a child of it are kept.
    """
    allowed = _normalize(allowed_scope)
    principal = principal_id.strip().lower()
    if not allowed or not principal:
        raise ValueError("principal id and allowed scope are required")
    stale = []
    for assignment in assignments:
        if assignment.get("principalId", "").lower() != principal:
            continue
        scope = _normalize(assignment.get("scope", ""))
        if scope != allowed and not scope.startswith(allowed + "/"):
            stale.append(assignment["id"])
    return stale


def stale_operations(operations: list) -> list:
    """Names of APIM operations other than the allowed ones."""
    return [
        operation["name"]
        for operation in operations
        if operation["name"] not in ALLOWED_OPERATIONS
    ]


def main(argv: list) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    roles = commands.add_parser("stale-roles")
    roles.add_argument("--principal-id", required=True)
    roles.add_argument("--allowed-scope", required=True)
    commands.add_parser("stale-operations")
    args = parser.parse_args(argv)

    data = json.load(sys.stdin) or []
    if args.command == "stale-roles":
        result = stale_role_assignments(
            data, args.principal_id, args.allowed_scope
        )
    else:
        result = stale_operations(data)
    for item in result:
        print(item)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
