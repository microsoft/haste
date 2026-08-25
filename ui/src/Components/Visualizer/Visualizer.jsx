// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// The results page: one model's predictions over the imagery it was run on.
//
// Two Azure Maps instances are handed to atlas.SwipeMap — the PRIMARY carries
// the pre-event imagery and is revealed LEFT of the divider, the SECONDARY
// carries the post-event imagery and is clipped so it is revealed RIGHT of it.
// Moving the divider left therefore uncovers more of the post-event map.
// SwipeMap syncs both cameras internally on every "move", so this file
// deliberately adds no camera-sync handler of its own.
//
// What gets drawn on top of the imagery depends on the workflow that produced
// the model, and both workflows end up in the same place:
//
//   • the inference workflow ships pre-coloured rasters (`_visualizer.tif`
//     and the raw `_predictions.tif`), while
//   • the embedding workflow ships no raster at all.
//
// So the layer that makes this page work for either is the vector one:
// per-building predicted footprints, streamed from the layer's PMTiles
// archive and coloured in the browser from the per-building score sidecar
// (usePredictionArtifacts + usePredictionFootprints). The raster checkboxes
// only appear for the models that actually have those rasters.
//
// The pencil next to Back turns this same view into an editor — same maps,
// same footprints, now clickable — instead of sending the analyst to a
// separate screen. See handleToggleEditMode.
//
// VERSIONS. A model's predictions are append-only: the raw model output plus
// every version an analyst saved. GetVisualizerResults serves ONE of them at
// a time, so the version selector (PredictionVersionControls) is a refetch —
// switching means a new payload with a version-pinned sidecar, which the
// artifact hook reloads and the footprint hook rebuilds on BOTH swipe panes.
// See handleSelectVersion.

// Dependencies
import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { apiGet, buildUrl } from "../../util/api";
import { useParams } from "react-router-dom";
import Labels from "./Labels";
import { AppContext } from "../../AppContext";
import PropType from "prop-types";
import { makeStyles, tokens } from "@fluentui/react-components";
import { convertDateToString } from "../../util/conversion";
import { fileDownload } from "../../util/file";
import VisualizerImageryControls from "./VisualizerImageryControls"
import "../../assets/css/visualizer.css";
import { getAzureMapsAuthOptions } from "../../util/azureMapsAuth";
import { shouldIgnoreShortcut } from "../keyboardShortcuts";
import { useTheme } from "../../util/ThemeContext.jsx";
import PredictionEditPanel from "./PredictionEditPanel";
import PredictionStatusNote from "./PredictionStatusNote";
import PredictionVersionControls from "./PredictionVersionControls";
import usePredictionArtifacts from "./usePredictionArtifacts";
import usePredictionFootprints from "./usePredictionFootprints";
import {
  CLASS_DAMAGED,
  CLASS_NOT_DAMAGED,
  CLASS_UNKNOWN,
  hasSavedClasses,
} from "./predictionClassify";
import {
  FOOTPRINTS_READY,
  canEditFootprints,
  describeEditAvailability,
  describeUnsavedEdits,
  hasRasterLayer,
  resolveModelFlavor,
  resolveSupportsThreshold,
  visualizerLayerOptions,
} from "./predictionResults";
import {
  MAX_VERSION_POLL_ATTEMPTS,
  RAW_VERSION,
  VERSION_POLL_INTERVAL_MS,
  buildVersionGpkgUrl,
  buildVisualizerResultsUrl,
  describeReportDivergence,
  describeSavedClassNote,
  describeVersionSidecarPending,
  describeVersionSwitchDiscard,
  describeVersionSwitchFailure,
  normalizeVersionSelection,
  shouldPollVersionSidecar,
  versionLabel,
  versionSelectorOptions,
} from "./predictionVersions";
import {
  dividerPositionForKey,
  resolveSwipeMode,
  swipeModeHint,
} from "./visualizerSwipe";

// 1 / 2 / 3 set the selected building's class in edit mode, matching
// PREDICTION_EDIT_SHORTCUTS.
const CLASS_BY_KEY = {
  1: CLASS_DAMAGED,
  2: CLASS_NOT_DAMAGED,
  3: CLASS_UNKNOWN,
};

