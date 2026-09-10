// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Common read-only results, adapted from PR136. Both workflows draw the same
// per-building vectors over two Azure Maps panes. Results GETs never start work.
import { useCallback, useContext, useEffect, useRef, useState } from "react";
import PropTypes from "prop-types";
import { makeStyles, tokens } from "@fluentui/react-components";
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
import "../../assets/css/visualizer.css";

const useStyles = makeStyles({
  topStack: {
    position: "absolute", top: "10px", left: "50%", transform: "translateX(-50%)",
    zIndex: 950, boxSizing: "border-box", width: "min(560px, calc(100% - 32px))",
    pointerEvents: "none", display: "flex", flexDirection: "column",
    gap: tokens.spacingVerticalS,
    "@media (max-width: 1100px)": { top: "66px" },
  },
});

export default function Visualizer({ setModalComponent }) {
  const ids = useParams();
  const styles = useStyles();
  const { updateAppParams } = useContext(AppContext);
  const { isDark, palette } = useTheme();
  const containerRef = useRef(null);
  const primaryContainerRef = useRef(null);
  const secondaryContainerRef = useRef(null);
  const callbacksRef = useRef({ updateAppParams, setModalComponent });
  const [swipeStateMobile, setSwipeStateMobile] = useState("post");
  const [visibility, setVisibility] = useState({
    predictedDamageLayer: false, predictionsLayer: false, footprints: true,
  });
  const { results, error: resultsError, retry } = useVisualizerResults(ids);
  const scene = useVisualizerMaps({ results, primaryContainerRef, secondaryContainerRef });
  const artifacts = usePredictionArtifacts(results);
  const footprints = usePredictionFootprints({
    maps: scene.maps, registerCleanup: scene.registerCleanup, artifacts, visible: visibility.footprints,
    themeHostRef: containerRef, isDark, palette,
  });
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
  useEffect(() => { resetMapPosition(); }, [resetMapPosition]);

  useEffect(() => {
    if (!scene.maps) return;
    for (const map of scene.maps) {
      for (const id of ["predictedDamageLayer", "predictionsLayer"]) {
        map.layers.getLayerById(id)?.setOptions({ visible: visibility[id] });
      }
    }
  }, [scene.maps, visibility]);

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
      if (shouldIgnoreShortcut(event) || event.ctrlKey || event.altKey || event.metaKey || !scene.swipe) return;
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
  }, [scene.swipe]);

  const changeVisibility = (key, visible) => setVisibility((previous) => ({ ...previous, [key]: visible }));
  return (
    <div className="visualizer-container" ref={containerRef}>
      <div id="primaryMap" ref={primaryContainerRef} className="map" aria-label="Pre-event results map" />
      <div id="secondaryMap" ref={secondaryContainerRef} className="map" aria-label="Post-event results map" />
      <Labels
        visualizerResults={results || {}}
        resetMapPosition={resetMapPosition}
        setSwipeStateMobile={setSwipeStateMobile}
        swipeStateMobile={swipeStateMobile}
        layerOptions={layerOptions}
        layerVisibility={visibility}
        onLayerVisibilityChange={changeVisibility}
      />
      <div className={styles.topStack}>
        <PredictionStatusNote
          status={status}
          detail={error || (status === FOOTPRINTS_LOADING ? "" : readinessDetail(results))}
          onRetry={retry}
        />
      </div>
    </div>
  );
}
Visualizer.propTypes = { setModalComponent: PropTypes.func.isRequired };
