# Feature: GDAL 3.13 Native Runtime

**Status:** in-progress
**Author:** HASTE engineering team
**Date:** 2026-10-02
**Target Release:** next
**Priority:** P0
**Work Item:** —

## Summary

HASTE currently loads several different GDAL builds per process: the
GDAL 3.9.2 bindings wheel, plus the copies bundled inside the rasterio, fiona
and pyogrio wheels. The GDAL 3.9.2 wheel was built outside the repository.

This feature replaces all of them with **one HASTE-built GDAL 3.13.3 native
runtime**:

- **Built in CI** from pinned, checksum-verified sources, with a minimal
  driver set and raw VRT bands compiled out.
- **Shared by every binding.** Every GDAL-linked Python binding (GDAL/osgeo,
  rasterio, fiona, pyogrio, pyproj) is built against it, so each process
  loads exactly one libgdal and one PROJ.
- **Published with evidence.** The runtime and bindings are published as
  attested, immutable assets alongside a manifest of the drivers and virtual
  file systems they contain.

Every GDAL-bearing runtime then installs exactly those binaries and checks
itself against the manifest at startup.

## Motivation

- **Patched GDAL.** GDAL 3.9.2 carries memory-safety CVEs fixed in the 3.13
  line. The upgrade has been deferred because no trusted prebuilt wheel
  exists for HASTE's Python 3.11 Linux runtimes (see
  [`known-vulnerabilities.md`](../../../docs/known-vulnerabilities.md) Root
  Cause C).
- **No such wheel exists today.** Official GDAL Python releases are
  source-only. Wheels that bundle a newer GDAL either require Python 3.12 or
  bundle GDAL 3.12, not 3.13.
- **One registry to harden.** Several libgdal copies per process mean
  several driver registries. Driver restrictions applied through one binding
  don't apply to the others.
- **Provenance and immutability.** HASTE needs a GDAL build whose sources,
  configuration and resulting driver set are reviewable and reproducible.
  Every deployment should run one immutable artifact that can be checked
  from inside the running process.

## Success Criteria

- [ ] Each deployed runtime reports GDAL 3.13.3, measured from inside the
      process through every binding, and loads one libgdal.
- [ ] Each Python binding was built against, and is linked to, the same
      runtime.
- [ ] `GDAL_VRT_ENABLE_RAWRASTERBAND=NO` and `GDAL_VRT_ENABLE_PYTHON=NO` are
      active. A raw-band VRT and a Python pixel-function VRT both fail to
      open.
- [ ] Callers can't change GDAL configuration, driver paths or plugin paths,
      and plugin loading is disabled.
- [ ] The driver and virtual-file-system inventory of each runtime is
      published, and anything outside the needed set is absent or disabled.
- [ ] Untrusted inputs are only ever opened with an explicit driver
      allowlist that excludes VRT.
- [ ] No deployment configuration relaxes raw-VRT source restrictions. A CI
      guard and the startup self-check both enforce this.
- [ ] Function App packages are built once and deployed unchanged, and
      images are pinned by digest.

## HASTE Components Affected

| Component | Impact |
|---|---|
| `native/gdal-runtime/` | New: source lock, build scripts, manifest and smoke tests |
| `.github/workflows/` | New runtime build and publish workflow; dependency validation; deploy packaging |
| `hastelib/src/hastegeo/core/utils/` | Runtime self-check; untrusted-open restrictions; `harden_gdal()` rework |
| `api/hastefuncapi/`, `api/hastefuncqueues/` | Pinned runtime wheels; build-once packages |
| `api/titilerfuncapi/` | Locked dependencies on the HASTE runtime; startup self-check; VRT driver policy |
| `docker/imageryprep/`, `docker/training/` | Runtime wheels; hardening env; build-time self-check |
| `infra/`, `.github/scripts/deploy_apps.sh`, `azure.yaml` | GDAL hardening settings; package deployment |

## Related Specs

| Spec | Relationship |
|---|---|
| [gdal-compensating-controls](../gdal-compensating-controls/) | supersedes the deferral this feature closes |
| [function-network-baseline](../function-network-baseline/) | related: limits who can reach TiTiler |
| [ADR-0004](../../architecture/decisions/0004-gdal-driver-allowlist.md) | amended by [ADR-0007](../../architecture/decisions/0007-gdal-native-runtime.md) |

## Document Index

| Document | Purpose | Status |
|---|---|---|
| [design.md](design.md) | Technical design | in-progress |
| [impact-analysis.md](impact-analysis.md) | Risk, dependencies, blast radius | in-progress |
| [user-stories.md](user-stories.md) | Stories, acceptance criteria and agent map | in-progress |
| [plan.md](plan.md) | Phases and tasks | in-progress |
| [test-plan.md](test-plan.md) | Test strategy and evidence | in-progress |
| [rollout.md](rollout.md) | Rollout order and rollback | in-progress |

## Decision Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-10-02 | Build the GDAL stack from source in CI instead of consuming third-party wheels | No trusted GDAL 3.13 Python 3.11 wheel exists. Owning the build makes the configuration and driver set reviewable. |
| 2026-10-02 | One shared native runtime wheel that every binding links to | One libgdal and one PROJ per process: one driver registry to harden, and version consistency that is provable. |
| 2026-10-02 | Stay on Python 3.11 and build rasterio 1.4.4 | rasterio ≥ 1.5 requires Python 3.12. Moving Python is a separate change; the pipeline is parameterized by Python version. |
| 2026-10-02 | Build GDAL without GEOS | HASTE uses no cutlines or OGR geometry operations, so one fewer library to patch. |
| 2026-10-02 | Function App packages built once and deployed unchanged | A remote build re-resolves dependencies per environment, so a deployment is not one immutable artifact. |
