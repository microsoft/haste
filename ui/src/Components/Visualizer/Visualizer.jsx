// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Common read-only results, adapted from PR136. Both workflows draw the same
// per-building vectors over two Azure Maps panes. Results GETs never start work.
import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import PropTypes from "prop-types";
import { Button, MessageBar, MessageBarActions, MessageBarBody, makeStyles, tokens } from "@fluentui/react-components";
import { useParams } from "react-router-dom";
import { AppContext } from "../../AppContext";
import { useTheme } from "../../util/ThemeContext.jsx";
import { convertDateToString } from "../../util/conversion";
import { shouldIgnoreShortcut } from "../keyboardShortcuts";
import Labels from "./Labels";
import PredictionStatusNote from "./PredictionStatusNote";
import useVisualizerResults from "./useVisualizerResults";
import useVisualizerMaps, { validBounds } from "./useVisualizerMaps";
import usePredictionArtifacts from "./usePredictionArtifacts";
import usePredictionFootprints from "./usePredictionFootprints";
import {
  FOOTPRINTS_LOADING, FOOTPRINTS_UNAVAILABLE, readinessDetail,
  resolveFootprintStatus, visualizerLayerOptions,
} from "./predictionResults.js";
import { dividerPositionForKey, isMobileResultsLayout } from "./visualizerSwipe.js";
import PredictionEditPanel from "./PredictionEditPanel";
import PredictionVersionControls from "./PredictionVersionControls";
import PredictionDiscardDialog from "./PredictionDiscardDialog";
import usePredictionEditor from "./usePredictionEditor";
import usePredictionEditorMap from "./usePredictionEditorMap";
import usePredictionNavigationGuard from "./usePredictionNavigationGuard";
import { buildVersionGpkgUrl, versionLabel } from "./predictionVersions.js";
import { downloadPrediction } from "./predictionDownload.js";
import { buildUrl } from "../../util/api";
import "../../assets/css/visualizer.css";

const useStyles = makeStyles({
  topStack: {
    position: "absolute", top: "10px", left: "50%", transform: "translateX(-50%)",
    zIndex: 950, boxSizing: "border-box", width: "min(560px, calc(100% - 32px))",
    pointerEvents: "none", display: "flex", flexDirection: "column",
    gap: tokens.spacingVerticalS,
    "@media (max-width: 1100px)": { top: "66px" },
  },
  editingStack: {
    left: "10px", top: "66px", transform: "none", width: "calc(100% - 390px)",
    "@media (max-width: 700px)": { left: "16px", width: "calc(100% - 32px)" },
  },
  notice: { pointerEvents: "auto", minWidth: 0, maxWidth: "100%" },
  noticeBody: { minWidth: 0, overflowWrap: "anywhere" },
  noticeActions: {
    minWidth: 0, maxWidth: "100%", flexWrap: "wrap",
    "& button": { maxWidth: "100%", whiteSpace: "normal" },
  },
  selectBox: {
    position: "absolute", display: "none", zIndex: 900, pointerEvents: "none",
    border: `${tokens.strokeWidthThick} dashed ${tokens.colorBrandStroke1}`,
    backgroundColor: tokens.colorBrandBackground2, opacity: 0.4,
  },
});

