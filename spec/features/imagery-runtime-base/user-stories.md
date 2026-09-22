# User stories: imagery runtime base recovery

## US-001: restore imagery image builds

As a contributor, I want the imagery worker to build on a supported OS
without changing Python or bypassing package-repository validation.

Acceptance criteria:

- Use the digest-pinned Ubuntu 22.04/Python 3.11 base in [the design](design.md).
- Install the existing dependency pins in the isolated worker environment.
- Keep the Dockerfile compatible with ACR's existing builder.
- Recognize supported Python image tokens while rejecting unrelated names
  such as `copy311-runtime` and `cpython3.11-base`.
- Keep the developer-facing container reference aligned with the Dockerfile.

## US-002: preserve native imagery behavior

As an operator, I want the base change to preserve imagery outputs and the
worker's non-root execution without changing training or deployment settings.

Acceptance criteria:

- Cover COG pixels, compression, CRS, mosaicking, reprojection, JPEG previews,
  vector round trips, and blocked GDAL drivers with the native runtime tests.
- Preserve the task entrypoint, CLI commands, and existing dependency pins.
- Leave the training image, application behavior, and Azure configuration
  unchanged. Any deployment remains a separate approval.

## Agent Assignment Map

| Story | Implementing Agent(s) | Validating Agent(s) |
|---|---|---|
| US-001 | `backend-dev` | `backend-validation` |
| US-002 | `backend-dev`, `gis` | `backend-validation` |
