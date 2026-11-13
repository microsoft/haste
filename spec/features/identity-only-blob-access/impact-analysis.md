# Impact analysis: Keyless storage

The cutover affects Blob/Queue clients, read-token issuance, upload staging,
labeling and visualizer URLs, downloads, Function storage configuration and
deployment trust. Batch credentials and unrelated storage accounts are excluded.

| Risk | Control |
|---|---|
| Signing client-editable links discloses another project's data | Derive label sources from trusted ImageLayer records and enforce the project prefix |
| Existing URLs or long sessions expire | Renew response copies; ETags cover signed payloads; UI refresh preserves state |
| Scratch removal breaks multi-request uploads | Persist staged blocks in Blob; validate finalization and instance changes |
| Deployment clears credentials before compatible code runs | Reconcile only after successful compatible package publication |
| RBAC tightening removes required host/worker access | Inventory effective identities/operations; add grants before retiring old ones |
| Candidate deployment weakens production | Exact-source attestation, repository/event checks and dev1-only branch gate |
| Shared Key disablement breaks hidden consumers | Separate per-account audit and approval; retain File data and rollback metadata |

Do not broaden TiTiler's data permissions or alter existing network containment.
Do not assume all SAS telemetry represents account-key authorization.
