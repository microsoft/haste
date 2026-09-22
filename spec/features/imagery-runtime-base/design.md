# Design: imagery runtime base recovery

## Table of contents

- [Scope](#scope)
- [Candidate](#candidate)
- [Compatibility validation](#compatibility-validation)
- [Rollout boundary](#rollout-boundary)
- [Sources](#sources)

## Scope

This changes only the CPU imagery worker base and the build guard that reads its
Python version. No Function host, training/CUDA image, GPU pool, Python version,
application behavior, or storage configuration changes.

The old `4-nightly-python3.11-slim` image uses Debian 11. Debian 11 LTS ended
August 31, 2026, and its final security metadata expired September 7. Disabling
APT validity or signature checks is not an acceptable recovery.

## Candidate

Use `mcr.microsoft.com/azureml/curated/minimal-py311-inference:59` pinned to
manifest digest
`sha256:89a46a46b71b4692731654d0523f53c8d14929e41ea8129293dc4e39fcabb14c`.
Registry metadata identifies Linux AMD64 and Ubuntu 22.04; the official
environment specifies Python 3.11. Its default user is `dockeruser`, so build-time
package installation must explicitly use root before restoring the existing
`appuser` task identity.

The Azure ML source labels this curated environment Preview. Keep that support
caveat visible during review. Do not substitute a floating `latest` tag for the
digest that was tested.

This image contains an inference environment, but HASTE retains its own task
entrypoint and does not start the Azure ML HTTP inference server. HASTE installs
its unchanged requirements in `/opt/haste-venv`, not that inference environment:
the bundled server requires a different Pydantic version. `pip check` must pass
for the active worker environment before the build succeeds.

## Compatibility validation

Use a unique local image tag and do not prune shared Docker state. Remote image
validation runs through the existing GitHub Actions workflows, not a local
Azure deployment.

The managed-machine feed restriction does not apply to the current remote build
environment. Keep the existing remote index behavior. Managed local builds must
explicitly supply their approved unauthenticated index using
`--build-arg PIP_INDEX_URL=<approved-index>`. This has no source-controlled default
and does not set a runtime `ENV` value.

Build arguments can appear in build metadata: this input accepts a non-secret
index URL, not credentials. Do not commit a device-proxy URL, place credentials
in a build argument, or fall back to public PyPI when a managed local build is
blocked. An authenticated feed would require a separate credential-safe design.

Build with the existing requirements, then run offline native smoke tests as
the non-root image user. Verify Python and GDAL versions, raster pixels/CRS,
COG layout and compression, reprojection, preview creation, vector read/write,
and the existing blocked-driver policy. Run the existing imagery utility and
preparation workflow tests against the image's own copied `hastegeo`.

CI must recognize both Functions references such as `python:4-python3.11-slim`
and Azure ML references such as `minimal-py311-inference`. An unrecognized or
different Python version must still fail; do not replace the guard with a
hardcoded success.

## Rollout boundary

Local evidence does not deploy this candidate or resolve the release gate.
Retain the previous production images. A later reviewed release must still use
GitHub Actions and matching image provenance. The initial remote test confirmed
that ACR quick builds use the legacy Docker builder and reject `RUN --mount`.
The compatible Dockerfile therefore uses ordinary `ARG`/`RUN` instructions;
neither the manual image Action nor the default-branch RC publisher needs a
builder migration. Validate the actual ACR image jobs rather than a skipped PR
build gate. This shared fix belongs in upstream HASTE; downstream
forks should receive it through synchronization rather than independent patches.
Remote test publication is authorized; application deployment is not.

## Sources

- [Debian 11 LTS end of life](https://www.debian.org/News/2026/20260831)
- [Official candidate environment](https://github.com/Azure/azureml-assets/blob/a95ee2255d3a5a405da83f3b90ce8ddf40085f79/assets/inference/environments/minimal-py311-inference/spec.yaml)
- [Official Python environment](https://github.com/Azure/azureml-assets/blob/a95ee2255d3a5a405da83f3b90ce8ddf40085f79/assets/inference/environments/minimal-py311-inference/context/conda_dependencies.yaml)
- [MCR candidate tags](https://mcr.microsoft.com/v2/azureml/curated/minimal-py311-inference/tags/list)
