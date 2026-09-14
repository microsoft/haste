# Releasing HASTE

HASTE versions the product and library independently. RC validation uses a
matching wheel/image artifact set; that does not turn a library version
into a product-release version.

| What | Git tag | Artifact tag | Published as |
|---|---|---|---|
| **Product** (the HASTE platform) | `v2.1.0`, `v2.1.0-rc01` | — | A GitHub Release, notes from `CHANGELOG.md` |
| **`hastegeo` wheel** (Python library) | `hastegeo-v1.0.40` | `hastegeo-1.0.40-py3-none-any.whl` | An asset on the `haste-binaries` release |
| **Docker images** | — | `2.1.0`, `2.1.0-rc01` | Tags in ACR |

## Contents

- [Tag conventions](#tag-conventions)
- [Cutting a product release](#cutting-a-product-release)
- [What `haste-binaries` is](#what-haste-binaries-is)
- [Historical exceptions](#historical-exceptions)
- [Verified branch artifacts](#verified-branch-artifacts)

## Tag conventions

### Product — `v<MAJOR>.<MINOR>.<PATCH>`

Annotated tags. Release candidates append `-rc<NN>` with the RC number
**zero padded to two digits**: `v2.1.0-rc01`, `v2.1.0-rc02`. Padding keeps
tags and image tags sorting correctly in lexicographic listings, where
`rc1, rc10, rc2` sorts wrong.

Pushing a `v*` tag triggers [`release.yml`](.github/workflows/release.yml),
which publishes the GitHub Release. An `-rc<NN>` tag is published as a
prerelease. The **Latest** badge goes to the highest stable `v*` tag and
only to that one, so re-publishing notes for an older tag never steals
it and backfilling history never demotes a newer release.

### `hastegeo` wheel — `hastegeo-v<MAJOR>.<MINOR>.<PATCH>`

**Created automatically. Never tag these by hand.**
[`publish_hastegeo_wheel.py`](.github/scripts/publish_hastegeo_wheel.py)
creates the tag as part of publishing a stable wheel, and the tag is what
makes a re-run idempotent.

The wheel version itself is PEP 440 and therefore cannot carry the product
convention: `1.0.40rc1` has no dash and no zero padding, because PEP 440
normalizes `1.0.40-rc01` to `1.0.40rc1` regardless. Do not confuse that
library version with the product-release tag. Branch-validation image tags
explicitly follow their matching wheel version, as described below.

The wheel line (`1.0.x`) is versioned on its own cadence and has no
relationship to the product version (`2.x`). Do not try to sync them.

### Docker images — `<MAJOR>.<MINOR>.<PATCH>[-rc<NN>]`

Image tags carry the **product** version, matching the git tag with the
leading `v` dropped: git `v2.1.0-rc01` → image `2.1.0-rc01`. Nothing parses
an image tag as a PEP 440 version, so the dash and the zero padding are
both free here — and they act as a deliberate marker that a given tag is
**not** a wheel version.

For branch validation, `hastegeo-publish.yml` deliberately tags both worker
images with their matching RC wheel version. Use the complete artifact-set
manifest described below. Stable/product image publishing remains separate;
pass explicit product image tags for stable deployments.

## Verified branch artifacts

Automatic PR candidates use `X.Y.Zrc<build-run-id>`, not a shared
next-available RC counter. Their stable release baseline is frozen at the
build run's creation time. A rerun retains that version; later releases
cannot make the publisher look for a differently named wheel.

The credential-free build emits `build-manifest.json` with source/run
identity and the wheel checksum. The default-branch publisher independently
validates this identity. Existing matching RC bytes/provenance can be reused
so a failed image stage can resume; conflicting assets are never overwritten.
GitHub workflow artifacts include the upstream run attempt in their name.

Each worker image carries source/version labels, is verified by digest, and
is locked before it is included in `hastegeo-<version>-artifacts.json`.
That manifest contains the wheel provenance and both image digests.
Registry names remain protected configuration; public manifests contain
registry-independent references and a fingerprint instead.

An RC deployment must select the exact application source and a complete
matching manifest. It verifies registry identity and locked digests before
updating the environment, and pins the wheel URL with its checksum.
Pre-upgrade builds without this metadata require a fresh updated build.

Changes to the trusted publisher must be reviewed and merged into the
default branch before activation. Updating a PR alone does not authorize a
deployment or overwrite an existing release. Existing asset-retention
approval and stable-release rules remain in place.

## Cutting a product release

1. **Close out the changelog.** Rename `## [Unreleased]` to
   `## [v2.1.0] — <short title>`. The title after the em dash becomes the
   GitHub Release title, so make it descriptive. Open a fresh empty
   `## [Unreleased]` above it.
2. **Merge that PR.** The changelog on `main` is now the release notes.
3. **Tag the merge commit** and push:

   ```bash
   git tag -a v2.1.0 -m "v2.1.0"
   git push origin v2.1.0
   ```

4. `release.yml` extracts the matching `CHANGELOG.md` section, rewrites
   repo-relative links into permalinks at the tag, and publishes the
   release. It **fails loudly** if no section matches the tag.

To re-publish notes for a tag that already exists, run `release.yml` via
`workflow_dispatch` with the tag name; it updates the existing release in
place.

### Release candidates

Tag `v2.1.0-rc01` before the changelog section is renamed and the workflow
will fail — an RC tag reads the section for the stable version it is a
candidate for (`v2.1.0`). Rename the section first; publishing an RC is a
statement that the notes are final enough to review.

## What `haste-binaries` is

[`haste-binaries`](https://github.com/microsoft/haste/releases/tag/haste-binaries)
is **not a product release.** It is a permanent, append-only asset store for
pip-installable binaries: the GDAL manylinux wheel and every `hastegeo`
wheel ever published.

Its download URLs are pinned in
[`api/hastefuncapi/requirements.txt`](api/hastefuncapi/requirements.txt),
[`api/hastefuncqueues/requirements.txt`](api/hastefuncqueues/requirements.txt),
[`docker/imageryprep/requirements.txt`](docker/imageryprep/requirements.txt),
[`docs/requirements.txt`](docs/requirements.txt) and
[`deploy/pin-hastegeo-wheel.ps1`](deploy/pin-hastegeo-wheel.ps1), and
deployed Function Apps install from those pins at build time.

Its stable asset history is also the **version database**:
[`haste_release.py`](hastelib/haste_release.py) derives the next stable
version by parsing asset filenames. CI RC suffixes come from immutable
build identity, not a race-prone shared counter.

Both facts mean assets must **never be renamed, moved to another release,
or deleted** without first migrating every pin and moving version
resolution onto git tags. Pruning stale RC wheels is handled separately and
deliberately by [`rc-cleanup.yml`](.github/workflows/rc-cleanup.yml).

## Historical exceptions

These predate the conventions above and are left as-is:

- **`1.4.2-rc01`** — missing the `v` prefix, and points at a pre-merge
  commit that is not an ancestor of `main`.
- **`v2.0.0-rc42`** — RC number not zero padded.
- **`v1.4.2`** — no tag was cut at the time, although `CHANGELOG.md`
  documents it as shipped. The tag was reconstructed after the fact at
  `cb46855` (#15), the commit on `main` matching what `1.4.2-rc01` was
  cut from. The release notes are the original changelog section; only
  the commit anchor is inferred.
