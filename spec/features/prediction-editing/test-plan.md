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

Exercise the actual UI in isolated browser fixtures: pencil/E, click, Ctrl+box,
right-click reset, arrows/Enter, standard-only sliders, save failures, version
switch/download/report selection, dark mode and narrow layout. Do not modify
production authentication or the user's running stack to create fixtures.

## Release Gate

Targeted tests and UI build pass; changed-file lint has no new findings.
Record any baseline-wide lint failures separately rather than suppressing them.
The editing PR diff contains only this stage above the common-results base.

## Observed Evidence

The combined backend/native regression gate passed 322 cases. Independent
review also exercised concurrent/idempotent saves, lost responses, source
changes, protected version selection, and 324 categorical report combinations.
Legacy raw report compatibility and model-list source/URL consistency have
native regression coverage.

The editor's Node suite passed 198 cases before incorporating the parent's
additional raw-download tests. Real Chrome/Azure Maps SDK/WebGL fixtures covered
gestures, complete pins, version selection, report/download choices, navigation
guards, and failure recovery. After 39 passing cases in the last broad pass,
six targeted notice cases closed its remaining failures, retaining the 650 ms
delayed-error reproduction and ordinary pointer hit-testing at 1440px and 390px.
All reported browser findings are closed. Fixture authentication and service
responses are not a claim of live Azure authentication or basemap validation.
