"""HASTE GDAL native runtime: configuration, hardening and a fail-closed check.

The wheel bundles one libgdal (with PROJ and their dependencies) that every
GDAL-linked binding links to. A process uses it in three steps:

    import haste_gdal_runtime as runtime
    runtime.configure(POLICY)        # before importing any GDAL binding
    import rasterio                  # the binding loads the runtime's libgdal
    runtime.secure_startup(POLICY)   # restrict, then verify or raise

``configure`` sets the operator-owned GDAL settings when the environment has
not set them, ``harden`` removes drivers and virtual file systems the policy
does not allow, and ``verify_or_raise`` compares the live process with the
build manifest and the policy. The library location is fixed by the
installed wheel and never read from the environment.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, MutableMapping

from ._native import NativeGdal, mapped_libraries

PACKAGE_DIR = Path(__file__).resolve().parent
LIBS_DIR = PACKAGE_DIR.parent / "haste_gdal_runtime.libs"
GDAL_DATA_DIR = PACKAGE_DIR / "share" / "gdal"
PROJ_DATA_DIR = PACKAGE_DIR / "share" / "proj"
CONFIG_FILE = PACKAGE_DIR / "gdalrc"
MANIFEST_PATH = PACKAGE_DIR / "manifest.json"

# Operator-owned hardening. configure() applies these when the environment
# leaves them unset; evaluate() fails when the effective value differs.
REQUIRED_CONFIG = {
    "GDAL_VRT_ENABLE_RAWRASTERBAND": "NO",
    "GDAL_VRT_ENABLE_PYTHON": "NO",
    "GDAL_DRIVER_PATH": "disable",
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_HEADER_FILE_KVP_ENABLED": "NO",
}

# Locations GDAL and PROJ read data and settings from. They must point into
# this package so no other file can change the runtime's behaviour.
PINNED_PATHS = {
    "GDAL_DATA": GDAL_DATA_DIR,
    "PROJ_DATA": PROJ_DATA_DIR,
    "GDAL_CONFIG_FILE": CONFIG_FILE,
}

_TRUE_VALUES = frozenset({"YES", "TRUE", "ON", "1"})
_FALSE_VALUES = frozenset({"NO", "FALSE", "OFF", "0"})

# Settings that relax a protection. Any of these fails the check.
FORBIDDEN_CONFIG = {
    "GDAL_VRT_RAWRASTERBAND_ALLOWED_SOURCE": lambda v: v.upper() == "ALL",
    "GDAL_VRT_PYTHON_TRUSTED_MODULES": lambda v: v != "",
    "GDAL_PYTHON_DRIVER_PATH": lambda v: v != "",
    "CPL_ENABLE_PATH_TRAVERSAL_DETECTION": lambda v: v.upper()
    in _FALSE_VALUES,
    "GDAL_HTTP_UNSAFESSL": lambda v: v.upper() in _TRUE_VALUES,
}

CA_BUNDLE_KEYS = ("CURL_CA_BUNDLE", "SSL_CERT_FILE")

WATCHED_CONFIG = sorted(
    {
        *REQUIRED_CONFIG,
        *PINNED_PATHS,
        *FORBIDDEN_CONFIG,
        *CA_BUNDLE_KEYS,
        "GDAL_SKIP",
    }
)

# Virtual file systems the HASTE workloads need: in-memory files, HTTPS range
# reads, and the two handlers the GeoTIFF driver uses internally.
DEFAULT_ALLOWED_VSI = frozenset(
    {"/vsimem/", "/vsicurl/", "/vsisubfile/", "/vsisparse/"}
)

BINDINGS = ("osgeo.gdal", "rasterio", "fiona", "pyogrio", "pyproj")

_CA_BUNDLES = (
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/tls/certs/ca-bundle.crt",
)


class RuntimeCheckError(RuntimeError):
    """The live GDAL runtime is not the approved one."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__(
            "GDAL runtime check failed:\n  - " + "\n  - ".join(problems)
        )


@dataclass(frozen=True)
class Policy:
    """What one HASTE runtime requires of the GDAL runtime.

    ``allowed_drivers`` of None keeps every driver in the build.
    """

    expected_gdal: str
    allowed_drivers: frozenset[str] | None = None
    allowed_vsi: frozenset[str] = DEFAULT_ALLOWED_VSI
    required_bindings: tuple[str, ...] = ()


def library_path(stem: str = "libgdal") -> Path:
    matches = sorted(LIBS_DIR.glob(f"{stem}-*.so*"))
    if len(matches) != 1:
        raise RuntimeCheckError(
            [f"expected one {stem} in {LIBS_DIR}, found {len(matches)}"]
        )
    return matches[0]


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


_NATIVE: dict[Path, NativeGdal] = {}


def _native(library: Path | None) -> NativeGdal:
    path = Path(library) if library else library_path()
    if path not in _NATIVE:
        _NATIVE[path] = NativeGdal(path)
    return _NATIVE[path]


