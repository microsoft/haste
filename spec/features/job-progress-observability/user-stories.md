# User stories: shared job progress

## US-001: observe a running job

As an analyst, I want status and available progress while work runs so I can
distinguish active computation from waiting or failure.

Acceptance: empty/partial telemetry does not crash polling; recorded epoch
and elapsed information becomes visible without inventing an ETA.

## US-002: observe completion without optional telemetry

As an analyst, I want successful completion to be visible even if the event
file is unavailable.

Acceptance: successful business completion reports complete progress;
failure/cancellation remain distinct; missing messages do not hide status.

## US-003: inspect live workflow output

As a developer, I want child stdout/stderr while a workflow step is still
running so I can diagnose slow work without restarting it.

Acceptance: both streams are visible before child exit; nonzero exits stay
explicit in workflow status and backend logs.

## Agent Assignment Map

| Story | Implementing agent | Validating agent |
|---|---|---|
| US-001 | backend-dev; ui | backend-validation; ui-validation |
| US-002 | backend-dev; ui | backend-validation; ui-validation |
| US-003 | backend-dev | backend-validation |
