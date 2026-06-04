---
name: api-design
description: "Guide for designing and documenting RESTful APIs. Use when asked to design an API, create endpoints, or document an API."
source: "Internal engineering practices, REST API conventions"
domain: "architecture"
level: "intermediate"
agents: ["backend-dev", "gis"]
created_date: "2026-04-27"
last_validated: ""
validated_by: ""
status: "draft"
---

# API Design

## Overview

Standards and patterns for designing consistent, well-documented RESTful APIs. Covers naming, HTTP methods, error handling, status codes, and documentation requirements.

## Key Concepts

### Naming Conventions
- Plural nouns for resources: `/users`, `/orders`, `/products`
- Kebab-case for multi-word: `/user-profiles`
- Nest related resources: `/users/{id}/orders`
- Query params for filtering: `/users?role=admin&active=true`

### HTTP Methods

| Method | Purpose | Idempotent | Response |
|--------|---------|------------|----------|
| GET | Read | Yes | 200 + body |
| POST | Create | No | 201 + body + Location |
| PUT | Replace | Yes | 200 + body |
| PATCH | Partial update | No | 200 + body |
| DELETE | Remove | Yes | 204 (no body) |

### Error Response Format
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable description",
    "details": [
      {"field": "email", "message": "Invalid email format"}
    ]
  }
}
```

### Status Codes
- **200**: Success — **201**: Created — **204**: No content
- **400**: Bad request — **401**: Unauthorized — **403**: Forbidden
- **404**: Not found — **409**: Conflict — **422**: Unprocessable
- **429**: Rate limited — **500**: Internal error

## Decision Framework

| Scenario | Method | Path | Status |
|----------|--------|------|--------|
| List items | GET | /items | 200 |
| Get one item | GET | /items/{id} | 200 / 404 |
| Create item | POST | /items | 201 |
| Full update | PUT | /items/{id} | 200 / 404 |
| Partial update | PATCH | /items/{id} | 200 / 404 |
| Delete item | DELETE | /items/{id} | 204 / 404 |
| Search | GET | /items?q=term | 200 |
| Bulk action | POST | /items/batch | 200 / 207 |

## Documentation Requirements

Every endpoint must document:
1. HTTP method and path
2. Description
3. Request parameters (path, query, body) with types
4. Response schema with examples
5. Error codes and descriptions
6. Authentication requirements

## Common Pitfalls

- **Using verbs in URLs** — Use nouns: `/users` not `/getUsers`
- **Inconsistent error format** — Use the same error schema everywhere
- **Missing pagination** — Any list endpoint that can grow needs pagination
- **No versioning strategy** — Decide early: URL (`/v1/`) or header-based
