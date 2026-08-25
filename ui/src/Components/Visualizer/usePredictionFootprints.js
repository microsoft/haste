// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Draws one model's predicted building footprints on the results page and,
// in edit mode, makes them editable.
//
// This is the layer both HASTE workflows share: the inference workflow also
// ships pre-coloured rasters, but an embedding model has nothing else to
// show, so per-building vectors are what makes the results page work for
// either. Footprints stream from the layer's PMTiles archive (never a
// download of every polygon), the per-building scores come from the small
// JSON sidecar held in a ref, and each building's class is derived in the
// browser from those scores plus the current thresholds, with any user edit
// taking precedence — predictionClassify.js owns that logic and is
// unit-tested. Colouring is applied as feature-state on the renderer beneath
// atlas.Map, keyed by the integer feature id, which is why moving the
// threshold slider recolours instantly with no server round-trip.
//
// THE SWIPE MAP IS ALWAYS UP on the results page. atlas.SwipeMap clips the
// SECONDARY (post-event) map to reveal the PRIMARY (pre-event) one on the
// left of the divider, so a click on the uncovered left half never reaches
// the post-event map. Both panes therefore get their own copy of the source,
// their own layers, their own interaction handlers, and a mirror of every
// feature-state write and paint expression — otherwise half the map is inert
// and the far side draws every footprint in the "not classified" colour.
//
// SWITCHING VERSIONS goes through the same rule and is the easiest place to
// break it: feature-state lives on the RENDERER, one per pane, so pointing
// the page at another version's sidecar has to tear down and rebuild the
// source, the layers and the feature-state on BOTH panes. `renderKey` — the
// version-pinned sidecar URL — is in the layer effect's deps for exactly that
// reason, and the teardown clears the feature-state before removing the
// source so nothing from the previous version can survive under a re-created
// source of the same name.
//
// Saving PUTs the thresholds plus the sparse override list to
// PutEditedPredictions, which writes a brand-new version — nothing is
// destructive.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { tokens } from "@fluentui/react-components";
import { apiPut } from "../../util/api";
import {
  FILTER_ALL,
  buildSavePayload,
  classifyAll,
  clearOverride,
  countClassChanges,
  cycleClass,
  filterIndices,
  matchesFilter,
  nextIndexInList,
  setOverrideEntries,
  setOverrides,
} from "./predictionClassify.js";
import {
  FALLBACK_COLORS,
  FILL_OPACITY_EXPRESSION,
  PMTILES_SOURCE_LAYER,
  STROKE_WIDTH_EXPRESSION,
  discoverFillLayerIds,
  discoverVectorSourceId,
  featureCentroid,
  fillColorExpression,
  findGlMap,
  footprintFeatureState,
  normalizeSelectionBox,
  resolveMapColors,
  strokeColorExpression,
  themeColorLookup,
} from "./predictionFootprintMap.js";
import { hasUnsavedEdits } from "./predictionResults.js";

// Each pane needs its own source and layer ids: the two Azure Maps instances
// have separate styles and never meet, and distinct ids keep the debugger
// honest about which renderer is which.
const PANE_IDS = [
  {
    key: "primary",
    sourceId: "visualizerPrimaryBuildings",
    fillLayerId: "visualizerPrimaryFootprintFill",
    lineLayerId: "visualizerPrimaryFootprintOutline",
  },
  {
    key: "secondary",
    sourceId: "visualizerSecondaryBuildings",
    fillLayerId: "visualizerSecondaryFootprintFill",
    lineLayerId: "visualizerSecondaryFootprintOutline",
  },
];

// `tokens.x` is the string "var(--x)"; resolveMapColors unwraps it and reads
// the concrete value off a live element inside the FluentProvider subtree, so
// the map follows the light/dark theme instead of a hardcoded palette.
const MAP_COLOR_TOKENS = {
  damaged: tokens.colorStatusDangerBackground3,
  notDamaged: tokens.colorStatusSuccessBackground3,
  unknown: tokens.colorNeutralForeground3,
  pending: tokens.colorNeutralBackground5,
  outline: tokens.colorNeutralStrokeAccessible,
  edited: tokens.colorBrandStroke1,
  selected: tokens.colorNeutralForeground1,
};

const DEFAULT_THRESHOLD = 0.5;

