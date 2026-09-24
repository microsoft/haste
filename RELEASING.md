# Releasing HASTE

HASTE versions three things independently. They are related but **never
equal**, and conflating them has broken deployments before.

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
normalizes `1.0.40-rc01` to `1.0.40rc1` regardless. This is the main reason
a wheel version can never be reused as a product or image tag.

The wheel line (`1.0.x`) is versioned on its own cadence and has no
relationship to the product version (`2.x`). Do not try to sync them.

Wheels publish on three channels, all to `haste-binaries`, all immutable:

| Channel | Version | Built by | Source tag |
|---|---|---|---|
| `release` | `1.0.40` | merge to `main` touching `hastelib/` | `hastegeo-v1.0.40` |
| `rc` | `1.0.40rc1` | a PR touching `hastelib/` | none |
| `dev` | `1.0.40.dev1` | **Build hastegeo wheel** dispatched on a branch | none |

Dev wheels exist to test a change in a *deployed* function app without
minting a release candidate: an RC additionally requires matching locked
images, because `deploy-apps.yml` makes image tags equal any `rc` wheel
version exactly. PEP 440 orders `1.0.40.dev1 < 1.0.40rc1 < 1.0.40`, so a dev
wheel can never shadow a release. They are pruned on the same schedule as
RCs — pin one in `.github/rc-retain.txt` if an environment depends on it.

The channel is derived from the triggering event, never from a build input,
so a dispatch cannot publish itself as stable however it was configured.

### Docker images — `<MAJOR>.<MINOR>.<PATCH>[-rc<NN>]`

Image tags carry the **product** version, matching the git tag with the
leading `v` dropped: git `v2.1.0-rc01` → image `2.1.0-rc01`. Nothing parses
an image tag as a PEP 440 version, so the dash and the zero padding are
both free here — and they act as a deliberate marker that a given tag is
**not** a wheel version.

To build them, dispatch
[`docker-build-and-push.yml`](.github/workflows/docker-build-and-push.yml)
with the **release tag selected in the ref dropdown** (tags are listed there
alongside branches) and the product version as `image_tag`. Building from a
tag while `image_tag` is still the `test-manual` placeholder fails the run
rather than publishing release code to a throwaway tag.

Images embed `hastegeo` as copied source, not an installed wheel, so the
build stamps `__about__.py` from the ref: a tag build gets the hastegeo
release reachable from it (the same rule `release.yml` uses to decide which
wheel a product release ships), and a branch build gets
`0.0.0+<branch>.<sha>`. The stamp is always derived, never typed, so a
branch image cannot be labelled as a release.

> **Known gap:** `hastegeo-publish.yml` still tags RC images with the
> resolved *wheel* version (e.g. `1.0.40rc4`), and there is no stable image
> build on merge at all — stable images are still built by hand via
> `workflow_dispatch`.
>
> Deploying is no longer affected: a blank `training_image_tag` /
> `imageprep_image_tag` now reuses the image the app being deployed is
> already running, read from its own `AZURE_BATCH_DOCKER_IMAGE`, rather than
> defaulting to the wheel version and pulling a tag that does not exist. Pass
> them explicitly only to *change* the image, or on a first deploy to an
> environment that has none.

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

Its asset list is also the **version database**:
[`haste_release.py`](hastelib/haste_release.py) derives the next stable
version and the next RC number by parsing asset filenames.

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
