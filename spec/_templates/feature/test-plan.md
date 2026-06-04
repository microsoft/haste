# Test Plan: [Feature Title]

## Test Strategy

| Level | Scope | Tool/Framework | Coverage Target |
|---|---|---|---|
| Unit | `hastegeo` core logic | pytest (`hastelib/tests/`) | |
| Integration | API endpoints | pytest + Azure Functions test harness | |
| E2E | Full stack via Docker Compose | Docker Compose + manual / Playwright | |
| Performance | Batch processing, tile serving | locust / custom scripts | |

## Test Scenarios

### Unit Tests (`hastelib/tests/`)

| ID | Module | Scenario | Input | Expected Output | Story Ref |
|---|---|---|---|---|---|
| UT-001 | `hastegeo/core/models/` | | | | US-001 |
| UT-002 | `hastegeo/core/processors/` | | | | |
| UT-003 | `hastegeo/core/data_layer/` | | | | |
| UT-004 | `hastegeo/core/runners/` | | | | |

### API Integration Tests

| ID | Endpoint | Method | Scenario | Preconditions | Expected Response | Story Ref |
|---|---|---|---|---|---|---|
| IT-001 | `/api/...` | POST | | | 200 + body | US-001 |
| IT-002 | `/api/...` | GET | | | 200 + body | |
| IT-003 | `/api/...` | POST | Invalid input | | 400 | |

### Queue Worker Tests

| ID | Queue | Scenario | Message | Expected Side Effect | Story Ref |
|---|---|---|---|---|---|
| QT-001 | `[queue-name]` | | `{...}` | Blob artifact created | US-001 |
| QT-002 | `[queue-name]` | Malformed message | `{...}` | Dead-letter / error log | |

### UI Component Tests

| ID | Component | Scenario | User Action | Expected Behavior | Story Ref |
|---|---|---|---|---|---|
| UI-001 | `Components/...` | | Click / input | | US-001 |
| UI-002 | `Components/...` | | | | |

### End-to-End Tests (Docker Compose)

| ID | User Flow | Steps | Expected Outcome | Story Ref |
|---|---|---|---|---|
| E2E-001 | | 1. Start `docker-compose up` 2. ... 3. ... | | US-001 |

### Edge Case & Negative Tests

| ID | Scenario | Input | Expected Behavior |
|---|---|---|---|
| NEG-001 | Unauthenticated API request | No function key | 401 |
| NEG-002 | Non-existent project ID | Random UUID | 404 |
| EDGE-001 | Very large imagery file | >1GB GeoTIFF | Timeout handling |
| EDGE-002 | Concurrent project updates | Parallel PUT requests | Cosmos conflict resolution |

### Performance Tests

| ID | Scenario | Load Profile | Target Metric | Threshold |
|---|---|---|---|---|
| PERF-001 | API response time | 50 concurrent requests | p99 latency | <2s |
| PERF-002 | Queue processing throughput | 100 queued messages | Processing rate | >10/min |
| PERF-003 | Tile serving | 200 concurrent tile requests | p95 latency | <500ms |

## Test Data Requirements

| Dataset | Description | Source | Sensitive? |
|---|---|---|---|
| Sample GeoTIFF imagery | Small satellite image tiles | Synthetic / open data | no |
| Sample Cosmos documents | Project, layer, model configs | Synthetic | no |
| Label data | Sample GeoJSON annotations | Synthetic | no |

## Coverage Matrix

| User Story | Unit | API Integration | Queue | UI | E2E | Performance |
|---|---|---|---|---|---|---|
| US-001 | UT-001 | IT-001 | QT-001 | UI-001 | E2E-001 | — |
| US-002 | UT-002 | IT-002 | — | UI-002 | — | PERF-001 |

## Environment Requirements

| Environment | Purpose | Config |
|---|---|---|
| Local (Docker Compose) | Developer testing | `docker-compose.yml` with Azurite |
| CI (GitHub Actions) | Automated pipeline | `secret-scan.yml`, `deploy-apps.yml` |
| Dev1 SWA | Integration testing | SWA CLI `dev1` config |
| Testing SWA | Pre-production validation | SWA CLI `test` config |

## Sign-off Criteria

- [ ] All P0 stories have E2E coverage
- [ ] `hastelib` unit test coverage ≥ [X]%
- [ ] No P0/P1 bugs open
- [ ] Performance thresholds met
- [ ] `docker-compose up` runs clean
- [ ] GitHub Actions CI passes (secret-scan, deploy-apps)
- [ ] Component Governance scan clean (new dependencies)