// Shared empty object so the derived baseline keeps a stable identity and the
// effects that depend on it do not re-run every render.
const EMPTY_OVERRIDES = {};

const usePredictionFootprints = ({
  projectId,
  imageLayerId,
  modelId,
  mapRefs,
  mapsReady,
  archiveKey,
  attrs,
  indexByIdRef,
  isEditMode,
  themeHostRef,
  selectionBoxRef,
  isDark,
  palette,
  defaultThreshold,
  onSaved,
  // Identity of the prediction data on the map (the version-pinned sidecar
  // URL). A new value means a different version is being drawn, so the layers
  // and every scrap of per-building state are rebuilt from scratch.
  renderKey = "",
}) => {
  // ── Refs the long-lived map handlers read ────────────────────────────────
  // A handler registered when the layers are built closes over that render's
  // values, so everything it needs is mirrored into a ref.
  const panesRef = useRef([]);
  const classesRef = useRef([]);
  const editedRef = useRef([]);
  const filterRef = useRef(FILTER_ALL);
  const clickActionRef = useRef("cycle");
  const editModeRef = useRef(false);
  const colorsRef = useRef(FALLBACK_COLORS);
  const selectedIdRef = useRef(null);
  // id -> [lng, lat], harvested from rendered footprints. The sidecar carries
  // no geometry, so this is the only way Prev/Next knows where to pan.
  const centroidsRef = useRef(new Map());
  // pane key -> the id the renderer gave our vector source.
  const sourceIdsRef = useRef({});
  const hydrateTimerRef = useRef(null);
  // Set by Prev/Next only: clicking a footprint must not yank the camera.
  const pendingPanRef = useRef(false);
  const mountedRef = useRef(true);

  // ── State ────────────────────────────────────────────────────────────────
  // Azure Maps builds layers inside its async "ready" handler, so readiness
  // is mirrored in state: the paint and hydrate effects depend on this flag
  // because refs alone never trigger a render.
  const [layersReady, setLayersReady] = useState(false);
  const [isVisible, setIsVisible] = useState(true);
  // The thresholds are DERIVED, not synced. The model's own operating point
  // arrives late (with the edit session) and a save moves the goalposts
  // again, so holding either in state would mean copying a prop into state
  // and then racing to keep it correct. Instead: null means "whatever the
  // model says", and only a deliberate move by the analyst is stored.
  const [thresholdOverride, setThresholdOverride] = useState(null);
  const [unknownThresholdOverride, setUnknownThresholdOverride] =
    useState(null);
  // Set by save(): from then on, "unsaved" and the "would change class"
  // readout are measured against the version that was written.
  const [savedBaseline, setSavedBaseline] = useState(null);
  const [overrides, setOverridesState] = useState({});
  const [filter, setFilter] = useState(FILTER_ALL);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const [clickAction, setClickAction] = useState("cycle");
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [savedResult, setSavedResult] = useState(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // ── Ref mirrors ──────────────────────────────────────────────────────────
  useEffect(() => {
    filterRef.current = filter;
  }, [filter]);
  useEffect(() => {
    clickActionRef.current = clickAction;
  }, [clickAction]);
  useEffect(() => {
    editModeRef.current = isEditMode;
  }, [isEditMode]);

  // The model's own operating point, so the first paint matches what the rest
  // of the app already shows for this model.
  const modelThreshold = Number.isFinite(Number(defaultThreshold))
    ? Number(defaultThreshold)
    : DEFAULT_THRESHOLD;
  const threshold = thresholdOverride ?? modelThreshold;
  const unknownThreshold = unknownThresholdOverride ?? 0;

  // What unsaved work is measured against: the model's operating point until
  // something has been saved, and the saved version afterwards.
  const baseline = useMemo(
    () =>
      savedBaseline ?? {
        threshold: modelThreshold,
        unknownThreshold: 0,
        overrides: EMPTY_OVERRIDES,
      },
    [savedBaseline, modelThreshold]
  );

  // ── Renderer helpers (read refs so map handlers stay valid) ──────────────
  // Azure Maps renames our vector source inside the renderer's style, and the
  // real name only shows up on the first rendered feature. It is learned once
  // per pane and kept here rather than written back onto the pane object,
  // which the panes' handlers treat as read-only.
  const rememberSourceId = useCallback((pane, source) => {
    if (!source || sourceIdsRef.current[pane.key] === source) return;
    sourceIdsRef.current = { ...sourceIdsRef.current, [pane.key]: source };
  }, []);

  const writeFeatureState = useCallback((id, state) => {
    for (const pane of panesRef.current) {
      if (!pane.glMap) continue;
      try {
        pane.glMap.setFeatureState(
          {
            source: sourceIdsRef.current[pane.key] || pane.sourceId,
            sourceLayer: PMTILES_SOURCE_LAYER,
            id,
          },
          state
        );
      } catch (error) {
        console.warn("feature-state write failed:", error);
      }
    }
  }, []);

  const repaintFootprints = useCallback(() => {
    for (const pane of panesRef.current) {
      if (pane.map && typeof pane.map.triggerRepaint === "function") {
        pane.map.triggerRepaint();
      }
    }
  }, []);

  const queryPane = useCallback((pane, box) => {
    if (!pane?.glMap) return [];
    try {
      return (
        pane.glMap.queryRenderedFeatures(
          box,
          pane.layerIds && pane.layerIds.length
            ? { layers: pane.layerIds }
            : undefined
        ) || []
      );
    } catch (error) {
      console.warn("queryRenderedFeatures failed:", error);
      return [];
    }
  }, []);

  // Paint every footprint currently on screen from the cached classification,
  // and remember where each one is so Prev/Next can pan to it. Both panes are
  // queried: they draw the same buildings but load their tiles independently,
  // so neither is authoritative on its own.
  const hydrateViewport = useCallback(() => {
    const classes = classesRef.current;
    const edited = editedRef.current;
    const byId = indexByIdRef.current;
    const activeFilter = filterRef.current;
    const selectedId = selectedIdRef.current;
    const seen = new Set();
    let wrote = false;
    for (const pane of panesRef.current) {
      for (const feature of queryPane(pane, undefined)) {
        const id = feature.id;
        if (id == null || seen.has(id)) continue;
        seen.add(id);
        // The first rendered feature tells us what the renderer actually
        // calls our source, which is the id every feature-state write needs.
        rememberSourceId(pane, feature.source);
        const index = byId.get(id);
        if (index === undefined) continue;
        if (!centroidsRef.current.has(id)) {
          const centroid = featureCentroid(feature.geometry);
          if (centroid) centroidsRef.current.set(id, centroid);
        }
        const cls = classes[index];
        writeFeatureState(
          id,
          footprintFeatureState({
            cls,
            dim: !matchesFilter(cls, edited[index], activeFilter),
            edited: !!edited[index],
            selected: selectedId === id,
          })
        );
        wrote = true;
      }
    }
    if (wrote) repaintFootprints();
  }, [
    indexByIdRef,
    queryPane,
    rememberSourceId,
    repaintFootprints,
    writeFeatureState,
  ]);

  // Tile loads and camera moves arrive in bursts; coalesce them so a pan
  // costs one queryRenderedFeatures pass rather than a dozen.
  const scheduleHydrate = useCallback(() => {
    if (hydrateTimerRef.current) return;
    hydrateTimerRef.current = window.setTimeout(() => {
      hydrateTimerRef.current = null;
      hydrateViewport();
    }, 120);
  }, [hydrateViewport]);

  // ── Editing ──────────────────────────────────────────────────────────────
  const handleFeatureClick = useCallback(
    (id) => {
      const index = indexByIdRef.current.get(id);
      if (index === undefined) return;
      setSelectedIndex(index);
      const action = clickActionRef.current;
      const cls =
        action === "cycle" ? cycleClass(classesRef.current[index]) : action;
      setOverridesState((previous) => setOverrides(previous, [id], cls));
    },
    [indexByIdRef]
  );

  const handleClearOverrideForId = useCallback(
    (id) => {
      const index = indexByIdRef.current.get(id);
      if (index === undefined) return;
      setSelectedIndex(index);
      setOverridesState((previous) => clearOverride(previous, id));
    },
    [indexByIdRef]
  );

  const applyClickActionToIds = useCallback(
    (ids) => {
      if (ids.length === 0) return;
      const action = clickActionRef.current;
      if (action !== "cycle") {
        setOverridesState((previous) => setOverrides(previous, ids, action));
        return;
      }
      // Cycle mode over a box: advance each building from its own class.
      const classes = classesRef.current;
      const byId = indexByIdRef.current;
      const entries = ids
        .map((id) => {
          const index = byId.get(id);
          if (index === undefined) return null;
          return { id, class: cycleClass(classes[index]) };
        })
        .filter(Boolean);
      setOverridesState((previous) => setOverrideEntries(previous, entries));
    },
    [indexByIdRef]
  );

  const setClassForSelected = useCallback(
    (cls) => {
      if (!attrs || selectedIndex < 0 || selectedIndex >= attrs.n) return;
      const id = attrs.ids[selectedIndex];
      setOverridesState((previous) => setOverrides(previous, [id], cls));
    },
    [attrs, selectedIndex]
  );

  const clearSelectedOverride = useCallback(() => {
    if (!attrs || selectedIndex < 0 || selectedIndex >= attrs.n) return;
    setOverridesState((previous) =>
      clearOverride(previous, attrs.ids[selectedIndex])
    );
  }, [attrs, selectedIndex]);

  const clearAllOverrides = useCallback(() => setOverridesState({}), []);

  // The feature under an event, on one pane's renderer.
  function featureAtEvent(pane, event) {
    if (!pane.glMap) return null;
    let pixel = event.pixel;
    if (!pixel && event.position) {
      const pixels = pane.map.positionsToPixels([event.position]);
      pixel = pixels && pixels[0];
    }
    if (!pixel) return null;
    try {
      const rendered = pane.glMap.queryRenderedFeatures(
        pixel,
        pane.layerIds && pane.layerIds.length
          ? { layers: pane.layerIds }
          : undefined
      );
      const feature = rendered && rendered[0];
      if (!feature || feature.id == null) return null;
      rememberSourceId(pane, feature.source);
      return { id: feature.id, source: feature.source };
    } catch (error) {
      console.warn("queryRenderedFeatures failed:", error);
      return null;
    }
  }

  // Ctrl+drag box-select, wired per pane: a drag that starts on the uncovered
  // side of the divider has to select buildings too. Both canvases are the
  // same size and in the same place, so they share one rectangle element with
  // no coordinate translation.
  function attachBoxSelect(pane) {
    const canvas = pane.map.getCanvasContainer();
    let origin = null;

    const onDown = (event) => {
      if (!editModeRef.current) return;
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      event.stopPropagation();
      pane.map.setUserInteraction({ dragPanInteraction: false });
      const rect = canvas.getBoundingClientRect();
      origin = { x: event.clientX - rect.left, y: event.clientY - rect.top };
      const box = selectionBoxRef?.current;
      if (box) {
        box.style.display = "block";
        box.style.left = `${origin.x}px`;
        box.style.top = `${origin.y}px`;
        box.style.width = "0px";
        box.style.height = "0px";
      }
    };

    const onMove = (event) => {
      if (!origin) return;
      const rect = canvas.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      const box = selectionBoxRef?.current;
      if (box) {
        box.style.left = `${Math.min(origin.x, x)}px`;
        box.style.top = `${Math.min(origin.y, y)}px`;
        box.style.width = `${Math.abs(x - origin.x)}px`;
        box.style.height = `${Math.abs(y - origin.y)}px`;
      }
    };

    const onUp = (event) => {
      if (!origin) return;
      const rect = canvas.getBoundingClientRect();
      const selection = normalizeSelectionBox(origin, {
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      });
      origin = null;
      if (selectionBoxRef?.current) {
        selectionBoxRef.current.style.display = "none";
      }
      pane.map.setUserInteraction({ dragPanInteraction: true });
      if (!selection) return;
      const features = queryPane(pane, [
        [selection.x1, selection.y1],
        [selection.x2, selection.y2],
      ]);
      const ids = [
        ...new Set(
          features.filter((feature) => feature.id != null).map((f) => f.id)
        ),
      ];
      applyClickActionToIds(ids);
    };

    canvas.addEventListener("mousedown", onDown);
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      canvas.removeEventListener("mousedown", onDown);
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
  }

  // ── Layers ───────────────────────────────────────────────────────────────
  // Built once the maps are ready and the archive is in memory, on BOTH panes.
  // Everything the handlers need comes from refs, so this effect never re-runs
  // for an edit-mode toggle or a class change.
  //
  // It DOES re-run for `renderKey`: a version switch draws different classes
  // for the same buildings, and feature-state is per renderer, so both panes
  // are torn down (state cleared, layers and source removed, handlers and the
  // hydrate timer detached) and rebuilt rather than repainted in place.
  useEffect(() => {
    if (!mapsReady || !archiveKey || !window.atlas) return undefined;
    const maps = (mapRefs || [])
      .map((ref) => ref?.current)
      .filter((map) => map && typeof map.layers?.add === "function");
    if (maps.length === 0) return undefined;

    const panes = [];
    const paint = colorsRef.current;
    // A rebuild (new archive, or a remount) invalidates whatever the previous
    // renderer called our source.
    sourceIdsRef.current = {};

    maps.forEach((map, position) => {
      const ids = PANE_IDS[position] || PANE_IDS[PANE_IDS.length - 1];
      try {
        const source = new window.atlas.source.VectorTileSource(ids.sourceId, {
          type: "vector",
          url: `pmtiles://${archiveKey}`,
          // Azure Maps ignores promoteId, but the tiles already carry native
          // integer feature ids (tippecanoe --use-attribute-for-id=id), which
          // is what setFeatureState needs.
          promoteId: { [PMTILES_SOURCE_LAYER]: "id" },
        });
        map.sources.add(source);

        const fillLayer = new window.atlas.layer.PolygonLayer(
          ids.sourceId,
          ids.fillLayerId,
          {
            sourceLayer: PMTILES_SOURCE_LAYER,
            fillColor: fillColorExpression(paint),
            fillOpacity: FILL_OPACITY_EXPRESSION,
            visible: true,
          }
        );
        map.layers.add(fillLayer);

        const lineLayer = new window.atlas.layer.LineLayer(
          ids.sourceId,
          ids.lineLayerId,
          {
            sourceLayer: PMTILES_SOURCE_LAYER,
            strokeColor: strokeColorExpression(paint),
            strokeWidth: STROKE_WIDTH_EXPRESSION,
            visible: true,
          }
        );
        map.layers.add(lineLayer);

        const glMap = findGlMap(map);
        const pane = {
          key: ids.key,
          map,
          source,
          fillLayer,
          lineLayer,
          glMap,
          layerIds: discoverFillLayerIds(glMap, [ids.fillLayerId], [ids.sourceId]),
          sourceId: discoverVectorSourceId(glMap, ids.sourceId),
          handlers: [],
          detachBox: null,
        };

        // Interaction handlers are attached ONCE and bail out unless edit mode
        // is on. Adding and removing them on every toggle is how listeners get
        // orphaned; a ref check cannot leak.
        const onClick = (event) => {
          if (!editModeRef.current) return;
          // Ctrl+click starts a box-select drag; don't also set a class.
          if (
            event.originalEvent &&
            (event.originalEvent.ctrlKey || event.originalEvent.metaKey)
          ) {
            return;
          }
          const feature = featureAtEvent(pane, event);
          if (feature) handleFeatureClick(feature.id);
        };
        const onContextMenu = (event) => {
          if (!editModeRef.current) return;
          // The browser's own menu over a map you are editing is never what
          // the analyst wanted.
          if (event?.originalEvent?.preventDefault) {
            event.originalEvent.preventDefault();
          }
          const feature = featureAtEvent(pane, event);
          if (feature) handleClearOverrideForId(feature.id);
          return false;
        };
        const onHydrate = () => scheduleHydrate();
        const onSourceData = (event) => {
          if (event && event.isSourceLoaded) scheduleHydrate();
        };
        map.events.add("click", fillLayer, onClick);
        map.events.add("contextmenu", fillLayer, onContextMenu);
        map.events.add("moveend", onHydrate);
        map.events.add("sourcedata", onSourceData);
        pane.handlers = [
          ["click", fillLayer, onClick],
          ["contextmenu", fillLayer, onContextMenu],
          ["moveend", null, onHydrate],
          ["sourcedata", null, onSourceData],
        ];
        pane.detachBox = attachBoxSelect(pane);
        panes.push(pane);
      } catch (error) {
        console.warn("Could not add the footprint layer to a map:", error);
      }
    });

    panesRef.current = panes;
    setLayersReady(panes.length > 0);
    hydrateViewport();

    return () => {
      for (const pane of panes) {
        if (pane.detachBox) pane.detachBox();
        for (const [name, target, handler] of pane.handlers) {
          try {
            if (target) pane.map.events.remove(name, target, handler);
            else pane.map.events.remove(name, handler);
          } catch (error) {
            console.warn("Could not detach a footprint handler:", error);
          }
        }
        // Wipe this pane's feature-state BEFORE the source goes: a rebuild
        // re-creates the source under the same id, and a renderer that kept
        // its state map keyed by that id would hand the next version the
        // previous one's colours on this pane only. That asymmetry between
        // the two panes is the bug this page has shipped twice.
        try {
          if (pane.glMap && typeof pane.glMap.removeFeatureState === "function") {
            pane.glMap.removeFeatureState({
              source: sourceIdsRef.current[pane.key] || pane.sourceId,
              sourceLayer: PMTILES_SOURCE_LAYER,
            });
          }
        } catch (error) {
          console.warn("Could not clear the footprint feature-state:", error);
        }
        try {
          pane.map.layers.remove(pane.fillLayer);
          pane.map.layers.remove(pane.lineLayer);
          pane.map.sources.remove(pane.source);
        } catch (error) {
          console.warn("Could not remove the footprint layer:", error);
        }
        try {
          pane.map.getCanvasContainer().style.cursor = "";
        } catch {
          // The map may already be disposed; nothing to restore.
        }
      }
      if (hydrateTimerRef.current) {
        window.clearTimeout(hydrateTimerRef.current);
        hydrateTimerRef.current = null;
      }
      panesRef.current = [];
      sourceIdsRef.current = {};
      if (mountedRef.current) setLayersReady(false);
    };
    // The callbacks below are stable (useCallback over refs); listing them
    // would not change when this effect runs, and featureAtEvent /
    // attachBoxSelect are plain closures defined in this module scope.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapsReady, archiveKey, renderKey]);

  // A different version means different classes for the same buildings, so
  // every piece of per-building state belongs to the version it came from:
  // the analyst's in-progress overrides, what "saved" means, the selection,
  // the filter and the thresholds. Rewinding them here (rather than leaving
  // them to bleed across the switch) is what stops version 2 being saved with
  // version 1's edits silently folded in.
  //
  // Skipped on the first run: everything below is already at its initial
  // value, and setting it again would cost a render for nothing.
  const renderKeyRef = useRef(renderKey);
  useEffect(() => {
    if (renderKeyRef.current === renderKey) return;
    renderKeyRef.current = renderKey;
    setOverridesState({});
    setSavedBaseline(null);
    setSavedResult(null);
    setSaveError("");
    setSelectedIndex(-1);
    setFilter(FILTER_ALL);
    setThresholdOverride(null);
    setUnknownThresholdOverride(null);
    selectedIdRef.current = null;
    // Centroids were harvested from the previous render pass; the geometry is
    // the same, but the cache refills itself on the next hydrate and keeping
    // it would pin memory to a version nobody is looking at any more.
    centroidsRef.current = new Map();
  }, [renderKey]);

  // ── Classification ───────────────────────────────────────────────────────
  // Every building's class is a pure function of the scores, the thresholds
  // and the analyst's overrides, so it is derived rather than stored — that
  // is what makes the threshold slider recolour the map with no server round
  // trip and no state to keep in sync.
  const classification = useMemo(
    () =>
      attrs
        ? classifyAll(attrs, { threshold, unknownThreshold, overrides })
        : null,
    [attrs, threshold, unknownThreshold, overrides]
  );

  // "N buildings would change class", measured against the operating point
  // the current view was saved (or shipped) with.
  const changeCount = useMemo(
    () =>
      attrs
        ? countClassChanges(
            attrs,
            baseline,
            { threshold, unknownThreshold },
            overrides
          )
        : 0,
    [attrs, baseline, threshold, unknownThreshold, overrides]
  );

  // Mirror the classification for the map handlers (which close over the
  // render that registered them) and repaint what is on screen. layersReady
  // is in the deps because the layers are created inside the maps' async
  // "ready" path — reading the pane refs during render would see an empty
  // list and never re-run.
  useEffect(() => {
    classesRef.current = classification?.classes || [];
    editedRef.current = classification?.edited || [];
    if (!layersReady || !classification) return;
    hydrateViewport();
  }, [classification, filter, layersReady, hydrateViewport]);

  // Resolve the map palette from the active Fluent theme, and re-apply it when
  // the user flips light/dark or changes the brand palette. Paint expressions
  // are per-renderer, so both panes get their own copy.
  useEffect(() => {
    const resolved = resolveMapColors(
      MAP_COLOR_TOKENS,
      themeColorLookup(themeHostRef?.current)
    );
    colorsRef.current = resolved;
    const fillColor = fillColorExpression(resolved);
    const strokeColor = strokeColorExpression(resolved);
    for (const pane of panesRef.current) {
      try {
        pane.fillLayer.setOptions({ fillColor });
        pane.lineLayer.setOptions({ strokeColor });
      } catch (error) {
        console.warn("Could not restyle the footprint layer:", error);
      }
    }
  }, [isDark, palette, layersReady, themeHostRef]);

  // Visibility, driven by the InfoPanel checkbox. Edit mode forces the layer
  // on: editing footprints nobody can see is not a state worth supporting.
  useEffect(() => {
    const visible = isEditMode || isVisible;
    for (const pane of panesRef.current) {
      try {
        pane.fillLayer.setOptions({ visible });
        pane.lineLayer.setOptions({ visible });
      } catch (error) {
        console.warn("Could not toggle the footprint layer:", error);
      }
    }
  }, [isVisible, isEditMode, layersReady]);

  // The pointer cursor is the only interaction affordance that changes with
  // edit mode; the handlers themselves are always attached and check the ref.
  useEffect(() => {
    for (const pane of panesRef.current) {
      try {
        pane.map.getCanvasContainer().style.cursor = isEditMode
          ? "pointer"
          : "";
      } catch (error) {
        console.warn("Could not set the map cursor:", error);
      }
    }
  }, [isEditMode, layersReady]);

  // ── Selection ────────────────────────────────────────────────────────────
  const filteredIndices = useMemo(
    () => (classification ? filterIndices(classification, filter) : []),
    [classification, filter]
  );

  // Changing the filter can strand the selection outside the visible set, so
  // snap it to the first match as part of the same event rather than in an
  // effect (which would cost an extra render pass).
  const handleFilterChange = useCallback(
    (nextFilter) => {
      setFilter(nextFilter);
      if (!classification) return;
      const nextIndices = filterIndices(classification, nextFilter);
      if (nextIndices.length === 0) return;
      setSelectedIndex((current) =>
        current >= 0 && !nextIndices.includes(current)
          ? nextIndices[0]
          : current
      );
    },
    [classification]
  );

  // Highlight the selected footprint, and pan to it when the selection came
  // from Prev/Next. Buildings whose tile has never rendered have no cached
  // centroid, so there is nowhere to pan yet.
  useEffect(() => {
    if (!layersReady) return;
    const previousId = selectedIdRef.current;
    const nextId =
      attrs && selectedIndex >= 0 && selectedIndex < attrs.n
        ? attrs.ids[selectedIndex]
        : null;
    if (previousId != null && previousId !== nextId) {
      writeFeatureState(previousId, { selected: false });
    }
    selectedIdRef.current = nextId;
    if (nextId == null) {
      repaintFootprints();
      return;
    }
    writeFeatureState(nextId, { selected: true });
    repaintFootprints();
    const shouldPan = pendingPanRef.current;
    pendingPanRef.current = false;
    const centroid = centroidsRef.current.get(nextId);
    const pane = panesRef.current[0];
    if (shouldPan && centroid && pane?.map) {
      // Both panes share a camera through atlas.SwipeMap, so moving one moves
      // the other — adding a second setCamera here would double-update them.
      const camera = pane.map.getCamera();
      pane.map.setCamera({
        center: centroid,
        zoom: Math.max(camera?.zoom || 0, 17.5),
        duration: 500,
      });
    }
  }, [
    selectedIndex,
    layersReady,
    attrs,
    repaintFootprints,
    writeFeatureState,
  ]);

  const navigateInFilter = useCallback(
    (direction) => {
      if (filteredIndices.length === 0) return;
      // Prefer buildings we can actually pan to; fall back to the plain next
      // one so navigation never stalls.
      const hasLocation = (index) => {
        const id = attrs?.ids?.[index];
        return id != null && centroidsRef.current.has(id);
      };
      const next = nextIndexInList(
        filteredIndices,
        selectedIndex,
        direction,
        hasLocation
      );
      if (next === null) return;
      pendingPanRef.current = true;
      setSelectedIndex(next);
    },
    [attrs, filteredIndices, selectedIndex]
  );

  // ── Derived view data ────────────────────────────────────────────────────
  const currentBuilding = useMemo(() => {
    if (
      !attrs ||
      !classification ||
      selectedIndex < 0 ||
      selectedIndex >= attrs.n
    ) {
      return null;
    }
    return {
      id: attrs.ids[selectedIndex],
      overtureId: attrs.overtureIds[selectedIndex],
      damage: attrs.damage[selectedIndex],
      unknown: attrs.unknown[selectedIndex],
      cls: classification.classes[selectedIndex],
      edited: classification.edited[selectedIndex],
    };
  }, [attrs, classification, selectedIndex]);

  const isDirty = useMemo(
    () => hasUnsavedEdits({ overrides, threshold, unknownThreshold, baseline }),
    [overrides, threshold, unknownThreshold, baseline]
  );

  // ── Save ─────────────────────────────────────────────────────────────────
  const save = useCallback(async () => {
    setIsSaving(true);
    setSaveError("");
    try {
      const payload = buildSavePayload({
        projectId,
        imageLayerId,
        modelId,
        threshold,
        unknownThreshold,
        overrides,
        // Carries the loaded version's own classes into the save: the server
        // derives every version from the RAW GeoPackage, so editing on top of
        // version N has to re-send what N established or the new version
        // would quietly lose it.
        attrs,
      });
      const result = await apiPut("PutEditedPredictions", payload);
      // apiPut surfaces a conflict as the bare status code.
      if (result === 409) {
        throw new Error(
          "Another version is being written for this model. Try saving again in a moment."
        );
      }
      if (!result || result.version == null) {
        throw new Error("The server did not return a new version number.");
      }
      if (!mountedRef.current) return result;
      setSavedResult(result);
      // Everything just written is now the thing later edits are measured
      // against, so the page stops calling saved work "unsaved".
      setSavedBaseline({
        threshold,
        unknownThreshold,
        overrides: { ...overrides },
      });
      if (typeof onSaved === "function") await onSaved(result);
      return result;
    } catch (error) {
      const message =
        error?.message || "Failed to save the edited predictions.";
      if (mountedRef.current) setSaveError(message);
      throw error;
    } finally {
      if (mountedRef.current) setIsSaving(false);
    }
  }, [
    projectId,
    imageLayerId,
    modelId,
    threshold,
    unknownThreshold,
    overrides,
    attrs,
    onSaved,
  ]);

  // Throw away every unsaved edit — used when the analyst confirms leaving
  // edit mode. "Unsaved" means "since the last save", so this rewinds to the
  // baseline rather than to nothing: edits that were already written to a
  // version must survive, or the page would immediately consider itself dirty
  // again.
  const discardEdits = useCallback(() => {
    setOverridesState({ ...(baseline.overrides || {}) });
    setThresholdOverride(baseline.threshold);
    setUnknownThresholdOverride(baseline.unknownThreshold);
    setSelectedIndex(-1);
    setFilter(FILTER_ALL);
    setSaveError("");
  }, [baseline]);

  return {
    layersReady,
    isVisible,
    setIsVisible,
    classification,
    filter,
    setFilter: handleFilterChange,
    filteredIndices,
    selectedIndex,
    currentBuilding,
    clickAction,
    setClickAction,
    setClassForSelected,
    clearSelectedOverride,
    clearAllOverrides,
    navigateInFilter,
    threshold,
    setThreshold: setThresholdOverride,
    unknownThreshold,
    setUnknownThreshold: setUnknownThresholdOverride,
    baseline,
    changeCount,
    overrides,
    isDirty,
    save,
    discardEdits,
    isSaving,
    saveError,
    savedResult,
  };
};

export default usePredictionFootprints;
