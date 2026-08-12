# Execution Plan: Batch node-loss resilience

## Phases

### Phase 1: Core Library

**Goal:** Make the Batch runner tolerate node loss, and let imagery recover its
outputs from blob storage.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Classify transient vs terminal node errors in `runners/azure_batch.py` | `backend-dev` | — | US-001 | done |
| Retry transient node errors; `reraise=True` on exhaustion | `backend-dev` | above | US-001 | done |
| `get_filecontent_from_task` returns `None` on node loss | `backend-dev` | above | US-001 | done |
| `cleanup_task` tolerates node loss, still disables the job | `backend-dev` | above | US-004 | done |
| Accept `file_pattern` as `str \| list[str]` in `add_task` | `backend-dev` | — | US-002 | done |
| Mirror list handling in `runners/local.py` | `backend-dev` | above | US-002 | done |
| Add `utils/errors.py::describe_exception` | `backend-dev` | — | US-003 | done |
| Add `utils/blob.py::fetch_url_text` | `backend-dev` | — | US-001 | done |
| Add `ImageryPostProcessor._read_task_output` with blob fallback | `backend-dev` | runner tasks | US-001, US-002 | done |
| Submit `outputs/` **and** `logs/` for upload from imagery | `backend-dev` | `add_task` change | US-002 | done |
| Unit tests: runner node errors | `backend-dev` | runner tasks | US-001, US-004 | done |
| Unit tests: imagery fallback + upload patterns | `backend-dev` | imagery tasks | US-001, US-002 | done |
| Unit tests: exception formatter | `backend-dev` | `utils/errors.py` | US-003 | done |
| Repair the `clipBbox` fixture gap in `test_imagery_preprocess_config.py` | `backend-dev` | — | — | done |

**Exit Criteria:**
- [x] All new unit tests pass (31)
- [x] No new failures in the `hastelib` suite versus a clean worktree at HEAD
- [x] Core logic works without any API-layer involvement

### Phase 2: Queue workers

**Goal:** Stop the imagery trigger from destroying the status history, and make
the recorded cause readable.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Append instead of assign `statusMessage` in the imagery trigger | `backend-dev` | Phase 1 | US-003 | done |
| Render the cause via `describe_exception` | `backend-dev` | Phase 1 | US-003 | done |
| Apply the formatter to train / embedding / inference messages | `backend-dev` | Phase 1 | US-003 | done |

**Exit Criteria:**
- [x] No business logic added to `function_app.py` (formatter lives in `hastegeo`)
- [x] flake8 / black / isort clean on the touched files

### Phase 3: Docs & spec

**Goal:** Bring documentation in line with the new read path.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Update `api/hastefuncqueues/README.md` (manifest/log source) | `backend-dev` | Phase 1 | US-001 | done |
| Update `docs/api/hastefuncqueues.md` (manifest/log source) | `backend-dev` | Phase 1 | US-001 | done |
| Write this spec set | `backend-dev` | Phases 1–2 | — | done |

**Exit Criteria:**
- [x] Docs no longer claim the files are read only from the task working directory
- [x] Spec records root cause, design, and rejected alternatives

## Milestones

| Milestone | Deliverable | Status |
|---|---|---|
| Root cause confirmed | Traced from the dev1 status message to the node-scoped file APIs | done |
| Core library done | `hastelib` runner + processor + utils changes | done |
| Queue workers done | Readable, appended status messages | done |
| Docs & spec done | Spec set + updated queue docs | done |
| Verified on dev1 | Manual verification per [test-plan.md](test-plan.md#manual-verification-dev1) | pending |

## Agent Summary

| Agent | Tasks Owned | Phases |
|---|---|---|
| `backend-dev` | 19 | 1, 2, 3 |
| `backend-validation` | validation of all phases | 1, 2 |
| `orchestrator` | spec status tracking | 3 |

## Resource Requirements

- **Agents:** `backend-dev` implements, `backend-validation` validates.
- **Azure services:** none new. No pool, quota or GPU changes.
- **External data:** none.

## Open Questions

- [ ] Should the pool stop deallocating on task completion (or hold a floor of
      one node) so the race disappears rather than being absorbed? That is an
      infrastructure decision, deliberately out of scope here — it would need an
      ADR and a quota discussion.
- [ ] Should node loss *during* a task (rather than after it) be surfaced
      distinctly? Batch requeues such tasks itself today; no evidence yet that it
      needs handling.
