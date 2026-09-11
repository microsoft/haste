// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { v4 as uuid } from "uuid";
import { buildUrl } from "../../util/api";
import { canEditResults, predictionRenderKey } from "./predictionResults.js";
import { requestPredictionJson, predictionErrorMessage } from "./predictionHttp.js";
import { indexById } from "./predictionClassify.js";
import { publishPredictionEdit } from "./predictionEditWorkflow.js";
import {
  canAdjustThresholds, classifyDraft, initialDraft, isDraftDirty,
  modelClassAt, nextReviewIndex, reviewLocation, reviewRows, saveAttempt, setOverrides,
} from "./predictionEditing.js";

export default function usePredictionEditor({ ids, results, artifacts, renderer, layersReady, loadVersion, focusBuilding }) {
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
  const bind = (candidate, keepControls = false) => {
    if (!canEditResults(candidate.results)) {
      const cause = new Error(candidate.results.editReadiness?.detail || "These predictions cannot be edited.");
      cause.code = candidate.results.editReadiness?.reason;
      throw cause;
    }
    const draft = initialDraft(candidate.attrs, candidate.results);
    const previous = stateRef.current;
    const controls = keepControls && previous?.routeKey === routeKey &&
      previous.source.predictionRevision === candidate.results.predictionRevision
      ? { activeClass: previous.activeClass, reviewClass: previous.reviewClass, selectedIndex: previous.selectedIndex }
      : { activeClass: "Damaged", reviewClass: "all", selectedIndex: -1 };
    setState({
      routeKey, key: predictionRenderKey(candidate.results),
      source: candidate.results, attrs: candidate.attrs, baseline: draft, draft,
      ...controls,
    });
  };

  const enter = () => {
    if (!layersReady || !artifacts.attrs || isEditMode || confirmed?.pending ||
        pending.current || !canEditResults(results)) return;
    setFailure(null);
    try { bind({ results, attrs: artifacts.attrs }); }
    catch (cause) {
      setFailure({ routeKey, code: cause.code, message: predictionErrorMessage(cause) });
    }
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
        try { bind(candidate); }
        catch (cause) {
          if (live(op)) setState(null);
          throw cause;
        }
      }
    } catch (cause) { failed(op, cause); }
    finally { finish(op); }
  };

  const adoptSaved = (candidate, result, op) => {
    if (!live(op)) return;
    setSaved({ routeKey, result, pending: false });
    lastAttempt.current = null;
    try { if (isEditMode) bind(candidate, true); }
    catch (cause) {
      if (live(op)) setState(null);
      failed({ ...op, kind: "display" }, cause);
    }
  };
  const loadSaved = async (result, op) => {
    const candidate = await loadVersion(result.version, result.predictionRevision);
    adoptSaved(candidate, result, op);
  };
  const save = async () => {
    if (disabled || !isDraftDirty(state.draft, state.baseline) ||
        error?.code === "source_changed" || error?.code === "request_conflict") return;
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
      else adoptSaved(outcome.candidate, outcome.result, op);
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
      ...previous, selectedIndex: -1,
      draft: { ...previous.draft, overrides: setOverrides(previous.draft.overrides, allowed, previous.activeClass) },
    };
  });
  const reset = (id) => change((previous) => {
    const index = rowIndex.get(id);
    if (index === undefined) return previous;
    return {
      ...previous, selectedIndex: -1,
      draft: { ...previous.draft, overrides: setOverrides(previous.draft.overrides, [id], modelClassAt(previous.attrs, index)) },
    };
  });
  const { attrs: editorAttrs, source: editorSource, draft: editorDraft, baseline: editorBaseline } = current ? state : {};
  const classification = useMemo(() => editorAttrs
    ? classifyDraft(editorAttrs, editorSource, editorDraft, editorBaseline) : null,
  [editorAttrs, editorSource, editorDraft, editorBaseline]);
  const draftDirty = useMemo(() => !!editorDraft && isDraftDirty(editorDraft, editorBaseline), [editorDraft, editorBaseline]);
  const reviewClass = current ? state.reviewClass : "all";
  const rows = useMemo(() => editorAttrs ? reviewRows(editorAttrs, classification, reviewClass) : [],
    [editorAttrs, classification, reviewClass]);
  const selectedId = current ? editorAttrs.ids[state.selectedIndex] : undefined;
  const presentation = useMemo(() => classification ? {
    classes: classification.classes, editedIds: classification.editedIds, selectedId,
  } : null, [classification, selectedId]);
  const navigate = async (direction) => {
    if (disabled || ["source_changed", "request_conflict"].includes(error?.code)) return;
    const next = nextReviewIndex(rows, state.selectedIndex, direction);
    if (next === null) return;
    const id = state.attrs.ids[next];
    const op = begin("review");
    if (!op) return;
    try {
      let location = renderer.getKnownLocation(id);
      if (!location) {
        const query = new URLSearchParams({
          projectId: ids.projectId, imageLayerId: ids.imageLayerId,
          buildingId: state.attrs.overtureIds[next],
        });
        location = reviewLocation(await requestPredictionJson(
          buildUrl(`GetBuildingFootprintsGeoJSON?${query}`), { signal: op.controller.signal },
        ), id, state.attrs.overtureIds[next]);
        if (!live(op)) return;
        renderer.rememberLocation(id, location);
      }
      if (!live(op)) return;
      change((previous) => ({ ...previous, selectedIndex: next }));
      focusBuilding(location);
    } catch (cause) { failed(op, cause); }
    finally { finish(op); }
  };
  const setThreshold = (value) => {
    if (!current || !canAdjustThresholds(state.source) || !Number.isFinite(value) || value < 0 || value > 1) return;
    change((previous) => ({ ...previous, draft: { ...previous.draft, threshold: value } }));
  };
  const interactionError = useCallback((cause) => {
    setFailure({ routeKey, message: cause.message });
  }, [routeKey]);
  return {
    isEditMode, busy, disabled, enter, exit, selectVersion, save, retrySaved,
    error: error?.message, errorCode: error?.code, confirmed,
    dirty: current && !confirmed?.pending && draftDirty,
    state: current ? state : null, classification, presentation, rows, selectedId,
    paint, reset, navigate, setThreshold, interactionError,
    setActiveClass: (activeClass) => change((previous) => ({ ...previous, activeClass, selectedIndex: -1 })),
    setReviewClass: (reviewClass) => change((previous) => ({ ...previous, reviewClass, selectedIndex: -1 })),
    assignHighlighted: (cls) => {
      if (selectedId !== undefined) change((previous) => ({
        ...previous, activeClass: cls,
        draft: { ...previous.draft, overrides: setOverrides(previous.draft.overrides, [selectedId], cls) },
      }));
    },
    discard: () => change((previous) => ({ ...previous, draft: previous.baseline })),
  };
}
