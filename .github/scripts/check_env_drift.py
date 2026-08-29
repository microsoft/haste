#!/usr/bin/env python3
"""Fail when an application setting the code requires is not deployed.

`hastegeo` reads its configuration from environment variables, and the Function
Apps receive those as application settings from two deploy paths:

    .github/scripts/deploy_apps.sh   (used by .github/workflows/deploy-apps.yml)
    infra/modules/functions.bicep    (used by the Bicep/IaC path)

Renaming a variable in code without renaming it in *both* deploy paths leaves
the setting silently unset, and the code falls back to a `<placeholder>` default
that only fails once Azure rejects it -- far from the cause. That is exactly how
`AZURE_BATCH_REGISTRY_SERVER` broke image preprocessing.

A variable is treated as REQUIRED when the code either reads it with no default
at all, or defaults it to a value still containing a `<placeholder>`. Anything
with a real, working default is optional and ignored.

Usage:  python .github/scripts/check_env_drift.py
Exit 0 when in sync, 1 otherwise.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

CODE_ROOTS = (
    REPO / "hastelib" / "src",
    REPO / "api" / "hastefuncapi",
    REPO / "api" / "hastefuncqueues",
    REPO / "api" / "titilerfuncapi",
)

DEPLOY_SH = REPO / ".github" / "scripts" / "deploy_apps.sh"
FUNCTIONS_BICEP = REPO / "infra" / "modules" / "functions.bicep"

PLACEHOLDER = re.compile(r"<[^<>]+>")

# Typed wrappers around os.getenv (e.g. `_get_bool_env`,
# `_get_bounded_int_env` in hastegeo.core.config). They take the variable name
# as the first argument and supply their own default in the signature, so a
# call is a genuine read even when no default is passed at the call site.
# Without this the scanner sees no reader and reports the setting as dead.
ENV_HELPER = re.compile(r"^_get_[a-z0-9_]*env$")

# Variables that are genuinely optional for an Azure deployment, with the reason
# each one is exempt. Anything not listed here that the code marks required must
# be emitted by both deploy paths.
ALLOWLIST = {
    "AzureFunctionsWebHost__hostId": "consumed by the Functions host runtime",
    # Alternative metadata/storage backends. Azure deployments use blob storage
    # (METADATA_STORAGE_TYPE=blob), so these are never read there.
    "COSMOS_ENDPOINT": "cosmos backend only",
    "COSMOS_DATABASE": "cosmos backend only",
    "COSMOS_CONTAINER": "cosmos backend only",
    "DATALAKE_ACCOUNT_URL": "datalake backend only",
    "DATALAKE_FILESYSTEM": "datalake backend only",
    "POSTGRES_HOST": "postgres backend only",
    "POSTGRES_PORT": "postgres backend only",
    "POSTGRES_USER": "postgres backend only",
    # pragma: allowlist nextline secret
    "POSTGRES_PASSWORD": "postgres backend only",  # pragma: allowlist secret
    "POSTGRES_DATABASE": "postgres backend only",
    "POSTGRES_TABLE": "postgres backend only",
    # Local docker-compose runner (RUNNER_TYPE=local); unused on Azure Batch.
    "AZURE_STORAGE_CONNECTION_STRING": "local runner only",
    "AZURE_STORAGE_ACCOUNT": "local runner only",
    "HASTE_DOCKER_NETWORK": "local runner only",
    "HASTE_DOCKER_MEM_LIMIT": "local runner only",
    "HASTE_DOCKER_SHM_SIZE": "local runner only",
    "HASTE_DOCKER_AZURITE_VOLUME": "local runner only",
    "HASTE_ENABLE_GPU": "local runner only",
    "HASTE_GPU_DEVICES": "local runner only",
    "HASTE_DATALOADER_WORKERS": "local runner only",
    "HASTE_DEBUG_VERBOSE": "local runner only",
    "CLEANUP_CONTAINERS": "local runner only",
    "PRESERVE_LOCAL_TASK_DIRS": "local runner only",
    "FAIL_ON_EMPTY_OUTPUT_LOG": "local runner only",
    # Set by the Batch node agent / supplied inside the task container.
    "WORKDIR": "set inside the task container",
    "INPUT_DIR": "set inside the task container",
    "OUTPUT_TRAINING_ZIP_NAME": "set inside the task container",
    "OUTPUT_INFERENCE_ZIP_NAME": "set inside the task container",
    # Azure Functions / platform-provided.
    "AzureWebJobsStorage": "provided by the Functions runtime",
    "WEBSITE_HOSTNAME": "provided by the Functions runtime",
    "FUNCTIONS_WORKER_RUNTIME": "provided by the Functions runtime",
    "AzureFunctionsWebHost__hostId": "consumed by the Functions host runtime",
    # Deprecated legacy name, still read as a fallback so environments
    # provisioned before the rename keep working. Deliberately not emitted.
    "AZURE_BATCH_REGISTRY_SERVER_URL": "deprecated legacy fallback",
    # GDAL tuning read inside the imageryprep/training container, where the
    # workflow supplies them; not Function App settings.
    "GDAL_SKIP": "read inside the task container",
    "GDAL_WARP_PARAMS": "read inside the task container",
    "GDAL_TRANSLATE_PARAMS": "read inside the task container",
}


def _literal(node: ast.AST):
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None


def scan_code() -> tuple[dict[str, set[Path]], set[str]]:
    """Return ({required var: files}, every var the code reads)."""
    required: dict[str, set[Path]] = {}
    seen: set[str] = set()

    for root in CODE_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts or "tests" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                name, default, has_default = None, None, False

                if isinstance(node, ast.Call):
                    func = node.func
                    is_getenv = (
                        isinstance(func, ast.Attribute)
                        and func.attr in ("getenv", "get")
                        and node.args
                    )
                    is_helper = (
                        isinstance(func, ast.Name)
                        and ENV_HELPER.match(func.id)
                        and node.args
                    )
                    if is_getenv:
                        target = ast.unparse(func)
                        if target.endswith(
                            ("os.getenv", "os.environ.get", "environ.get")
                        ):
                            name = _literal(node.args[0])
                            has_default = len(node.args) > 1
                            if has_default:
                                default = _literal(node.args[1])
                    elif is_helper:
                        name = _literal(node.args[0])
                        # The wrapper defines its own default, so the read is
                        # optional even with no default at the call site.
                        has_default = True
                        if len(node.args) > 1:
                            default = _literal(node.args[1])

                elif isinstance(node, ast.Subscript):
                    value = node.value
                    if isinstance(value, ast.Attribute) and ast.unparse(
                        value
                    ).endswith("os.environ"):
                        name = _literal(node.slice)

                if not isinstance(name, str):
                    continue
                seen.add(name)

                # Required = no default, or a default that is still a
                # <placeholder> the operator was meant to replace.
                unresolved = isinstance(default, str) and PLACEHOLDER.search(
                    default
                )
                if has_default and not unresolved:
                    continue
                required.setdefault(name, set()).add(path.relative_to(REPO))

    return required, seen


def settings_in_deploy_sh() -> set[str]:
    """Extract only the keys inside the `appsettings set --settings` block.

    Scanning the whole file would also pick up resource tags such as
    `project=haste`, which are not application settings.
    """
    names: set[str] = set()
    in_block = False
    for line in DEPLOY_SH.read_text(encoding="utf-8").splitlines():
        if "appsettings set" in line:
            in_block = True
            continue
        if in_block:
            names.update(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)=', line))
            if not line.rstrip().endswith("\\"):
                in_block = False
    return names


def settings_in_bicep() -> set[str]:
    text = FUNCTIONS_BICEP.read_text(encoding="utf-8")
    return set(re.findall(r"\{\s*name:\s*'([A-Za-z_][A-Za-z0-9_]*)'", text))


def main() -> int:
    required, all_read = scan_code()
    surfaces = {
        str(DEPLOY_SH.relative_to(REPO)): settings_in_deploy_sh(),
        str(FUNCTIONS_BICEP.relative_to(REPO)): settings_in_bicep(),
    }

    failures: list[str] = []
    for var in sorted(required):
        if var in ALLOWLIST:
            continue
        missing = [name for name, s in surfaces.items() if var not in s]
        if missing:
            readers = ", ".join(sorted(str(p) for p in required[var]))
            failures.append(
                f"  {var}\n"
                f"      read by:     {readers}\n"
                f"      NOT set by:  {', '.join(missing)}"
            )

    # Settings a deploy path emits that no code reads -- dead config, and a
    # strong signal that a rename was applied on only one side.
    dead: list[str] = []
    for surface, names in surfaces.items():
        for var in sorted(names):
            if var not in all_read and var not in ALLOWLIST:
                dead.append(f"  {var}  (set by {surface}, read by no code)")

    if failures:
        print(
            "Required application settings are not emitted by every "
            "deploy path:\n"
        )
        print("\n".join(failures))
    if dead:
        print("\nDead application settings (set but never read):\n")
        print("\n".join(dead))

    if failures or dead:
        print(
            "\nFix by updating .github/scripts/deploy_apps.sh and "
            "infra/modules/functions.bicep together, or add a documented "
            "entry to ALLOWLIST in this script."
        )
        return 1

    print("Application settings are in sync across code and deploy paths.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
