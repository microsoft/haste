// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { v4 as uuid } from "uuid";
import { buildUrl } from "../../util/api";
import { predictionRenderKey } from "./predictionResults.js";
import { requestPredictionJson, predictionErrorMessage } from "./predictionHttp.js";
import { versionEndpoint } from "./predictionVersions.js";
import { indexById } from "./predictionClassify.js";
import { publishPredictionEdit } from "./predictionEditWorkflow.js";
import {
  canAdjustThresholds, classifyDraft, countManualChanges, filteredRows, initialDraft, isDraftDirty,
  modelClassAt, nextReviewIndex, saveAttempt, setOverrides, validateEditSession,
  undoManualChanges,
} from "./predictionEditing.js";

export default function usePredictionEditor({ ids, results, artifacts, renderer, layersReady, loadVersion }) {
  const routeKey = JSON.stringify(ids);
  const [state, setState] = useState(null);
  const [operation, setOperation] = useState(null);
  const [failure, setFailure] = useState(null);
  const [saved, setSaved] = useState(null);
  const sequence = useRef(0);
  const pending = useRef(null);
  const lastAttempt = useRef(null);
  const stateRef = useRef(null);
  useEffect(() => { stateRef.current = state; }, [state]);
  useEffect(() => () => {
    ++sequence.current;
    pending.current?.controller.abort();
    pending.current = null;
    lastAttempt.current = null;
  }, [routeKey]);
  const isEditMode = state?.routeKey === routeKey;
  const current = isEditMode && state.key === artifacts.key && !!artifacts.attrs;
  const busy = operation?.routeKey === routeKey;
  const confirmed = saved?.routeKey === routeKey ? saved : null;
  const error = failure?.routeKey === routeKey ? failure : null;
  const disabled = busy || !current || !layersReady || confirmed?.pending === true;
  const begin = (kind) => {
    if (pending.current) return null;
    const op = { run: ++sequence.current, controller: new AbortController(), kind };
    pending.current = op;
    setOperation({ routeKey, kind });
    setFailure(null);
    return op;
  };
  const live = (op) => op.run === sequence.current && !op.controller.signal.aborted;
  const finish = (op) => {
    if (!live(op)) return;
    pending.current = null;
    setOperation(null);
  };
  const failed = (op, cause) => {
    if (live(op)) setFailure({
      routeKey, code: cause.code,
      message: op.kind === "save" && cause.status == null && typeof cause.code !== "string"
        ? `The save could not be confirmed. Your draft is kept; retrying unchanged content reuses the same request ID. ${cause.message || ""}`
        : predictionErrorMessage(cause),
    });
  };
  const bind = async (candidate, op) => {
    const session = validateEditSession(await requestPredictionJson(
      buildUrl(versionEndpoint("GetPredictionEditSession", ids, candidate.results.predictionVersion ?? 0)),
      { signal: op.controller.signal },
    ), candidate.results, candidate.attrs);
    if (!live(op)) return;
    const draft = initialDraft(candidate.attrs, session);
    setState({
      routeKey, key: predictionRenderKey(candidate.results), session,
      source: candidate.results, attrs: candidate.attrs, baseline: draft, draft,
      activeClass: "Damaged", selectedIndex: -1, filter: "all",
    });
  };

  const enter = async () => {
    if (!layersReady || !artifacts.attrs || isEditMode || confirmed?.pending) return;
    if (results.currentPredictionRevision && results.currentPredictionRevision !== results.predictionRevision) return;
    const op = begin("session");
    if (!op) return;
    try { await bind({ results, attrs: artifacts.attrs }, op); }
    catch (cause) { failed(op, cause); }
    finally { finish(op); }
  };
  const exit = () => {
    if (pending.current) return;
    setState(null);
    setFailure(null);
    lastAttempt.current = null;
  };
  const selectVersion = async (version) => {
    const op = begin("version");
    if (!op) return;
    try {
      const candidate = await loadVersion(version);
      if (!live(op)) return;
      lastAttempt.current = null;
      setSaved(null);
      if (isEditMode) {
        try { await bind(candidate, op); }
        catch (cause) {
          if (live(op)) setState(null);
          throw cause;
        }
      }
    } catch (cause) { failed(op, cause); }
    finally { finish(op); }
  };

  const adoptSaved = async (candidate, result, op) => {
    if (!live(op)) return;
    // Once artifacts are adopted, a session failure disables editing but does
    // not misreport a successful save/display as a failed persistence operation.
    setSaved({ routeKey, result, pending: false });
    lastAttempt.current = null;
    try { if (isEditMode) await bind(candidate, op); }
    catch (cause) {
      if (live(op)) setState(null);
      failed(op, cause);
    }
  };
  const loadSaved = async (result, op) => {
    const candidate = await loadVersion(result.version, result.predictionRevision);
    await adoptSaved(candidate, result, op);
  };
  const save = async () => {
    if (disabled || error?.code === "source_changed" || error?.code === "request_conflict") return;
    const op = begin("save");
    if (!op) return;
    try {
      const attempt = saveAttempt(lastAttempt.current, ids, state.source, state.draft, uuid);
      lastAttempt.current = attempt;
      const outcome = await publishPredictionEdit(attempt.body, {
        write: (body) => requestPredictionJson(buildUrl("PutEditedPredictions"), { body, signal: op.controller.signal }),
        loadVersion,
        buildingCount: state.attrs.n,
        isCurrent: () => live(op),
        onSaved: (result) => {
          setSaved({ routeKey, result, pending: true });
          setOperation({ routeKey, kind: "display" });
        },
      });
      if (outcome.displayError) setSaved({ routeKey, result: outcome.result, pending: true, error: outcome.displayError });
      else await adoptSaved(outcome.candidate, outcome.result, op);
    } catch (cause) { failed(op, cause); }
    finally { finish(op); }
  };
  const retrySaved = async () => {
    if (!confirmed?.pending) return;
    const op = begin("display");
    if (!op) return;
    try { await loadSaved(confirmed.result, op); }
    catch (cause) {
      if (live(op)) setSaved({ ...confirmed, error: `Version ${confirmed.result.version} was saved but could not be displayed. ${cause.message}` });
    } finally { finish(op); }
  };

  const change = (update) => {
    if (disabled) return;
    const previous = stateRef.current || state;
    const next = update(previous);
    if (error?.code !== "source_changed" &&
        (error?.code !== "request_conflict" || isDraftDirty(next.draft, previous.draft))) setFailure(null);
    if (confirmed && !confirmed.pending) setSaved(null);
    stateRef.current = next;
    setState(next);
  };
  const currentAttrs = state?.attrs;
  const rowIndex = useMemo(() => currentAttrs ? indexById(currentAttrs) : new Map(), [currentAttrs]);
  const paint = (rowIds) => change((previous) => {
    const allowed = rowIds.filter((id) => rowIndex.has(id));
    return {
      ...previous, selectedIndex: allowed.length ? rowIndex.get(allowed[0]) : previous.selectedIndex,
      draft: { ...previous.draft, overrides: setOverrides(previous.draft.overrides, allowed, previous.activeClass) },
    };
  });
  const reset = (id) => change((previous) => {
    const index = rowIndex.get(id);
    if (index === undefined) return previous;
    return {
      ...previous, selectedIndex: index,
      draft: { ...previous.draft, overrides: setOverrides(previous.draft.overrides, [id], modelClassAt(previous.attrs, index)) },
    };
  });
  const { attrs: editorAttrs, source: editorSource, draft: editorDraft, baseline: editorBaseline,
    filter: editorFilter, selectedIndex: reviewIndex } = current ? state : {};
  const classification = useMemo(() => editorAttrs
    ? classifyDraft(editorAttrs, editorSource, editorDraft, editorBaseline) : null,
  [editorAttrs, editorSource, editorDraft, editorBaseline]);
  const rows = useMemo(() => editorAttrs ? filteredRows(editorAttrs, classification, editorFilter) : [],
    [editorAttrs, classification, editorFilter]);
  const selectedId = editorAttrs?.ids[reviewIndex];
  const draftDirty = useMemo(() => !!editorDraft && isDraftDirty(editorDraft, editorBaseline), [editorDraft, editorBaseline]);
  const manualChangeCount = useMemo(() => editorDraft ? countManualChanges(editorDraft, editorBaseline) : 0, [editorDraft, editorBaseline]);
  const dimmedIds = useMemo(() => {
    const included = new Set(rows);
    return new Set(editorAttrs?.ids.filter((_id, i) => !included.has(i)) || []);
  }, [editorAttrs, rows]);
  const presentation = useMemo(() => classification ? {
    classes: classification.classes, editedIds: classification.editedIds, selectedId, dimmedIds,
  } : null, [classification, selectedId, dimmedIds]);
  const navigate = (direction) => {
    if (disabled) return;
    const next = nextReviewIndex(rows, state.selectedIndex, direction, (i) => !!renderer?.getKnownLocation(state.attrs.ids[i]));
    if (next === null) return;
    change((previous) => ({ ...previous, selectedIndex: next }));
    const location = renderer?.getKnownLocation(state.attrs.ids[next]);
    const map = renderer?.getPanes()[0]?.map;
    if (location && map) map.setCamera({ center: location, zoom: Math.max(map.getCamera().zoom, 17.5), duration: 350 });
  };
  const setThreshold = (field, value) => {
    if (!current || !canAdjustThresholds(state.source) || !Number.isFinite(value) || value < 0 || value > 1) return;
    change((previous) => ({ ...previous, draft: { ...previous.draft, [field]: value } }));
  };
  const interactionError = useCallback((cause) => {
    setFailure({ routeKey, message: cause.message });
  }, [routeKey]);
  return {
    isEditMode, busy, disabled, enter, exit, selectVersion, save, retrySaved,
    error: error?.message, errorCode: error?.code, confirmed,
    dirty: current && !confirmed?.pending && draftDirty,
    manualChangeCount,
    state: current ? state : null, classification, rows, selectedId, presentation,
    paint, reset, navigate, setThreshold, interactionError,
    setActiveClass: (activeClass) => change((previous) => ({ ...previous, activeClass })),
    setFilter: (filter) => change((previous) => ({ ...previous, filter, selectedIndex: -1 })),
    applySelected: () => { if (selectedId !== undefined) paint([selectedId]); },
    resetSelected: () => { if (selectedId !== undefined) reset(selectedId); },
    discard: () => change((previous) => ({ ...previous, draft: previous.baseline })),
    undoManual: () => change((previous) => ({ ...previous, draft: undoManualChanges(previous.draft, previous.baseline) })),
  };
}