export default function Visualizer({ setModalComponent }) {
  const { projectId, imageLayerId, modelId } = useParams();
  const ids = useMemo(() => ({ projectId, imageLayerId, modelId }), [projectId, imageLayerId, modelId]);
  const routeKey = JSON.stringify(ids);
  const styles = useStyles();
  const { updateAppParams } = useContext(AppContext);
  const { isDark, palette } = useTheme();
  const containerRef = useRef(null);
  const primaryContainerRef = useRef(null);
  const secondaryContainerRef = useRef(null);
  const selectionBoxRef = useRef(null);
  const positionedScene = useRef(null);
  const confirmationRef = useRef(null);
  const downloadAbortRef = useRef(null);
  const [confirmation, setConfirmation] = useState(null);
  const [downloadState, setDownloadState] = useState(null);
  const downloadBusy = downloadState?.routeKey === routeKey && downloadState.loading;
  useEffect(() => () => { downloadAbortRef.current?.abort(); }, [routeKey]);
  const callbacksRef = useRef({ updateAppParams, setModalComponent });
  const [swipeStateMobile, setSwipeStateMobile] = useState("post");
  const [visibility, setVisibility] = useState({
    predictedDamageLayer: false, predictionsLayer: false, footprints: true,
  });
  const { results, preloaded, error: resultsError, retry, loadVersion, switchState } = useVisualizerResults(ids);
  const scene = useVisualizerMaps({ results, routeKey, primaryContainerRef, secondaryContainerRef });
  const artifacts = usePredictionArtifacts(results, preloaded);
  const footprints = usePredictionFootprints({
    maps: scene.maps, registerCleanup: scene.registerCleanup, artifacts, visible: visibility.footprints,
    themeHostRef: containerRef, isDark, palette,
  });
  const editor = usePredictionEditor({
    ids, results, artifacts, renderer: footprints.renderer, layersReady: footprints.layersReady, loadVersion,
  });
  usePredictionEditorMap({
    renderer: footprints.renderer, enabled: editor.isEditMode && !!editor.state,
    interactive: !editor.disabled && !confirmation,
    presentation: editor.presentation, paint: editor.paint, reset: editor.reset,
    boxRef: selectionBoxRef, onError: editor.interactionError,
  });
  const askDiscard = useCallback(() => {
    if (!editor.busy && !editor.dirty) return Promise.resolve(true);
    if (confirmationRef.current) return Promise.resolve(false);
    return new Promise((resolve) => {
      confirmationRef.current = resolve;
      setConfirmation({ blocked: editor.busy });
    });
  }, [editor.busy, editor.dirty]);
  const answerDiscard = (answer) => {
    confirmationRef.current?.(answer);
    confirmationRef.current = null;
    setConfirmation(null);
  };
  usePredictionNavigationGuard(editor.busy || editor.dirty, askDiscard, editor.exit);
  useEffect(() => () => { confirmationRef.current?.(false); }, []);
  const toggleEdit = async () => {
    if (editor.busy || confirmation) return;
    if (!editor.isEditMode) await editor.enter();
    else if (await askDiscard()) editor.exit();
  };
  const selectVersion = async (version) => {
    if (editor.busy || confirmation) return;
    if (await askDiscard()) await editor.selectVersion(version);
  };
  const onDownload = async (version, predictionRevision) => {
    if (downloadBusy) return;
    const controller = new AbortController();
    downloadAbortRef.current = controller;
    setDownloadState({ routeKey, loading: true });
    try {
      await downloadPrediction(buildUrl(buildVersionGpkgUrl({ ...ids, version, predictionRevision })), version, { signal: controller.signal });
      if (!controller.signal.aborted) setDownloadState(null);
    } catch (cause) {
      if (!controller.signal.aborted) setDownloadState({ routeKey, error: cause.message });
    }
  };
  const error = resultsError || scene.error || artifacts.error || footprints.error;
  const status = error ? FOOTPRINTS_UNAVAILABLE : resolveFootprintStatus({
    results, loaded: !!artifacts.attrs, layersReady: footprints.layersReady,
  });
  const layerOptions = visualizerLayerOptions({ results, footprintStatus: status });

  // AppContext's update function is not memoized. Read its latest value from
  // an effect rather than repeatedly updating the title on context renders.
  useEffect(() => {
    callbacksRef.current = { updateAppParams, setModalComponent };
  }, [updateAppParams, setModalComponent]);
  useEffect(() => {
    const title = results?.projectName
      ? `${results.projectName}${results.eventDate ? `: ${convertDateToString(results.eventDate)}` : ""}`
      : "";
    callbacksRef.current.updateAppParams({ visualizerTitle: title });
    return () => {
      callbacksRef.current.updateAppParams({ visualizerTitle: "" });
      callbacksRef.current.setModalComponent(null);
    };
  }, [results]);

  const resetMapPosition = useCallback(() => {
    const bounds = [
      results?.studyArea?.[0]?.bbox, artifacts.bounds,
      results?.postDisasterImagery?.bounds, results?.preDisasterImagery?.bounds,
    ].find(validBounds);
    if (bounds && scene.maps) {
      // SwipeMap synchronizes cameras. Do not add a second camera sync loop.
      scene.maps[0].setCamera({ bounds, padding: 80, duration: 0 });
    }
  }, [results, artifacts.bounds, scene.maps]);
  useEffect(() => {
    const hasBounds = [results?.studyArea?.[0]?.bbox, artifacts.bounds,
      results?.postDisasterImagery?.bounds, results?.preDisasterImagery?.bounds].some(validBounds);
    if (scene.maps && hasBounds && positionedScene.current !== scene.key) {
      resetMapPosition();
      positionedScene.current = scene.key;
    }
  }, [scene.maps, scene.key, results, artifacts.bounds, resetMapPosition]);

  useEffect(() => {
    if (!scene.maps) return;
    for (const map of scene.maps) {
      for (const id of ["predictedDamageLayer", "predictionsLayer"]) {
        map.layers.getLayerById(id)?.setOptions({ visible: !editor.isEditMode && visibility[id] });
      }
    }
  }, [scene.maps, visibility, editor.isEditMode, results?.predictedDamageLayer, results?.predictionsLayer]);
  useEffect(() => {
    footprints.renderer?.setVisible(editor.isEditMode || visibility.footprints);
  }, [footprints.renderer, editor.isEditMode, visibility.footprints]);

  useEffect(() => {
    if (!scene.swipe || !scene.maps) return;
    const container = containerRef.current;
    const resize = () => {
      const mobile = isMobileResultsLayout(window.innerWidth);
      const width = container.getBoundingClientRect().width;
      scene.swipe.setOptions({
        sliderPosition: mobile ? (swipeStateMobile === "post" ? 0 : width) : width / 2,
      });
      const divider = container.querySelector(".azure-maps-swipe-map");
      if (divider) divider.classList.toggle("d-none", mobile);
      const controls = scene.maps[0].controls;
      const hasZoom = scene.zoom && controls.getControls().includes(scene.zoom);
      if (mobile && hasZoom) controls.remove(scene.zoom);
      else if (!mobile && scene.zoom && !hasZoom) {
        controls.add(scene.zoom, { position: "bottom-left" });
      }
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(container);
    window.addEventListener("resize", resize);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", resize);
    };
  }, [scene, swipeStateMobile]);

  useEffect(() => {
    const onKeyDown = (event) => {
      if (confirmation || shouldIgnoreShortcut(event) || event.ctrlKey || event.altKey || event.metaKey) return;
      if (event.target?.closest?.('[role="dialog"], [role="alertdialog"], [role="combobox"], [role="listbox"], [role="menu"]')) return;
      if (event.key.toLowerCase() === "e") {
        if (!event.repeat) toggleEdit();
        return;
      }
      if (editor.isEditMode && !editor.disabled) {
        const cls = { 1: "Damaged", 2: "NotDamaged", 3: "Unknown" }[event.key];
        if (cls) {
          editor.setActiveClass(cls);
          containerRef.current.focus({ preventScroll: true });
          return;
        }
        if (event.key === "Enter") { event.preventDefault(); editor.applySelected(); return; }
        if (["ArrowLeft", "ArrowRight"].includes(event.key)) {
          event.preventDefault();
          editor.navigate(event.key === "ArrowLeft" ? -1 : 1);
          containerRef.current.focus({ preventScroll: true });
          return;
        }
      }
      if (!scene.swipe) return;
      const position = dividerPositionForKey(event.key, containerRef.current.getBoundingClientRect().width);
      if (position !== null) {
        scene.swipe.setOptions({ sliderPosition: position });
        if (isMobileResultsLayout(window.innerWidth) && event.key.toLowerCase() !== "s") {
          setSwipeStateMobile(event.key.toLowerCase() === "a" ? "post" : "pre");
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  const changeVisibility = (key, visible) => setVisibility((previous) => ({ ...previous, [key]: visible }));
  const historical = results?.currentPredictionRevision && results.currentPredictionRevision !== results.predictionRevision;
  const canEdit = footprints.layersReady && !historical && !editor.confirmed?.pending;
  const loadingVersion = editor.busy || (status === FOOTPRINTS_LOADING && !!results);
  const retryResults = () => {
    if (editor.busy) return;
    if (scene.error || footprints.error) scene.retryScene();
    if (results) selectVersion(results.predictionVersion ?? 0); else retry();
  };
  return (
    <div className="visualizer-container" ref={containerRef} tabIndex={-1} aria-label="Prediction results">
      <div id="primaryMap" ref={primaryContainerRef} className="map" aria-label="Pre-event results map" />
      <div id="secondaryMap" ref={secondaryContainerRef} className="map" aria-label="Post-event results map" />
      <div ref={selectionBoxRef} className={styles.selectBox} />
      <Labels
        visualizerResults={results || {}}
        resetMapPosition={resetMapPosition}
        setSwipeStateMobile={setSwipeStateMobile}
        swipeStateMobile={swipeStateMobile}
        layerOptions={layerOptions}
        layerVisibility={visibility}
        onLayerVisibilityChange={changeVisibility}
        isEditMode={editor.isEditMode}
        canEdit={canEdit}
        editTooltip={historical ? "Historical generations are read-only. Select current raw predictions to edit." : canEdit ? "Edit these predictions and save a new version (E)" : "Load a valid prediction source before editing."}
        onToggleEditMode={toggleEdit}
        busy={editor.busy}
      />
      <div className={`${styles.topStack} ${editor.isEditMode ? styles.editingStack : ""}`}>
        {results && <PredictionVersionControls
          versions={results.predictionVersions || []} source={results}
          onSelectVersion={selectVersion} onDownload={onDownload}
          disabled={editor.busy || loadingVersion || !!downloadBusy || !!confirmation}
          loading={loadingVersion}
          editing={editor.isEditMode}
        />}
        {scene.basemapWarning && <MessageBar intent="info" layout="multiline" className={styles.notice}>
          <MessageBarBody className={styles.noticeBody}>{scene.basemapWarning}</MessageBarBody>
        </MessageBar>}
        {switchState?.error && <MessageBar intent="error" className={styles.notice}><MessageBarBody>
          {versionLabel(switchState.version)} could not be loaded ({switchState.phase}).
          The map still shows {versionLabel(results?.predictionVersion ?? 0)}{editor.isEditMode ? " with the local edit preview" : ""}. {switchState.error}
        </MessageBarBody></MessageBar>}
        {!editor.isEditMode && editor.error && <MessageBar intent="error" layout="multiline" className={styles.notice}>
          <MessageBarBody className={styles.noticeBody}>{editor.error}</MessageBarBody>
          <MessageBarActions className={styles.noticeActions}>
            <Button onClick={editor.enter} disabled={!canEdit || editor.busy}>Retry editing</Button>
            {editor.errorCode === "source_changed" && <Button onClick={() => selectVersion(0)}>Reload current predictions</Button>}
          </MessageBarActions>
        </MessageBar>}
        {historical && <MessageBar intent="info" className={styles.notice}><MessageBarBody>
          Historical generation: viewing, downloads and reports remain available. Editing requires the current model predictions.
        </MessageBarBody></MessageBar>}
        {editor.confirmed && <MessageBar intent={editor.confirmed.error ? "warning" : "success"} layout="multiline" className={styles.notice}>
          <MessageBarBody className={styles.noticeBody}>
            {editor.confirmed.error || `Version ${editor.confirmed.result.version} saved. ${editor.confirmed.pending || loadingVersion ? "Loading the saved version…" : `${editor.confirmed.result.editedCount ?? 0} buildings changed from model.`}`}
          </MessageBarBody>
          <MessageBarActions className={styles.noticeActions}>
            {editor.confirmed.pending && !editor.busy && <Button onClick={editor.retrySaved}>Retry displaying saved version</Button>}
            <Button disabled={!!downloadBusy} onClick={() => onDownload(editor.confirmed.result.version, editor.confirmed.result.predictionRevision)}>Download saved version</Button>
          </MessageBarActions>
        </MessageBar>}
        {downloadState?.routeKey === routeKey && downloadState.error && <MessageBar intent="error" className={styles.notice}><MessageBarBody>{downloadState.error}</MessageBarBody></MessageBar>}
        {downloadBusy && <MessageBar intent="info" layout="multiline" className={styles.notice}>
          <MessageBarBody className={styles.noticeBody}>Downloading predictions…</MessageBarBody>
          <MessageBarActions className={styles.noticeActions}>
            <Button onClick={() => { downloadAbortRef.current?.abort(); setDownloadState(null); }}>Cancel download</Button>
          </MessageBarActions>
        </MessageBar>}
        <PredictionStatusNote
          status={status}
          detail={error || (status === FOOTPRINTS_LOADING ? "" : readinessDetail(results))}
          onRetry={editor.busy ? undefined : retryResults}
        />
      </div>
      {editor.isEditMode && <PredictionEditPanel editor={editor} versions={results?.predictionVersions || []}
        onExit={toggleEdit} onDownload={onDownload} downloadBusy={!!downloadBusy}
        swipeStateMobile={swipeStateMobile} setSwipeStateMobile={setSwipeStateMobile} onReloadCurrent={() => selectVersion(0)} />}
      {confirmation && <PredictionDiscardDialog blocked={confirmation.blocked} onAnswer={answerDiscard} />}
    </div>
  );
}
Visualizer.propTypes = { setModalComponent: PropTypes.func.isRequired };