const useStyles = makeStyles({
  // Back and the edit affordance sit side by side; stacked, the second button
  // would run into the pre-event imagery block just below them.
  navigationControls: {
    flexDirection: "row",
  },
  // The results page's top-centre overlay column: the version selector above
  // the layer's status note.
  //
  // They share one stack rather than each pinning itself to the map, because
  // both are variable height (a divergence warning, a failed switch, a
  // progress bar) and two independently positioned overlays at fixed offsets
  // would sooner or later cover each other. It starts below the navigation
  // controls' row so a narrow desktop cannot overlap them either.
  //
  // The column itself is transparent to the pointer; only the cards inside it
  // take clicks, so the map still pans through the gaps.
  topStack: {
    position: "absolute",
    top: "66px",
    left: "50%",
    transform: "translateX(-50%)",
    zIndex: 950,
    boxSizing: "border-box",
    width: "min(560px, calc(100% - 32px))",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: tokens.spacingVerticalS,
    pointerEvents: "none",
  },
  // Ctrl+drag box-select rectangle. Absolutely positioned inside the
  // visualizer container, which shares its top-left corner with both map
  // canvases, so the drag offsets need no translation.
  selectBox: {
    position: "absolute",
    display: "none",
    zIndex: 900,
    pointerEvents: "none",
    border: `${tokens.strokeWidthThick} dashed ${tokens.colorBrandStroke1}`,
    backgroundColor: tokens.colorBrandBackground2,
    opacity: 0.4,
  },
  editHint: {
    position: "absolute",
    bottom: "6px",
    left: "50%",
    transform: "translateX(-50%)",
    zIndex: 900,
    padding: `${tokens.spacingVerticalXXS} ${tokens.spacingHorizontalM}`,
    borderRadius: tokens.borderRadiusMedium,
    color: tokens.colorNeutralForeground2,
    backgroundColor: tokens.colorNeutralBackground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    boxShadow: tokens.shadow4,
    fontSize: tokens.fontSizeBase100,
    whiteSpace: "nowrap",
    pointerEvents: "none",
    "@media (max-width: 900px)": {
      display: "none",
    },
  },
});

