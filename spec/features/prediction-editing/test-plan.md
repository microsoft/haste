# Test Plan: Versioned Prediction Editing

**Contents:** [Backend](#backend) - [Frontend](#frontend) -
[Release gate](#release-gate) - [Observed evidence](#observed-evidence)

## Backend

Cover schema validation, invalid/duplicate/out-of-bounds overrides, both producer
flavors, threshold boundaries, source identity and CRS, raw immutability,
version resolution, missing/unknown versions, paired sidecar saves, failed saves,
existing-version protection, model/layer validation, and protected downloads.

Use fixtures with differing raw and edited classes to prove both report
endpoints use the selected artifact. Assert explicit raw/older selection and
latest-default behavior, edited-class Assessment counts, and the edited
precision/recall operating point.

## Frontend

Use the existing Node runner for classification, version-selection, URL and
map-state helpers. Cover the post-save transition to the returned version,
raw downloads through the API, both panes' source/state reset, cancellation,
and the absence of preparation requests.
Assert that unchanged drafts cannot submit saves, selecting a class alone is not
an edit, and entering/rebinding editing performs no separate session request.
Cover class-filtered arrow traversal after reclassification, direct 1/2/3
annotation of the highlight, and exact location lookup for an unloaded building.
Verify Previous/Next follows the same traversal, the position is one-based
within the selected category, and empty categories disable both buttons.

Exercise the actual UI in isolated browser fixtures: pencil/E, click, Ctrl+box,
right-click reset, class-choice colors, a standard-only damage slider on raw and
saved versions, preserved manual assignments, undo, save failures, version
switch/download/report selection, dark mode and narrow layout. Do not modify
production authentication or the user's running stack to create fixtures.

## Release Gate

Targeted tests and UI build pass; changed-file lint has no new findings.
Record any baseline-wide lint failures separately rather than suppressing them.
The editing PR diff contains only this stage above the common-results base.

## Observed Evidence

The simplified stack's combined backend/native regression gate passed 248
cases. Model-only edit tests cover concurrent/idempotent saves, partial uploads,
source changes, historical versions, protected downloads and reports. Tests for
the removed shadow authority, reservation counters and receipt ledger are gone.

The deployed save-failure investigation compared wheel `1.0.44rc11` with
`9ded358`: all 104 non-version Python modules match. Both reported response
bodies identify the Python generic-error paths, not an absent APIM operation.
This establishes code parity and transport location, not the remote exception.

Additional regressions exercise Azure SDK policy-list handling, unchanged-policy
no-op behavior, preservation of unrelated policies, lease renewal/release error
classification, and credential-free error diagnostics on both save routes.
These use deterministic SDK mocks; no remote account access, prediction
submission, deployment, or existing project-data mutation is implied.
The combined policy/lease/storage/processor/API gate passed 95 cases. A separate
offline run in the API image passed 31 policy/lease/diagnostic cases using the
deployment's Azure Blob SDK 12.30.0, rather than only the host's SDK version.

The final merged editor's Node suite passed 206 cases, including the parent's
additional raw-download tests. Real Chrome/Azure Maps SDK/WebGL fixtures covered
gestures, complete pins, version selection, report/download choices, navigation
guards, and failure recovery. After 39 passing cases in the last broad pass,
six targeted notice cases closed its remaining failures, retaining the 650 ms
delayed-error reproduction and ordinary pointer hit-testing at 1440px and 390px.
Six direct real-browser smoke checks also passed against the simplified public
serializers: editing controls, save/version adoption, saved pins, lost-response
retry, historical results after clear, and reports. The UI bundle is unchanged.
All reported browser findings are closed. Fixture authentication and service
responses are not a claim of live Azure authentication or basemap validation.