def skip_list(manifest: dict[str, Any], policy: Policy) -> list[str]:
    """Drivers in the build that ``policy`` does not allow."""
    if policy.allowed_drivers is None:
        return []
    return sorted(set(manifest.get("drivers", [])) - policy.allowed_drivers)


def configure(
    policy: Policy | None = None,
    environ: MutableMapping[str, str] | None = None,
    manifest: dict[str, Any] | None = None,
) -> None:
    """Apply data paths and hardening defaults to the process environment.

    Values already set are left alone, so evaluate() still reports any
    operator setting that weakens a protection. Drivers the policy does not
    allow are added to GDAL_SKIP, which GDAL applies after every driver
    registration, including registrations a binding makes later.
    """
    env = os.environ if environ is None else environ
    for key, path in PINNED_PATHS.items():
        env.setdefault(key, str(path))
    for key, value in REQUIRED_CONFIG.items():
        env.setdefault(key, value)
    if not any(env.get(key) for key in CA_BUNDLE_KEYS):
        for candidate in _CA_BUNDLES:
            if os.path.isfile(candidate):
                env["CURL_CA_BUNDLE"] = candidate
                break
    if policy is not None and policy.allowed_drivers is not None:
        skipped = skip_list(manifest or load_manifest(), policy)
        existing = [
            name
            for name in re.split(r"[,\s]+", env.get("GDAL_SKIP", ""))
            if name
        ]
        merged = list(dict.fromkeys(existing + skipped))
        if merged:
            env["GDAL_SKIP"] = ",".join(merged)


def harden(
    policy: Policy, *, library: Path | None = None
) -> dict[str, list[str]]:
    """Remove the drivers and virtual file systems ``policy`` does not allow.

    Run after the bindings are imported. Removed file systems stay removed
    for the life of the process; removed drivers also stay out because
    configure() lists them in GDAL_SKIP.
    """
    native = _native(library)
    removed_drivers: list[str] = []
    if policy.allowed_drivers is not None:
        removed_drivers = native.deregister_drivers(
            set(native.drivers()) - policy.allowed_drivers
        )
    removed_vsi = native.remove_vsi_handlers(
        set(native.vsi_prefixes()) - policy.allowed_vsi
    )
    return {"drivers": removed_drivers, "vsi_prefixes": removed_vsi}


def _binding_info(name: str, module: Any) -> dict[str, str]:
    info = {"version": str(getattr(module, "__version__", ""))}
    if name == "osgeo.gdal":
        info["gdal"] = module.VersionInfo("RELEASE_NAME")
    elif name in ("rasterio", "fiona"):
        info["gdal"] = str(module.__gdal_version__)
    elif name == "pyogrio":
        info["gdal"] = str(module.__gdal_version_string__)
    elif name == "pyproj":
        info["proj"] = str(
            getattr(module, "__proj_version__", None)
            or module.proj_version_str
        )
    return info


def _import_bindings(names: tuple[str, ...]) -> dict[str, dict[str, str]]:
    found = {}
    for name in names:
        if importlib.util.find_spec(name.split(".")[0]) is None:
            continue
        found[name] = _binding_info(name, importlib.import_module(name))
    return found


def report(
    *, bindings: tuple[str, ...] = BINDINGS, library: Path | None = None
) -> dict[str, Any]:
    """Collect evidence about the GDAL runtime loaded in this process."""
    imported = _import_bindings(bindings)
    native = _native(library)
    config = {key: native.config(key) for key in WATCHED_CONFIG}
    ca_bundle = next(
        (config[key] for key in CA_BUNDLE_KEYS if config.get(key)), None
    )
    raw_band_flag = native.driver_metadata(
        "VRT", "GDAL_VRT_ENABLE_RAWRASTERBAND"
    )
    return {
        "library": str(native.path),
        "gdal_release": native.version_info("RELEASE_NAME"),
        "build_info": native.build_info(),
        "drivers": native.drivers(),
        "vsi_prefixes": native.vsi_prefixes(),
        "vrt_raw_band_compiled": raw_band_flag == "YES",
        "config": config,
        "ca_bundle": {
            "path": ca_bundle,
            "exists": bool(ca_bundle) and os.path.isfile(ca_bundle),
        },
        "mapped_libgdal": mapped_libraries("libgdal"),
        "mapped_libproj": mapped_libraries("libproj"),
        "bindings": imported,
        "probes": native.probes(),
        "probes_permissive": native.probes(permissive=True),
    }


def _same_path(left: str | None, right: Path) -> bool:
    return bool(left) and os.path.realpath(left) == os.path.realpath(right)


def _check_versions(
    observed: dict[str, Any], manifest: dict[str, Any], policy: Policy
) -> list[str]:
    problems = []
    expected = policy.expected_gdal
    if observed["gdal_release"] != expected:
        problems.append(
            f"libgdal is {observed['gdal_release']}, expected {expected}"
        )
    if manifest.get("gdal_release") != expected:
        problems.append(
            f"installed runtime was built for GDAL "
            f"{manifest.get('gdal_release')}, expected {expected}"
        )
    for name in policy.required_bindings:
        if name not in observed["bindings"]:
            problems.append(f"required binding {name} is not installed")
    for name, info in observed["bindings"].items():
        if "gdal" in info and info["gdal"] != expected:
            problems.append(
                f"{name} reports GDAL {info['gdal']}, expected {expected}"
            )
        if "proj" in info and info["proj"] != manifest.get("proj_release"):
            problems.append(
                f"{name} reports PROJ {info['proj']}, runtime has "
                f"{manifest.get('proj_release')}"
            )
    return problems