const Visualizer = ({ setModalComponent }) => {
  // Constants
  const { projectId, imageLayerId, modelId } = useParams();
  const styles = useStyles();
  const [globalVisualizerResults, setGlobalVisualizerResults] = useState({});
  const { setIsLoading, updateAppParams, appParams, setDialog } =
    useContext(AppContext);
  const { isDark, palette } = useTheme();
  // The container elements and the Map objects that end up inside them are
  // kept apart: the footprint layer needs the maps, the box-select needs the
  // DOM, and SwipeMap leaves state on both.
  const containerRef = useRef(null);
  const primaryContainerRef = useRef(null);
  const secondaryContainerRef = useRef(null);
  const selectionBoxRef = useRef(null);
  const primaryMapRef = useRef(null);
  const secondaryMapRef = useRef(null);
  const swipeMapRef = useRef(null);
  const zoomControlRef = useRef(null);
  // Both maps build their layers inside an async "ready" handler that fires
  // after the constructor returns, so readiness is counted there and mirrored
  // into state — the refs alone would never re-run the dependent effects.
  const readyCountRef = useRef(0);
  const [mapsReady, setMapsReady] = useState(false);
  const [swipeStateMobile, setSwipeStateMobile] = useState("post");
  const [isEditMode, setIsEditMode] = useState(false);
  // Which prediction version is on the map is NOT held in state: it is
  // whatever the payload currently on screen says it was served from
  // (`servedVersion` below). One source of truth means the selector can never
  // claim a version the map is not actually drawing — including while a
  // switch is in flight, or after one failed.
  const [isSwitchingVersion, setIsSwitchingVersion] = useState(false);
  // A switch that failed. Kept as its own state so the previous version stays
  // on the map with an explanation instead of the page half-applying a
  // version it could not load.
  const [versionSwitchFailure, setVersionSwitchFailure] = useState(null);
  // How many times we have re-asked for a version whose sidecar is still
  // being backfilled. Reset by every deliberate switch.
  const [versionPollAttempt, setVersionPollAttempt] = useState(0);
  // Only the newest version request may write results: an analyst clicking
  // through three versions must not be left on whichever response happens to
  // arrive last.
  const versionRunRef = useRef(0);
  // The run id of the switch the spinner belongs to. A background poll shares
  // the counter above (its response must lose to a newer request too), so
  // without this a poll landing mid-switch would leave the selector spinning
  // for a switch that had already finished.
  const switchRunRef = useRef(0);
  // The status the analyst last dismissed a note for. Stored rather than a
  // plain boolean so a NEW status (preparing -> failed, say) shows up again
  // without an effect that resets state behind their back.
  const [dismissedNoteStatus, setDismissedNoteStatus] = useState("");
  // Layer checkboxes are controlled from here so edit mode can hide the
  // pre-coloured damage raster (it fights with the vector classes underneath)
  // and put it back on the way out, with the checkboxes telling the truth
  // throughout.
  const [layerVisibility, setLayerVisibility] = useState({
    predictedDamageLayer: true,
    predictionsLayer: false,
    footprints: true,
  });
  const rasterVisibilityBeforeEditRef = useRef(null);

  const [imageryValues, setImageryValues] = useState({
    opacity: 1,
    contrast: 0,
    hueRotation: 0,
    saturation: 0,
  });

  const resultsReady = !!globalVisualizerResults.projectName;

  // ── Predicted building footprints ────────────────────────────────────────
  // The artifacts (PMTiles + score sidecar) and the map layers they feed are
  // owned by two hooks so this component stays about the page rather than the
  // renderer. Both are safe to call before anything has loaded.
  const artifacts = usePredictionArtifacts({
    projectId,
    imageLayerId,
    modelId,
    results: globalVisualizerResults,
    resultsReady,
  });

  const mapRefs = useMemo(() => [primaryMapRef, secondaryMapRef], []);

  const footprints = usePredictionFootprints({
    projectId,
    imageLayerId,
    modelId,
    mapRefs,
    mapsReady,
    archiveKey: artifacts.archiveKey,
    attrs: artifacts.attrs,
    indexByIdRef: artifacts.indexByIdRef,
    isEditMode,
    themeHostRef: containerRef,
    selectionBoxRef,
    isDark,
    palette,
    defaultThreshold: artifacts.session?.defaultThreshold,
    onSaved: artifacts.refreshVersions,
    // Identity of the prediction data being drawn. A version switch changes
    // it, which is what makes the hook rebuild the source, the layers and the
    // feature-state on BOTH swipe panes rather than repaint stale ones.
    renderKey: artifacts.renderKey,
  });

  const footprintStatus = artifacts.status;
  const canEdit = canEditFootprints(footprintStatus) && footprints.layersReady;
  const layerOptions = useMemo(
    () =>
      visualizerLayerOptions({
        results: globalVisualizerResults,
        footprintStatus,
      }),
    [globalVisualizerResults, footprintStatus]
  );
  const swipeMode = useMemo(
    () => resolveSwipeMode(globalVisualizerResults),
    [globalVisualizerResults]
  );

  // ── Version selection ────────────────────────────────────────────────────
  // Everything about which version is on the map, and about the divergence
  // between the map and the reports, is decided in predictionVersions.js.
  const servedVersion = artifacts.activeVersion ?? RAW_VERSION;
  const versionOptions = useMemo(
    () =>
      versionSelectorOptions({
        versions: artifacts.versions,
        servedVersion,
      }),
    [artifacts.versions, servedVersion]
  );
  // Version selection moves the MAP only — the reports always read the newest
  // saved version — so this is disclosed wherever the analyst can act on it.
  // `predictionVersionIsLatest` is the server's answer; it knows about
  // versions this page may not have listed.
  const reportDivergence = useMemo(
    () =>
      describeReportDivergence({
        isLatest: artifacts.versionIsLatest,
        servedVersion,
        versions: artifacts.versions,
      }),
    [artifacts.versionIsLatest, servedVersion, artifacts.versions]
  );

  // Visualizer data fetching function. `version` is left out for the very
  // first load so the API applies its own default (the newest saved state);
  // every switch pins one explicitly, 0 being the raw model output.
  const fetchVisualizerResults = useCallback(
    (version) =>
      apiGet(
        buildVisualizerResultsUrl({
          projectId,
          imageLayerId,
          modelId,
          version,
        })
      ),
    [projectId, imageLayerId, modelId]
  );

  async function getVisualizerResults() {
    setIsLoading(true);
    return await fetchVisualizerResults()
      .then((response) => {
        setIsLoading(false);
        return response;
      })
      .catch((error) => {
        setIsLoading(false);
        console.error("Error fetching visualizer results:", error);
        throw error;
      });
  }

  /**
   * Point the map at another saved version.
   *
   * The whole switch is one refetch: the new payload carries a version-pinned
   * sidecar URL, which reloads the scores (the footprint geometry is shared
   * by every version) and rebuilds both swipe panes. A failure changes
   * nothing — the previous version stays on screen with the reason — because
   * results are only replaced once the new payload is in hand.
   */
  const loadVersion = useCallback(
    async (version, { poll = false } = {}) => {
      const runId = versionRunRef.current + 1;
      versionRunRef.current = runId;
      if (!poll) {
        switchRunRef.current = runId;
        setIsSwitchingVersion(true);
        setVersionSwitchFailure(null);
        setIsLoading(true, `Loading ${versionLabel(version).toLowerCase()}`);
      }
      try {
        const results = await fetchVisualizerResults(version);
        if (runId !== versionRunRef.current) return;
        setGlobalVisualizerResults(results);
        if (!poll) setVersionPollAttempt(0);
      } catch (error) {
        if (runId !== versionRunRef.current) return;
        console.error("Could not load the selected prediction version:", error);
        if (!poll) {
          setVersionSwitchFailure(
            describeVersionSwitchFailure({
              version,
              shownVersion: servedVersion,
              message: "The version could not be read from the server.",
            })
          );
        }
      } finally {
        // Released by the switch that owns it, even when a background poll
        // has since taken over the run counter — an unreleased spinner would
        // lock the selector on a page that is otherwise perfectly usable.
        if (!poll && switchRunRef.current === runId) {
          setIsSwitchingVersion(false);
          setIsLoading(false);
        }
      }
    },
    [fetchVisualizerResults, servedVersion, setIsLoading]
  );

  const handleSelectVersion = useCallback(
    (version) => {
      const next = normalizeVersionSelection(version);
      if (next === servedVersion && !versionSwitchFailure) return;
      // Nothing is written until "Save as new version", and the switch
      // reloads the predictions from the server, so pending edits would go
      // with them. Same confirmation as leaving edit mode.
      if (isEditMode && footprints.isDirty) {
        setDialog(
          "Discard unsaved edits?",
          `${describeUnsavedEdits(
            footprints.overrides,
            footprints.baseline
          )} ${describeVersionSwitchDiscard(next)}`,
          [
            {
              type: "primary",
              key: "discard",
              text: "Discard and switch",
              onClick: () => {
                setDialog();
                footprints.discardEdits();
                loadVersion(next);
              },
            },
            {
              type: "default",
              key: "keep",
              text: "Keep editing",
              onClick: () => setDialog(),
            },
          ]
        );
        return;
      }
      loadVersion(next);
    },
    [
      servedVersion,
      versionSwitchFailure,
      isEditMode,
      footprints,
      loadVersion,
      setDialog,
    ]
  );

  // A version saved before its sidecar existed has nothing to draw. The
  // artifact hook has already asked for the backfill; re-ask the API for the
  // same version on a bounded schedule so the map fills in on its own instead
  // of making the analyst reload. One timer at a time, cleared on every
  // change.
  useEffect(() => {
    if (
      !shouldPollVersionSidecar({
        pending: artifacts.versionPending,
        attempt: versionPollAttempt,
        maxAttempts: MAX_VERSION_POLL_ATTEMPTS,
      })
    ) {
      return undefined;
    }
    const timer = window.setTimeout(() => {
      setVersionPollAttempt((attempt) => attempt + 1);
      loadVersion(servedVersion, { poll: true });
    }, VERSION_POLL_INTERVAL_MS);
    return () => window.clearTimeout(timer);
  }, [
    artifacts.versionPending,
    versionPollAttempt,
    servedVersion,
    loadVersion,
  ]);

  // Switching versions re-fetches everything, including the lazily loaded
  // edit session that carries the model's flavour and threshold support. An
  // analyst who was already editing should not have to leave and re-enter
  // edit mode to get those back, so it is re-fetched once per version — and
  // only while editing, so a read-only view still never pays for it.
  const sessionRenderKeyRef = useRef("");
  useEffect(() => {
    if (!isEditMode || !artifacts.renderKey) return;
    if (sessionRenderKeyRef.current === artifacts.renderKey) return;
    sessionRenderKeyRef.current = artifacts.renderKey;
    artifacts.ensureSession().catch((error) => {
      // Editing still works without it: the thresholds start from their
      // defaults and the history comes from the results payload.
      console.warn("Could not reload the prediction edit session:", error);
    });
  }, [isEditMode, artifacts]);

  // The GeoPackage for one version, through GetModelArtifact — auth, managed
  // identity and Range are handled there, which is why this page never
  // rewrites blob SAS URLs the way the model rows do.
  const handleDownloadVersion = useCallback(
    (version) => {
      fileDownload(
        buildUrl(
          buildVersionGpkgUrl({
            projectId,
            imageLayerId,
            modelId,
            version,
          })
        ),
        setDialog
      );
    },
    [projectId, imageLayerId, modelId, setDialog]
  );

  // The width the swipe divider is measured against. The container is the
  // element both map canvases fill, so it beats window.innerWidth whenever the
  // page is not full-bleed.
  const swipeAreaWidth = useCallback(
    () => containerRef.current?.getBoundingClientRect().width || window.innerWidth,
    []
  );

  useEffect(() => {
    if (swipeMapRef.current) {
      if (swipeStateMobile === "post") {
        swipeMapRef.current.setOptions({
          sliderPosition: 0,
        });
      } else {
        swipeMapRef.current.setOptions({
          sliderPosition: swipeAreaWidth(),
        });
      }
    }
  }, [swipeStateMobile, swipeAreaWidth]);

  function checkResponsiveness() {
    const bootstrapBreakpoint = appParams.bootstrapBreakpoint;
    if (bootstrapBreakpoint < 4) {
      if (swipeMapRef.current) {
        swipeMapRef.current.setOptions({
          sliderPosition: swipeStateMobile === "post" ? 0 : swipeAreaWidth(),
        });
      }

      if (primaryMapRef.current && primaryMapRef.current.controls && zoomControlRef.current) {
        primaryMapRef.current.controls.remove(zoomControlRef.current);
      }

      const swipeMapElement = document.querySelector('.azure-maps-swipe-map');
      if (swipeMapElement) {
        swipeMapElement.classList.add('d-none');
      }
    } else {
      if (swipeMapRef.current) {
        swipeMapRef.current.setOptions({
          sliderPosition: swipeAreaWidth() / 2
        });
      }

      if (primaryMapRef.current && primaryMapRef.current.controls && zoomControlRef.current) {
        const controls = primaryMapRef.current.controls.getControls();
        const hasZoomControl = controls.includes(zoomControlRef.current);
        if (!hasZoomControl) {
          primaryMapRef.current.controls.add(zoomControlRef.current, {
            position: "bottom-left",
          });
        }
      }

      const swipeMapElement = document.querySelector('.azure-maps-swipe-map');
      if (swipeMapElement) {
        swipeMapElement.classList.remove('d-none');
      }
    }
  }

  useEffect(() => {
    checkResponsiveness();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appParams.bootstrapBreakpoint]);

  useEffect(() => {
    let cancelled = false;

    const initializeMaps = async () => {
      if (window.atlas) {
        // Create zoom control reference, so it can be referenced when deleting
        // and resetting regarding responsiveness
        zoomControlRef.current = new window.atlas.control.ZoomControl();

        const visualizerResults = await getVisualizerResults();
        if (cancelled) return;

        updateAppParams({
          visualizerTitle: convertToVisualizerTitle(visualizerResults),
        });

        const authOptions = getAzureMapsAuthOptions();

        // PRE EVENT MAP SETUP
        const primaryMap = new window.atlas.Map(primaryContainerRef.current, {
          style: "satellite",
          authOptions: authOptions,
        });

        // POST EVENT MAP SETUP
        const secondaryMap = new window.atlas.Map(secondaryContainerRef.current, {
          style: "satellite",
          authOptions: authOptions,
        });

        // SwipeMap object to enable swipe functionality. Primary is revealed
        // left of the divider, secondary is clipped and revealed right of it.
        swipeMapRef.current = new window.atlas.SwipeMap(
          primaryMap,
          secondaryMap
        );

        // Both panes have to be up before the footprint layer can be added to
        // them; whichever "ready" lands second flips the flag.
        const markReady = () => {
          readyCountRef.current += 1;
          if (readyCountRef.current >= 2 && !cancelled) setMapsReady(true);
        };

        // Primary map event listeners
        primaryMap.events.add("ready", async function () {
          // Avoid map rotation
          avoidRotation(primaryMap);

          await loadPreOrPostDisasterLayer(
            primaryMap,
            visualizerResults.preDisasterImagery,
            "preDisasterImagery"
          );

          loadPredictedDamageLayer(primaryMap, visualizerResults.predictedDamageLayer);

          loadPredictionsLayer(primaryMap, visualizerResults.predictionsLayer);

          await loadStudyArea(primaryMap, visualizerResults.studyArea);

          markReady();
        });

        // Secondary map event listeners
        secondaryMap.events.add("ready", function () {
          // Avoid map rotation
          avoidRotation(secondaryMap);

          loadPreOrPostDisasterLayer(
            secondaryMap,
            visualizerResults.postDisasterImagery,
            "postDisasterImagery"
          );

          loadPredictedDamageLayer(secondaryMap, visualizerResults.predictedDamageLayer);

          loadPredictionsLayer(secondaryMap, visualizerResults.predictionsLayer);

          loadStudyArea(secondaryMap, visualizerResults.studyArea);

          markReady();
        });

        // Assign maps to refs
        primaryMapRef.current = primaryMap;
        secondaryMapRef.current = secondaryMap;

        // Set global visualizer results to be used in child components
        setGlobalVisualizerResults(visualizerResults);
        checkResponsiveness();
      }
    };

    // Call the async function inside the effect
    initializeMaps();

    // On component dismount
    return () => {
      cancelled = true;
      setModalComponent(null);
      updateAppParams({ visualizerTitle: "" });
      teardownMaps();
    };

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Dispose both maps and the swipe control. Ordering matters: SwipeMap
  // appended its divider to the primary's container and attached handlers to
  // both maps, so it goes first — and it does NOT clear the inline `clip` it
  // left on the secondary, which has to be wiped by hand or the element is
  // handed back to the DOM permanently cropped.
  function teardownMaps() {
    if (swipeMapRef.current) {
      try {
        if (typeof swipeMapRef.current.dispose === "function") {
          swipeMapRef.current.dispose();
        }
      } catch (error) {
        console.warn("atlas.SwipeMap dispose failed:", error);
      }
      swipeMapRef.current = null;
    }

    const panes = [
      [primaryMapRef, primaryContainerRef],
      [secondaryMapRef, secondaryContainerRef],
    ];
    for (const [mapRef, containerElementRef] of panes) {
      const map = mapRef.current;
      if (map) {
        try {
          if (typeof map.getMapContainer === "function") {
            map.getMapContainer().style.clip = "";
          }
        } catch (error) {
          console.warn("clearing the map clip failed:", error);
        }
        try {
          map.dispose();
        } catch (error) {
          console.warn("map dispose failed:", error);
        }
      }
      if (containerElementRef.current) {
        containerElementRef.current.style.clip = "";
      }
      mapRef.current = null;
    }
    readyCountRef.current = 0;
    zoomControlRef.current = null;
  }

  // ── Edit mode ────────────────────────────────────────────────────────────
  const enterEditMode = useCallback(async () => {
    // The session carries the model's flavour, whether its score can be
    // re-thresholded, and the saved version history. It is fetched lazily —
    // the API reads the GeoPackage to answer — so a plain results view never
    // pays for it.
    setIsLoading(true, "Preparing prediction editing");
    try {
      await artifacts.ensureSession();
      // Claim the session for the version on screen so the effect that
      // re-fetches it after a version switch does not immediately ask again.
      sessionRenderKeyRef.current = artifacts.renderKey;
    } catch (error) {
      // Editing still works without it: the thresholds simply start from
      // their defaults and the version list stays empty until the first save.
      console.warn("Could not load the prediction edit session:", error);
    } finally {
      setIsLoading(false);
    }
    rasterVisibilityBeforeEditRef.current = {
      predictedDamageLayer: layerVisibility.predictedDamageLayer,
      predictionsLayer: layerVisibility.predictionsLayer,
    };
    setLayerVisibility((previous) => ({
      ...previous,
      predictedDamageLayer: false,
      predictionsLayer: false,
      footprints: true,
    }));
    setIsEditMode(true);
  }, [artifacts, layerVisibility, setIsLoading]);

  const leaveEditMode = useCallback(() => {
    footprints.discardEdits();
    setIsEditMode(false);
    const restore = rasterVisibilityBeforeEditRef.current;
    rasterVisibilityBeforeEditRef.current = null;
    if (restore) {
      setLayerVisibility((previous) => ({ ...previous, ...restore }));
    }
  }, [footprints]);

  const handleToggleEditMode = useCallback(() => {
    if (!isEditMode) {
      if (!canEdit) return;
      enterEditMode();
      return;
    }
    if (!footprints.isDirty) {
      leaveEditMode();
      return;
    }
    // Nothing is written until "Save as new version", so leaving with edits
    // pending throws them away — say so before it happens.
    setDialog(
      "Discard unsaved edits?",
      describeUnsavedEdits(footprints.overrides, footprints.baseline),
      [
        {
          type: "primary",
          key: "discard",
          text: "Discard edits",
          onClick: () => {
            setDialog();
            leaveEditMode();
          },
        },
        {
          type: "default",
          key: "keep",
          text: "Keep editing",
          onClick: () => setDialog(),
        },
      ]
    );
  }, [
    isEditMode,
    canEdit,
    enterEditMode,
    leaveEditMode,
    footprints.isDirty,
    footprints.overrides,
    footprints.baseline,
    setDialog,
  ]);

  const handleSave = useCallback(async () => {
    try {
      const result = await footprints.save();
      setDialog(
        "Edits saved",
        `Version ${result.version} saved with ${result.editedCount ?? 0} edited building${
          result.editedCount === 1 ? "" : "s"
        }.`
      );
    } catch (error) {
      setDialog(
        "Save failed",
        error?.message || "Failed to save the edited predictions."
      );
    }
  }, [footprints, setDialog]);

  // ── Keyboard ─────────────────────────────────────────────────────────────
  // Bound in its own effect so the handler always sees the current mode and
  // selection; a listener registered once on mount would close over the first
  // render's values. Focus guarding is the shared shouldIgnoreShortcut.
  useEffect(() => {
    const onKeyDown = (event) => {
      if (shouldIgnoreShortcut(event)) return;
      if (event.ctrlKey || event.altKey || event.metaKey) return;

      if (isEditMode) {
        const cls = CLASS_BY_KEY[event.key];
        if (cls) {
          footprints.setClickAction(cls);
          footprints.setClassForSelected(cls);
          return;
        }
        if (event.key === "ArrowLeft") {
          event.preventDefault();
          footprints.navigateInFilter(-1);
          return;
        }
        if (event.key === "ArrowRight") {
          event.preventDefault();
          footprints.navigateInFilter(1);
          return;
        }
      }

      if (event.key.toLowerCase() === "e") {
        handleToggleEditMode();
        return;
      }

      // A / S / D snap the divider. The position is in pixels from the left
      // edge of the map area: A = hard left (the post-event map fills the
      // view), S = centre, D = hard right (the pre-event map fills it).
      if (!swipeMapRef.current) return;
      const position = dividerPositionForKey(event.key, swipeAreaWidth());
      if (position === null) return;
      try {
        swipeMapRef.current.setOptions({ sliderPosition: position });
      } catch (error) {
        console.warn("swipe setOptions(sliderPosition) failed:", error);
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isEditMode, footprints, handleToggleEditMode, swipeAreaWidth]);

  // Avoid map rotation and set camera bearing to 0
  function avoidRotation(map) {
    map.setUserInteraction({
      dragRotateInteraction: false,
      scrollZoomInteraction: true,
      pinchZoomInteraction: true,
      pinchRotateInteraction: false,
    });

    map.setCamera({
      bearing: 0,
    });
  }

  // Load study area on map
  async function loadStudyArea(map, studyArea) {
    // A layer with no label project has no study area: the maps still work,
    // there is simply no outline to draw and nothing to fly to.
    if (!Array.isArray(studyArea) || studyArea.length === 0) return;

    // Create Data Source
    const dataSource = new window.atlas.source.DataSource();
    map.sources.add(dataSource);

    // Add data
    const geoJsonData = {
      type: "FeatureCollection",
      features: studyArea,
    };
    dataSource.add(geoJsonData);

    // Create linelayer to define workspace
    const lineLayer = new window.atlas.layer.LineLayer(dataSource, null, {
      strokeColor: "#FFFFFF",
      strokeWidth: 2,
    });
    map.layers.add(lineLayer);

    resetMapPosition(studyArea, 3000);
  }

  // Reset map position to study area
  function resetMapPosition(studyArea, duration = 700) {
    if (!primaryMapRef.current) return;
    if (!Array.isArray(studyArea) || !studyArea[0]?.bbox) return;
    // atlas.SwipeMap keeps both cameras in sync, so moving the primary moves
    // the secondary with it.
    primaryMapRef.current.setCamera({
      bounds: studyArea[0].bbox,
      type: "fly",
      duration: duration,
      padding: 100,
    });
  }

  // Adds a layer with pre or post disaster imagery. Without a usable tile URL
  // (no pre-event imagery, or an embedding model whose imagery was never
  // processed into a COG) the Azure Maps basemap stands in, so the pane is
  // never blank.
  async function loadPreOrPostDisasterLayer(map, disasterLayer, customId) {
    if (hasRasterLayer(disasterLayer)) {
      const layer = new window.atlas.layer.TileLayer({
        tileUrl: disasterLayer.url,
        minZoom: 1,
        maxZoom: 22,
        bounds: disasterLayer.bounds,
        attribution: disasterLayer.attribution,
      });
      layer.customId = customId;

      map.layers.add(layer);
    } else {
      const tempTileUrlPath = `https://atlas.microsoft.com/map/tile?api-version=2.1&tilesetId=microsoft.imagery&zoom={z}&x={x}&y={y}`;

      const imagery = new window.atlas.layer.TileLayer({
        tileUrl: tempTileUrlPath,
        tileSize: 512,
      });

      try {
        imagery.customId = customId;
        map.layers.add(imagery);
      } catch (error) {
        console.error("Error loading imagery layer:", error);
      }
    }
  }

  // Adds the pre-coloured predicted damage raster. Embedding models have no
  // such raster — their predictions are the vector footprints — so nothing is
  // added and the InfoPanel offers no checkbox for it.
  function loadPredictedDamageLayer(map, predictedDamageLayer) {
    if (!hasRasterLayer(predictedDamageLayer)) return;

    const layer = new window.atlas.layer.TileLayer({
      tileUrl: predictedDamageLayer.url,
      minZoom: 1,
      maxZoom: 22,
      bounds: predictedDamageLayer.bounds,
      attribution: predictedDamageLayer.attribution,
    });

    layer.customId = "predictedDamageLayer";
    map.layers.add(layer);
  }

  // Adds the raw per-pixel prediction raster, hidden until it is checked in
  // the InfoPanel.
  function loadPredictionsLayer(map, predictionsLayer) {
    if (!hasRasterLayer(predictionsLayer)) return;

    const layer = new window.atlas.layer.TileLayer({
      tileUrl: predictionsLayer.url,
      minZoom: 1,
      maxZoom: 22,
      bounds: predictionsLayer.bounds,
      attribution: predictionsLayer.attribution,
      visible: false,
    });

    layer.customId = "predictionsLayer";
    map.layers.add(layer);
  }

  // Get layer by customId
  function getLayerById(currentMap, customId) {
    if (!currentMap.current || !currentMap.current.layers) return null;
    const layers = currentMap.current.layers.getLayers();
    return layers.find((layer) => layer.customId === customId);
  }

  // Toggles one raster layer on both maps. The vector footprints are not here:
  // they belong to usePredictionFootprints, which owns both panes' copies.
  const applyRasterVisibility = useCallback((customId, isVisible) => {
    for (const mapRef of [primaryMapRef, secondaryMapRef]) {
      const layer = getLayerById(mapRef, customId);
      if (layer) layer.setOptions({ visible: isVisible });
    }
  }, []);

  useEffect(() => {
    if (!mapsReady) return;
    applyRasterVisibility(
      "predictedDamageLayer",
      layerVisibility.predictedDamageLayer
    );
    applyRasterVisibility("predictionsLayer", layerVisibility.predictionsLayer);
  }, [mapsReady, layerVisibility, applyRasterVisibility]);

  const setFootprintsVisible = footprints.setIsVisible;
  useEffect(() => {
    setFootprintsVisible(layerVisibility.footprints);
  }, [layerVisibility.footprints, setFootprintsVisible]);

  const handleLayerVisibilityChange = useCallback((key, isVisible) => {
    setLayerVisibility((previous) => ({ ...previous, [key]: isVisible }));
  }, []);

  // Convert date to string for visualizer title
  function convertToVisualizerTitle(response) {
    if (response.eventDate && response.eventDate !== "") {
      return response.projectName + ": " + convertDateToString(response.eventDate);
    } else {
      return response.projectName;
    }
  }

  const updateImageryProperties = (key, value) => {
    try {
      const preImageryRef = getLayerById(primaryMapRef, "preDisasterImagery");
      const postImageryRef = getLayerById(secondaryMapRef, "postDisasterImagery");

      preImageryRef.setOptions({
        [key]: value,
      });

      postImageryRef.setOptions({
        [key]: value,
      });

      setImageryValues({
        ...imageryValues,
        [key]: value,
      });
    } catch (error) {
      console.error("Error updating imagery values:", error);
    }
  };

  const resetImageryProperties = () => {
    try {
      const preImageryRef = getLayerById(primaryMapRef, "preDisasterImagery");
      const postImageryRef = getLayerById(secondaryMapRef, "postDisasterImagery");

      preImageryRef.setOptions({
        opacity: 1,
        contrast: 0,
        hueRotation: 0,
        saturation: 0,
      });

      postImageryRef.setOptions({
        opacity: 1,
        contrast: 0,
        hueRotation: 0,
        saturation: 0,
      });

      setImageryValues({
        opacity: 1,
        contrast: 0,
        hueRotation: 0,
        saturation: 0,
      });
    } catch (error) {
      console.error("Error resetting imagery values:", error);
    }
  };

  const classification = footprints.classification;
  const showStatusNote =
    resultsReady &&
    footprintStatus !== FOOTPRINTS_READY &&
    dismissedNoteStatus !== footprintStatus;
  // A version saved before its sidecar existed has nothing to draw, which is
  // a fact about the VERSION rather than about the layer — so it is said on
  // the version card, next to the selector that can get the analyst out of
  // it, and the layer's own status note is left to describe the layer.
  const versionPendingNote = artifacts.versionPending
    ? describeVersionSidecarPending({
        version: servedVersion,
        versionsPending: artifacts.versionsPending,
      })
    : null;
  // The version history is only worth a control once something has been
  // saved: with no edited versions there is nothing to choose between, and
  // the raw output is already what the page shows.
  const showVersionControls = resultsReady && versionOptions.length > 1;
  // A version's own classes were decided by an analyst, so the thresholds
  // cannot move them; offering sliders that do nothing would be a lie.
  const versionHasSavedClasses = hasSavedClasses(artifacts.attrs);
  const supportsThreshold =
    resolveSupportsThreshold({
      results: globalVisualizerResults,
      session: artifacts.session,
    }) && !versionHasSavedClasses;

  return (
    <div className="visualizer-container" ref={containerRef}>
      <div id="primaryMap" ref={primaryContainerRef} className="map"></div>
      <div id="secondaryMap" ref={secondaryContainerRef} className="map"></div>
      {/* Ctrl+drag selection rectangle, shared by both panes. */}
      <div ref={selectionBoxRef} className={styles.selectBox} />

      <Labels
        resetMapPosition={resetMapPosition}
        visualizerResults={globalVisualizerResults}
        setSwipeStateMobile={setSwipeStateMobile}
        swipeStateMobile={swipeStateMobile}
        layerOptions={layerOptions}
        layerVisibility={layerVisibility}
        onLayerVisibilityChange={handleLayerVisibilityChange}
        isEditMode={isEditMode}
        canEdit={canEdit}
        editTooltip={describeEditAvailability(footprintStatus)}
        onToggleEditMode={handleToggleEditMode}
        navigationControlsClassName={styles.navigationControls}
      />

      <VisualizerImageryControls
        updateImageryProperties={updateImageryProperties}
        resetImageryProperties={resetImageryProperties}
        imageryValues={imageryValues}
        visualizerResults={globalVisualizerResults}
      />

      {(showVersionControls || showStatusNote) && (
        <div className={styles.topStack}>
          {showVersionControls && (
            <PredictionVersionControls
              options={versionOptions}
              selectedVersion={servedVersion}
              onSelectVersion={handleSelectVersion}
              onDownload={handleDownloadVersion}
              isSwitching={isSwitchingVersion}
              pending={versionPendingNote}
              divergence={reportDivergence}
              failure={versionSwitchFailure}
              onDismissFailure={() => setVersionSwitchFailure(null)}
            />
          )}

          {showStatusNote && (
            <PredictionStatusNote
              status={footprintStatus}
              prepState={artifacts.prepState}
              session={artifacts.session}
              error={artifacts.error}
              detail={artifacts.readinessDetail}
              onRetry={artifacts.requestPreparation}
              onDismiss={() => setDismissedNoteStatus(footprintStatus)}
            />
          )}
        </div>
      )}

      {isEditMode && classification && (
        <>
          <div className={styles.editHint}>
            Click a footprint to set its class &middot; Ctrl+drag to box-select
            &middot; right-click to undo an edit &middot; A / S / D move the
            swipe divider
          </div>
          <PredictionEditPanel
            flavor={resolveModelFlavor({
              results: globalVisualizerResults,
              session: artifacts.session,
            })}
            supportsThreshold={supportsThreshold}
            counts={classification.counts}
            total={classification.total}
            editedCount={classification.editedCount}
            filter={footprints.filter}
            setFilter={footprints.setFilter}
            filteredIndices={footprints.filteredIndices}
            selectedIndex={footprints.selectedIndex}
            currentBuilding={footprints.currentBuilding}
            clickAction={footprints.clickAction}
            setClickAction={footprints.setClickAction}
            onSetClass={(cls) => {
              footprints.setClickAction(cls);
              footprints.setClassForSelected(cls);
            }}
            onClearOverride={footprints.clearSelectedOverride}
            onClearAllEdits={footprints.clearAllOverrides}
            onPrev={() => footprints.navigateInFilter(-1)}
            onNext={() => footprints.navigateInFilter(1)}
            threshold={footprints.threshold}
            setThreshold={footprints.setThreshold}
            unknownThreshold={footprints.unknownThreshold}
            setUnknownThreshold={footprints.setUnknownThreshold}
            baseline={footprints.baseline}
            changeCount={footprints.changeCount}
            swipeHint={swipeModeHint(swipeMode)}
            onExit={handleToggleEditMode}
            onSave={handleSave}
            isSaving={footprints.isSaving}
            saveError={footprints.saveError}
            savedResult={footprints.savedResult}
            versions={artifacts.versions}
            activeVersion={artifacts.activeVersion}
            // Downloads and the report disclosure are the same in both modes;
            // the panel is simply where the version history already lives.
            onDownloadVersion={handleDownloadVersion}
            reportDivergence={reportDivergence}
            thresholdNote={
              versionHasSavedClasses
                ? describeSavedClassNote(servedVersion)
                : ""
            }
          />
        </>
      )}
    </div>
  );
};

Visualizer.propTypes = {
  setModalComponent: PropType.func.isRequired,
};

export default Visualizer;
