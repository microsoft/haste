# App-Wide Loading Performance

This branch contains slices 1 through 4 of the seven-part split of PR #194.
The remaining slices are planned, not included in this branch.

## Scope

- Route Loading
- Cancellation and Loading Ownership
- Session Bootstrap
- Security
- Published Datasets
- Active Jobs

See [design](design.md) and [user stories](user-stories.md) for the applicable
contracts and acceptance criteria. Each slice carries focused regression tests.

## Rollout

No deployment is part of this history-only split. Session bootstrap remains
blocked on trusted Function ingress or signed identity validation. Production
route timings and real-credential Maps readiness remain unverified.
