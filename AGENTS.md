# Agent instructions for microsoft/haste

This file is read by AI coding agents (GitHub Copilot, Claude, Cursor,
Codex, etc.) when working in this repository. It collects the small set
of project-specific conventions that aren't obvious from the source
itself.

> **Mirrored at `.github/copilot-instructions.md`.** GitHub Copilot's
> chat reads that file directly; other tools read this one. Keep the two
> in sync — they cover the same guidance, though formatting and some
> sections differ between them.

---

## Code organization

### `function_app.py` is for HTTP endpoints only

`api/hastefuncapi/function_app.py` (and its sibling
`api/hastefuncqueues/function_app.py`) should contain **only top-level
`@app.route(...)` handlers** — the thin async wrappers that decode the
`func.HttpRequest`, call into business logic, and serialize a
`func.HttpResponse`.

Helpers, utilities, parsers, validators, computations, math, blob
plumbing — everything else — lives under
`hastelib/src/hastegeo/core/`. The function-app module imports them.

Rationale: keeping HTTP wrappers separate from logic lets the same code
be reached from unit tests, the CLI scripts in `validation/` and
`docker/training/code/`, and any future non-HTTP entrypoint. It also
keeps `function_app.py` from growing without bound — it's already over
3,600 lines.

A quick heuristic for new code:

- If you'd want to call it from a test without setting up a `HttpRequest`
  mock, it doesn't belong in `function_app.py`.
- If two endpoints would call it, it definitely doesn't.

The few helpers that **do** legitimately live in `function_app.py` are
ones that operate on `func.HttpRequest` / `func.HttpResponse` directly
(e.g. `_require_guid_param`, `_bad_request`, `_decode_client_principal`).
Anything that operates on plain data goes in `hastegeo`.

### Where things live in `hastegeo`

- `hastegeo.core.utils.*` — small leaf utilities (one module per
  concern). Examples: `blob`, `aoi`, `footprints`, `data`, `metadata`,
  `assessment`.
- `hastegeo.core.processors.*` — orchestration over the above (one per
  domain object: artifacts, imagery, inference, train, stats,
  metadata).
- `hastegeo.core.runners.*` — code that spawns and supervises Docker /
  Azure-Batch jobs.
- `hastegeo.core.models.*` — Pydantic schemas shared by API and storage.
- `hastegeo.workflows.*` — long-running scripted pipelines run inside
  the imageryprep / training containers.

### Tests live next to each module

`hastelib/tests/core/utils/test_<name>.py` and so on. Use `unittest`
style (subclass `unittest.TestCase`) — that's the dominant pattern in
the existing test files. `pytest` also runs both styles, so either
works in practice, but match the file you're nearest.

Run a single test file without setting up the conda env:

```bash
PYTHONPATH=$PWD/hastelib/src python -m unittest \
  hastelib.tests.core.utils.test_<name> -v
```

Run the full conda-backed suite:

```bash
cd hastelib && hatch run test:pytest
```

---

## Repository-wide patterns

### Package naming

The directory is `hastelib/` but the Python package is `hastegeo`. Old
docs and code may still say `haste`, `haste_geo`, or `hasteutils` —
those are stale leftovers from earlier renames. Always import as
`from hastegeo.core...`. Search for the older names with `grep` before
assuming.

### Pre-commit

Run `pre-commit install` once. Hooks (`.pre-commit-config.yaml`):
`black` and `isort` (both line-length 79), `flake8` (max-line=79,
ignoring E202/E203/E221/E231/E501/E713/W503), and `detect-secrets`.
**flake8 is blocking** — fix any `F401`/`F841` warnings in files you
touch even if they pre-date your change, otherwise the hook won't let
the commit through.

### Commit messages

Conventional-commit prefix (`feat`, `fix`, `refactor`, `style`,
`chore`, `docs`) with optional scope. Descriptive bodies are the norm;
reviewers expect them. Every commit ends with:

```
Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
```

### Docker compose dev stack

`docker compose -f docker/docker-compose.yml ...`. The persistent
services are `azurite`, `api-proxy`, `hastefuncapi`, `hastefuncqueues`,
`titiler`, `ui`. `data-init`, `imageryprep_image`, and `training_image`
are one-shot side-cars that exit after they run.

Three traps worth knowing:

1. `data-init` re-uploads `project_stats.json` with empty defaults on
   every `compose up`. Use `--no-deps` when recreating a single
   service: `compose up -d --no-deps --force-recreate hastefuncapi`.
   If you already wiped the stats, regenerate with
   `curl http://localhost:7071/api/GenerateProjectStats`.
2. `api-proxy` (nginx) caches the `hastefuncapi` upstream IP at
   startup. After recreating hastefuncapi, also
   `compose restart api-proxy`, otherwise `/api/*` returns 404.
3. The docker socket GID inside `hastefuncqueues` must match the host.
   `stat -c %g /var/run/docker.sock` to find the right value, then
   `echo DOCKER_GID=<n> >> docker/.env`.

### Wheel publishing (`hatch build -t wheel`)

`hastelib/haste_build.py` is a Hatchling custom hook that, on every
wheel build, **bumps the patch in `__about__.py`, uploads to a private
Azure blob, and rewrites `requirements.txt` pins across the repo**.
None of that should happen inside a Docker build, so the three
Dockerfiles that `pip install /tmp/hastelib/` set
`HASTE_SKIP_VERSION_BUMP=1`. Don't strip that. Only run `hatch build`
when you genuinely want to cut a release (and have `az login` set up).

---

## See also

- `QUICKSTART.md` — agent runbook to stand up the local stack (phased,
  verify-gated; for Claude Code / Copilot driving setup end-to-end).
- `README.md` — getting-started for the dev stack.
- `docker/README.md` — service-by-service docker compose architecture.
- `docs/development.md` — broader contributor guide.
- `docs/security-configuration.md` — production deployment guidance
  from PR #18.
