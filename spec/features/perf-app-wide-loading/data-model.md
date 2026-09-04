# Data Model: App-Wide Loading Performance

## Contents

- [Persistent Data](#persistent-data)
- [Bootstrap Response](#bootstrap-response)
- [Labeling Workspace Response](#labeling-workspace-response)
- [Active Jobs Response](#active-jobs-response)
- [Cache Keys](#cache-keys)
- [Migration](#migration)

## Persistent Data

No persistent schema, container, filesystem, queue, or Batch change is
introduced. Existing user ACL and published-dataset records remain compatible.

## Bootstrap Response

```json
{
  "user": {
    "userId": "string",
    "identityId": "string",
    "userRoles": ["string"],
    "settings": {},
    "status": "string"
  },
  "publishing": {
    "publishingEnabled": true,
    "providers": []
  }
}
```

## Labeling Workspace Response

```json
{
  "labelProject": {},
  "imageLayer": {
    "imageLayerId": "string",
    "name": "string",
    "sourceTypePostEvent": "string"
  },
  "eventTypes": [],
  "primaryClasses": []
}
```

The embedded records retain their existing field names. The response contains
one image layer and one label project rather than a complete project view.

## Active Jobs Response

```json
{
  "jobs": [
    {
      "key": "training-42",
      "kind": "Training",
      "projectName": "Project",
      "name": "Model",
      "target": "/project/project-id/layer-id",
      "indicator": {
        "id": "ongoingTraining-42",
        "currentStep": 2,
        "totalSteps": 5,
        "progressPct": 40,
        "status": "Running",
        "statusMessage": "",
        "prefix": "Training",
        "contextLabel": "Model: Model - Training"
      }
    }
  ]
}
```

## Cache Keys

| Data | Key | TTL | Invalidation |
|---|---|---:|---|
| Published dataset page | Caller plus normalized page, size, project, target, status, search, sort | <=5 s | Publishing mutations |
| Browser ETag | Same normalized query | Response lifetime | New `200` or mutation |
| Active jobs | Shared active-job representation | <=5 s | TTL; queue updates occur out of process |
| Active Jobs browser ETag | One route-local value | Response lifetime | New `200` |

Authorization state is never stored in these caches.

## Migration

No forward or backward migration is required. Rolling back discards
process-local caches and restores the legacy UI startup sequence.