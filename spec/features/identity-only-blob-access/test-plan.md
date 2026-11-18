# Test plan: Keyless storage

| Layer | Required evidence |
|---|---|
| Unit | Identity clients, single-blob SAS, delegation lifetime/cache, Azurite, URL parsing, project prefix and legacy token replacement |
| API/processors | Trusted label materialization, mismatched linkage, nested artifacts, signed ETag freshness and no persisted response mutation |
| Upload | Out-of-order/retried chunks, cumulative limit, missing blocks, cancellation and another-instance finalization |
| UI | Expiry/tab resume/retry, transactional map updates, unsaved edits, version switches and explicit-null overlays |
| IaC/deploy | No Blob setting or File mount key, matching config paths, reviewed role grants, candidate trust negative cases |
| Live | Upload, imagery, labeling, training/inference, previews/downloads, PMTiles, publishing and scratch restart |
| Disablement | Identity/delegation success and Shared Key failure after approved cutover; redeploy preserves posture |

Run nearest tests first, then the documented core suite, UI lint/build,
environment drift check, shell syntax and Bicep compilation. Compare
platform-specific failures with current main and report them explicitly.
Use existing approved tooling/CI; do not install dependencies from blocked feeds.

## Local implementation evidence

- Focused backend/API regression suites pass, including authoritative label
  sources, project-prefix rejection, Azurite signing, unsigned Batch paths,
  delegation lifetime and durable upload ordering/retry/cancellation.
- `python -m unittest discover -s .github\scripts\tests -p "test_*.py" -q`:
  95 passed, including candidate provenance and post-publish mount cutover.
- `python -m unittest discover -s hastelib\tests\build -q`: 116 passed.
- `python .github\scripts\check_env_drift.py`, Git Bash `-n` on
  `.github/scripts/deploy_apps.sh`, Bicep compilation and configured pre-commit
  hooks pass. Compilation retains two unrelated APIM URL warnings.
- Existing native Python 3.11 full-suite run: 922 passed, 43 failed. Every
  failing test and error message matches the refreshed main baseline exactly
  (886 passed, the same 43 failures). The failures involve Windows `fcntl`,
  local artifact URLs and incompatible installed PROJ data.
- The documented Hatch command cannot reach tests locally: dependency
  reconciliation tries to build pinned GDAL without the required headers.
  This is not a passing pinned-runtime check; Linux/pinned-dependency CI remains
  required.
- UI credential-refresh and visualizer Node suites: 36 passed. Vite production
  build passes using existing local dependencies; the tree is not lockfile-exact.
  Full ESLint reports the same 159 errors and 7 warnings as main, with no added
  findings. The changed credential-refresh utility/tests lint clean.

No live validation, IaC what-if, candidate dispatch, identity-grant retirement,
policy revocation or Shared Key disablement is claimed. Those remain gated.

## Review follow-up evidence

- The native Python suite ran with 936 passes and 36 failures. All failing
  test identities and messages are present in the recorded main baseline;
  this run had fewer environment-dependent failures than that baseline.
- Artifact interface, local raster, authoritative signing and upload regression
  tests pass. An isolated Azurite container verified cancellation racing
  completion, incomplete-upload cleanup and rejection of a stale lease.
- The IaC isolation/cutover suite passes, Bicep compiles and environment
  settings drift check passes. Azure what-if and live deployment remain unrun.
- UI refresh and visualizer suites pass (37 tests); changed-file lint and the
  Vite build pass with reused, non-lockfile-exact dependencies.
- Runtime source tests pass after updating SQLite to 3.54.1. The native
  vulnerability scan remains a gate: an SQLite CLI advisory has no fixed
  release, and the OpenSSL vendor's fixed release has not yet shipped.
  Findings have not been suppressed.