def _check_libraries(observed: dict[str, Any]) -> list[str]:
    problems = []
    library = os.path.realpath(observed["library"])
    mapped = sorted({os.path.realpath(p) for p in observed["mapped_libgdal"]})
    if mapped != [library]:
        problems.append(
            f"expected only the runtime's libgdal mapped, found {mapped}"
        )
    libs_dir = os.path.dirname(library)
    proj = sorted({os.path.realpath(p) for p in observed["mapped_libproj"]})
    if len(proj) > 1 or any(os.path.dirname(p) != libs_dir for p in proj):
        problems.append(f"expected only the runtime's libproj, found {proj}")
    return problems


def _check_inventory(
    observed: dict[str, Any], manifest: dict[str, Any], policy: Policy
) -> list[str]:
    problems = []
    registered = set(observed["drivers"])
    unknown = sorted(registered - set(manifest.get("drivers", [])))
    if unknown:
        problems.append(f"drivers not in the build manifest: {unknown}")
    if policy.allowed_drivers is not None:
        extra = sorted(registered - policy.allowed_drivers)
        if extra:
            problems.append(f"drivers outside the policy: {extra}")
    prefixes = set(observed["vsi_prefixes"])
    unknown_vsi = sorted(prefixes - set(manifest.get("vsi_prefixes", [])))
    if unknown_vsi:
        problems.append(f"file systems not in the manifest: {unknown_vsi}")
    extra_vsi = sorted(prefixes - policy.allowed_vsi)
    if extra_vsi:
        problems.append(f"file systems outside the policy: {extra_vsi}")
    if "/vsicurl/" in prefixes and not observed["ca_bundle"]["exists"]:
        problems.append(
            "HTTPS reads are enabled but no CA bundle file is configured"
        )
    return problems


def _check_config(observed: dict[str, Any]) -> list[str]:
    problems = []
    config = observed["config"]
    for key, expected in REQUIRED_CONFIG.items():
        actual = config.get(key)
        if (actual or "").upper() != expected.upper():
            problems.append(f"{key} is {actual!r}, expected {expected!r}")
    for key, relaxes in FORBIDDEN_CONFIG.items():
        actual = config.get(key)
        if actual is not None and relaxes(actual):
            problems.append(f"{key}={actual!r} is not allowed")
    for key, path in PINNED_PATHS.items():
        if not _same_path(config.get(key), path):
            problems.append(f"{key} is {config.get(key)!r}, expected {path}")
    return problems


def _check_vrt(
    observed: dict[str, Any], manifest: dict[str, Any], policy: Policy
) -> list[str]:
    problems = []
    if manifest.get("vrt_raw_band_compiled") is not False:
        problems.append("the runtime was built with VRT raw bands")
    if observed["vrt_raw_band_compiled"]:
        problems.append("the loaded libgdal has VRT raw bands compiled in")
    for source, probes in (
        ("build", manifest.get("probes_permissive", {})),
        ("configured", observed["probes"]),
        ("permissive", observed["probes_permissive"]),
    ):
        for probe in ("raw_band", "python_pixel_function"):
            if probes.get(probe) not in ("rejected", "read-failed"):
                problems.append(
                    f"{probe} probe ({source} settings) returned "
                    f"{probes.get(probe)!r}"
                )
    vrt_allowed = (
        policy.allowed_drivers is None or "VRT" in policy.allowed_drivers
    )
    if not vrt_allowed and observed["probes"].get("vrt_driver") != "rejected":
        problems.append("a VRT document opened although VRT is not allowed")
    return problems


def evaluate(
    observed: dict[str, Any], manifest: dict[str, Any], policy: Policy
) -> list[str]:
    """Return every way ``observed`` differs from what is approved."""
    return [
        *_check_versions(observed, manifest, policy),
        *_check_libraries(observed),
        *_check_inventory(observed, manifest, policy),
        *_check_config(observed),
        *_check_vrt(observed, manifest, policy),
    ]


def verify(policy: Policy) -> list[str]:
    return evaluate(report(), load_manifest(), policy)


def verify_or_raise(policy: Policy) -> dict[str, Any]:
    """Raise RuntimeCheckError unless the process matches ``policy``.

    Returns the report so callers can log it as evidence.
    """
    observed = report()
    problems = evaluate(observed, load_manifest(), policy)
    if problems:
        raise RuntimeCheckError(problems)
    return observed


def secure_startup(policy: Policy) -> dict[str, Any]:
    """Harden the process, then verify it. Returns the evidence report."""
    removed = harden(policy)
    observed = verify_or_raise(policy)
    observed["removed"] = removed
    return observed
