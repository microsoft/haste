# Execution Plan: GDAL Deferral Compensating Controls

## Phases

### Phase 1: Core hardening module

**Goal:** Implement driver allowlist + sniffing/size helpers in `hastegeo`.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Audit GDAL/OGR drivers in use → finalize allowlist | `gis` | — | US-001 | done |
| Create `core/utils/gdal_security.py` (`harden_gdal`, `sniff_file_type`, `assert_*`, size envs) | `gis` | audit | US-001 | not-started |
| Wire `harden_gdal()` into parse sites + workflow/training entrypoints | `gis` | module | US-001 | not-started |
| Unit tests `tests/core/utils/test_gdal_security.py` | `backend-dev` | module | US-001 | not-started |

**Exit Criteria:**
- [ ] Allowlisted drivers present; HDF4/HDF5/netCDF deregistered.
- [ ] `harden_gdal()` idempotent; sniff/size helpers covered by tests.

### Phase 2: Ingestion boundaries

**Goal:** Size + type checks at upload; SSRF/size hardening at download.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Upload size cap + magic-byte check in `uploader.py` | `backend-dev` | Phase 1 | US-002 | not-started |
| SSRF/redirect + size cap in `downloader.py` | `backend-dev` | Phase 1 | US-003 | not-started |
| Tests: extend `test_uploader_format.py`; new `test_downloader.py` | `backend-dev` | above | US-002/3 | not-started |

**Exit Criteria:**
- [ ] Oversize/wrong-type uploads → 400; partial chunks cleaned.
- [ ] Imagery downloader refuses 3xx and caps size.

### Phase 3: Containers, docs, verification

**Goal:** Subprocess coverage + documented exception + weekly review.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| `GDAL_SKIP` env in `imageryprep`/`training` Dockerfiles | `backend-dev` | Phase 1 | US-001 | not-started |
| Update `known-vulnerabilities.md`, `security-configuration.md`, `triage-process.md`, `CHANGELOG.md` | `backend-dev` | Phase 1-2 | US-004 | not-started |
| Verify (conda/hatch or Docker) + imagery smoke | `backend-validation` | all | — | not-started |

**Exit Criteria:**
- [ ] Tests green in a GDAL-capable env; imagery smoke produces correct COG/JPEG/GPKG/GeoJSON.
- [ ] Docs reflect implemented controls + weekly cadence with exit criterion.

## Milestones

| Milestone | Deliverable |
|---|---|
| Spec approved | This spec set + ADR-0004 |
| Core hardening done | `gdal_security.py` + wiring + tests |
| Boundaries done | upload/download checks + tests |
| Docs + verify | docs updated, suite green, PR opened |

## Agent Summary

| Agent | Tasks Owned | Phases |
|---|---|---|
| `gis` | 3 | 1 |
| `backend-dev` | 6 | 2, 3 |
| `backend-validation` | 1 | 3 |
| `security` / `security-validation` | review | 3 |

## Resource Requirements

- **Agents:** `gis`, `backend-dev`, `backend-validation`, `security-validation`.
- **Azure services:** none new.
- **GPU compute:** none.
- **External data:** none (tests use synthetic fixtures).

## Open Questions

- [ ] Verification env: local Docker/WSL is wedged; run via `hatch run test:pytest` (conda) or Docker test image once healthy.
