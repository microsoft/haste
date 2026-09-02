# Data Model: App-Wide Loading Performance

## Contents

- [Persistent Data](#persistent-data)
- [Bootstrap Response](#bootstrap-response)
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

## Cache Keys

| Data | Key | TTL | Invalidation |
|---|---|---:|---|
| Published dataset page | Caller plus normalized page, size, project, target, status, search, sort | <=5 s | Publishing mutations |
| Browser ETag | Same normalized query | Response lifetime | New `200` or mutation |

Authorization state is never stored in these caches.

## Migration

No forward or backward migration is required. Rolling back discards
process-local caches and restores the legacy UI startup sequence.