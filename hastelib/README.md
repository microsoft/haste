# hastegeo

[![PyPI - Version](https://img.shields.io/pypi/v/hastegeo.svg)](https://pypi.org/project/hastegeo)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/hastegeo.svg)](https://pypi.org/project/hastegeo)

-----

## Table of Contents

- [Installation](#installation)
- [License](#license)

## Installation

```console
pip install "hastegeo @ https://github.com/microsoft/haste/releases/download/haste-binaries/hastegeo-<version>-py3-none-any.whl"
```

For local development from the repository root:

```console
pip install -e hastelib/
```

Local/editable installs report `0.0.0+local`. CI supplies the exact PEP 440
version when it builds an RC or stable wheel.

## Release process

`hatch build` is build-only. GitHub Actions resolves the version, builds and
tests without write credentials, then passes the wheel to a separate trusted
publisher that runs from the default branch. Merging a PR into `main` that
touches `hastelib/` publishes the next stable patch wheel — the review required
to land the commit is the release approval. Stable releases create a
`hastegeo-vX.Y.Z` source tag so reruns are idempotent.

## License

`hastegeo` is distributed under the terms of the [MIT](https://opensource.org/license/mit) license.
