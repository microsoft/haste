// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { Button, makeStyles, tokens } from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
import { useEffect, useMemo, useRef, useState, useContext } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { apiGet, apiPut } from "../../util/api";
import { getAzureMapsAuthOptions, isAzureMapsPlaceholder } from "../../util/azureMapsAuth";
import { AppContext } from "../../AppContext.jsx";
import BuildingValidationRightPanel from "./BuildingValidationRightPanel.jsx";
import ValidationConfigModal from "./ValidationConfigModal.jsx";
import {
  DEFAULT_VALIDATION_SAMPLE,
  resolveSampleSize,
} from "./validationConfig.js";
import { loadValidationMapData } from "./loadValidationMapData.js";
import { loadImagery } from "../LabelingTool/LabelingToolHelper.js";
import { shouldIgnoreShortcut } from "../keyboardShortcuts.js";
import "../../assets/css/labels.css";
import "../../assets/css/drawingToolbar.css";

const LABEL_COLORS = {
  Damaged: "#C50F1F",
  NotDamaged: "#107C10",
  Unknown: "#4D4D4D",
  unlabeled: "#BDBDBD",
};

const useStyles = makeStyles({
  root: {
    display: "flex",
    flexGrow: 1,
    position: "relative",
    isolation: "isolate",
    overflow: "hidden",
    color: tokens.colorNeutralForeground1,
    backgroundColor: tokens.colorNeutralBackground2,
  },
  emptyState: {
    position: "absolute",
    top: "70px",
    right: "16px",
    zIndex: 1000,
    maxWidth: "calc(100% - 32px)",
    padding: `${tokens.spacingVerticalM} ${tokens.spacingHorizontalL}`,
    color: tokens.colorNeutralForeground1,
    backgroundColor: tokens.colorNeutralBackground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium,
    boxShadow: tokens.shadow8,
  },
});

// Filter values used by the right-panel dropdown and the map dim logic.
// 'all' means no filter; 'unlabeled' means buildings with no label set yet;
// the three class names match the values stored on labels[id].label.
const FILTER_VALUES = ["all", "unlabeled", "Damaged", "NotDamaged", "Unknown"];

function buildingMatchesFilter(feature, labels, filter) {
  if (filter === "all") return true;
  const lbl = labels[feature.properties?.id]?.label;
  if (filter === "unlabeled") return !lbl;
  return lbl === filter;
}

function extractCentroid(feature) {
  try {
    const geom = feature.geometry;
    if (!geom) return null;
    const coords =
      geom.type === "Polygon"
        ? geom.coordinates[0]
        : geom.type === "MultiPolygon"
        ? geom.coordinates[0][0]
        : null;
    if (!coords || coords.length === 0) return null;
    const lng = coords.reduce((sum, coord) => sum + coord[0], 0) / coords.length;
    const lat = coords.reduce((sum, coord) => sum + coord[1], 0) / coords.length;
    return [lng, lat];
  } catch {
    return null;
  }
}

const BuildingValidation = () => {
  const styles = useStyles();
  const { projectId, imageLayerId } = useParams();
  const navigate = useNavigate();
  const { setIsLoading, setDialog, setAppHeaderRightButtons } = useContext(AppContext);

  const mapContainerRef = useRef(null);
  const mapRef = useRef(null);
  const datasourceRef = useRef(null);
  const preImageryRef = useRef(null);
  const postImageryRef = useRef(null);
  const fillLayerRef = useRef(null);
  // Tile URL templates (with {z}/{x}/{y} placeholders) saved alongside
  // the layer instances so the prefetcher can build URLs without
  // poking at Azure Maps internals.
  const preTileUrlRef = useRef(null);
  const postTileUrlRef = useRef(null);
  // De-dupe set: URLs we've already requested. Prevents thrashing the
  // tile server when the user walks back and forth across buildings.
  const prefetchedTilesRef = useRef(new Set());

  const [isMapReady, setIsMapReady] = useState(false);
  const [features, setFeatures] = useState([]);
  const [labels, setLabels] = useState({});
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [isSaving, setIsSaving] = useState(false);
  const [filter, setFilter] = useState("all");
  // Both toggles default to on so the page starts in the labeling-ready
  // state. Turning the fill off reveals the imagery under each polygon;
  // turning the post-event layer off lets the user compare against the
  // satellite basemap underneath.
  const [showFill, setShowFill] = useState(true);
  const [showPostImagery, setShowPostImagery] = useState(true);
  // The imagery layers are created inside the map's async "ready"
  // handler, which fires after createMap() resolves and flips
  // isMapReady. Mirroring their availability in state (rather than
  // reading the refs during render) is what re-renders the right panel
  // once the layers actually exist.
  const [hasPreImagery, setHasPreImagery] = useState(false);
  const [hasPostImagery, setHasPostImagery] = useState(false);
  // The polygon datasource is also created in the "ready" handler, so the
  // styling effect below would otherwise run once (before it exists),
  // bail out, and never re-run — leaving the initial footprints drawn
  // from the raw GeoJSON with no _label/_selected/_passesFilter set.
  const [isDatasourceReady, setIsDatasourceReady] = useState(false);
  // How many footprints this layer validates. Read from the validation
  // document on load and changed through the settings modal.
  const [sampleSize, setSampleSize] = useState(DEFAULT_VALIDATION_SAMPLE);
  const [configOpen, setConfigOpen] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [initAttempt, setInitAttempt] = useState(0);

  // Post-event is only genuinely showable once that layer exists. Without
  // this, the toggle defaults to "post" on a layer that has no post-event
  // imagery, which hides the pre-event layer and leaves just the basemap
  // while the panel still claims post-event is on screen.
  const showPostEvent = showPostImagery && hasPostImagery;

  // Indices into `features` that pass the current filter. Prev / Next /
  // Skip-to-next-unlabeled all walk this subset, NOT the raw features
  // list, so the filter genuinely restricts navigation.
  const filteredIndices = useMemo(
    () =>
      features
        .map((f, i) => [f, i])
        .filter(([f]) => buildingMatchesFilter(f, labels, filter))
        .map(([, i]) => i),
    [features, labels, filter]
  );

  // Find the next index from a starting point, wrapping around the end.
  // Used by Prev/Next/SkipNext so navigation continues cyclically inside
  // the filtered subset. Returns null when the candidate list is empty.
  function nextIndexInList(list, fromIndex, direction = 1) {
    if (list.length === 0) return null;
    // Find where the current selection is in the filtered list (or the
    // insertion point if it isn't in the list at all).
    let pos = list.indexOf(fromIndex);
    if (pos === -1) {
      // Selection isn't in the filtered set — jump to the closest
      // following candidate, or wrap to the first one.
      const after = list.find((i) => i > fromIndex);
      return after !== undefined ? after : list[0];
    }
    pos = (pos + direction + list.length) % list.length;
    return list[pos];
  }

  function skipToNextUnlabeled() {
    const unlabeledIndices = features
      .map((f, i) => [f, i])
      .filter(([f]) => !labels[f.properties?.id]?.label)
      .map(([, i]) => i);
    const next = nextIndexInList(unlabeledIndices, selectedIndex, 1);
    if (next !== null) setSelectedIndex(next);
  }

  function navigateInFilter(direction) {
    const next = nextIndexInList(filteredIndices, selectedIndex, direction);
    if (next !== null) setSelectedIndex(next);
  }

  useEffect(() => {
    const init = async () => {
      if (!window.atlas) return;
      setIsLoading(true, "Loading Building Validation");
      try {
        // eslint-disable-next-line react-hooks/immutability
        await createMap();
        setIsMapReady(true);
        setLoadError(false);
      } catch (error) {
        console.error("Failed to initialize building validation:", error);
        setLoadError(true);
      } finally {
        setIsLoading(false);
      }
    };

    init();

    return () => {
      setAppHeaderRightButtons([]);
      if (mapRef.current) {
        mapRef.current.dispose();
        mapRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initAttempt]);

  async function fetchFootprints(size) {
    return apiGet(
      `GetBuildingFootprintsGeoJSON?projectId=${projectId}` +
        `&imageLayerId=${imageLayerId}&sample=${size}`
    );
  }

  // Apply a new sample size without leaving the page. The sample is a
  // permutation prefix, so a larger size returns the same buildings plus
  // more — the labels held in state stay valid and simply re-attach to the
  // features they already belonged to.
  async function reloadFootprints(size) {
    setIsLoading(true, "Loading buildings…");
    try {
      const footprintsGeoJSON = await fetchFootprints(size);
      const featuresArr = footprintsGeoJSON?.features || [];
      setSampleSize(size);
      setFeatures(featuresArr);
      setSelectedIndex(0);
    } catch (e) {
      console.error("Failed to reload building footprints:", e);
      setDialog("Error", "Failed to reload the buildings for this layer.", [
        {
          type: "primary",
          key: "close",
          text: "Close",
          onClick: () => setDialog(),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  }

  async function createMap() {
    const {
      layerData,
      validationData,
      footprintsGeoJSON,
      sampleSize: configuredSample,
    } = await loadValidationMapData({
      get: apiGet,
      projectId,
      imageLayerId,
      resolveSampleSize,
    });
    setSampleSize(configuredSample);

    const existingLabels = validationData?.labels || {};
    setLabels(existingLabels);

    const featuresArr = footprintsGeoJSON?.features || [];
    setFeatures(featuresArr);

    // Build Azure Maps
    const map = new window.atlas.Map(mapContainerRef.current, {
      center: [0, 0],
      zoom: 3,
      maxPitch: 0,
      pitch: 0,
      style: isAzureMapsPlaceholder ? "blank" : "satellite",
      language: "en-US",
      authOptions: getAzureMapsAuthOptions(),
    });

    map.events.add("ready", async function () {
      map.setUserInteraction({
        dragRotateInteraction: false,
        scrollZoomInteraction: true,
        pinchZoomInteraction: true,
        pinchRotateInteraction: false,
      });

      map.controls.add(new window.atlas.control.ZoomControl(), {
        position: "bottom-left",
      });

      // Load post-event imagery tile layer if available
      if (layerData?.imagery?.preEventTileUrl) {
        loadImagery(
          layerData.imagery.preEventTileUrl,
          map,
          preImageryRef,
          "preEventImageryLayer",
          false
        );
        preTileUrlRef.current = layerData.imagery.preEventTileUrl;
        setHasPreImagery(true);
      }
      if (layerData?.imagery?.postEventTileUrl) {
        loadImagery(
          layerData.imagery.postEventTileUrl,
          map,
          postImageryRef,
          "postEventImageryLayer",
          true
        );
        postTileUrlRef.current = layerData.imagery.postEventTileUrl;
        setHasPostImagery(true);
      }

      // Create datasource for building polygons
      const datasource = new window.atlas.source.DataSource();
      map.sources.add(datasource);
      datasourceRef.current = datasource;
      setIsDatasourceReady(true);

      if (featuresArr.length > 0) {
        datasource.add(footprintsGeoJSON);

        // Polygon fill layer — keep reference for event binding.
        // Out-of-filter buildings render at low opacity so they stay
        // as context without dominating the visible field.
        const fillLayer = new window.atlas.layer.PolygonLayer(datasource, "buildingFill", {
          fillColor: [
            "case",
            ["==", ["get", "_label"], "Damaged"], LABEL_COLORS.Damaged,
            ["==", ["get", "_label"], "NotDamaged"], LABEL_COLORS.NotDamaged,
            ["==", ["get", "_label"], "Unknown"], LABEL_COLORS.Unknown,
            LABEL_COLORS.unlabeled,
          ],
          fillOpacity: [
            "case",
            ["==", ["get", "_passesFilter"], false], 0.1,
            0.5,
          ],
        });
        map.layers.add(fillLayer);
        fillLayerRef.current = fillLayer;

        // Polygon outline layer
        map.layers.add(
          new window.atlas.layer.LineLayer(datasource, "buildingOutline", {
            strokeColor: [
              "case",
              ["==", ["get", "_selected"], true], "#ffffff",
              "#1a5276",
            ],
            strokeWidth: [
              "case",
              ["==", ["get", "_selected"], true], 3,
              1,
            ],
          })
        );

        // Click handler: pass layer object (not string ID) — Atlas v3 requirement
        map.events.add("click", fillLayer, (e) => {
          if (e.shapes && e.shapes.length > 0) {
            const clickedId = e.shapes[0].getProperties().id;
            const idx = featuresArr.findIndex((f) => f.properties?.id === clickedId);
            if (idx >= 0) {
              setSelectedIndex(idx);
            }
          }
        });
        map.getCanvasContainer().style.cursor = "pointer";

        // Start zoomed in on the first building to be labeled rather
        // than the full study-area extent — the user asked for an
        // immediately-actionable view. The [labels, selectedIndex,
        // features] effect below also pans to selectedIndex, but only
        // after the React state settles; setting the camera here gets
        // the initial frame right without waiting for a re-render.
        const firstCenter = extractCentroid(featuresArr[0]);
        if (firstCenter) {
          map.setCamera({ center: firstCenter, zoom: 18, duration: 0 });
        }
      }
    });

    mapRef.current = map;
  }

  // Toggle building polygon fill visibility (selection outline + click
  // handler still apply when fill is off — only the colored fill goes
  // away, so the imagery underneath is visible).
  useEffect(() => {
    if (fillLayerRef.current) {
      fillLayerRef.current.setOptions({ visible: showFill });
    }
  }, [showFill, isMapReady]);

  // A single-map comparison: post-event on, or pre-event/basemap when off.
  useEffect(() => {
    if (preImageryRef.current) {
      preImageryRef.current.setOptions({ visible: !showPostEvent });
    }
    if (postImageryRef.current) {
      postImageryRef.current.setOptions({ visible: showPostEvent });
    }
  }, [showPostEvent, isMapReady, hasPreImagery, hasPostImagery]);

  // Update polygon properties when labels, selectedIndex, or filter change
  useEffect(() => {
    if (!datasourceRef.current || features.length === 0) return;

    const updatedFeatures = features.map((f, idx) => ({
      ...f,
      properties: {
        ...f.properties,
        _label: labels[f.properties?.id]?.label || null,
        _selected: idx === selectedIndex,
        _passesFilter: buildingMatchesFilter(f, labels, filter),
      },
    }));

    datasourceRef.current.clear();
    datasourceRef.current.add({ type: "FeatureCollection", features: updatedFeatures });

    // Pan map to selected building
    const selected = features[selectedIndex];
    if (selected && mapRef.current) {
      const coords = extractCentroid(selected);
      if (coords) {
        mapRef.current.setCamera({ center: coords, zoom: 18, duration: 500 });
      }
    }
  }, [labels, selectedIndex, features, filter, isDatasourceReady]);

  // When the filter changes such that the current selection no longer
  // matches, jump to the first building that does — so the user isn't
  // looking at a building that's hidden under the dim layer.
  useEffect(() => {
    if (filteredIndices.length === 0) return;
    if (!filteredIndices.includes(selectedIndex)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelectedIndex(filteredIndices[0]);
    }
  }, [filteredIndices, selectedIndex]);

  // Web-Mercator slippy-tile math. Returns {x, y, z} for the tile that
  // contains the given lng/lat at zoom z. Matches the {z}/{x}/{y} URL
  // template emitted by titiler so the prefetched URLs share a cache
  // key with what Azure Maps TileLayer will eventually request.
  function lnglatToTile(lng, lat, z) {
    const n = 2 ** z;
    const x = Math.floor(((lng + 180) / 360) * n);
    const latRad = (lat * Math.PI) / 180;
    const y = Math.floor(
      ((1 -
        Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) /
        2) *
        n
    );
    return { x, y, z };
  }

  // Warm the browser HTTP cache for the tiles around a building so that
  // when the user navigates to it the basemap pops in immediately
  // instead of streaming in from titiler. Fetches a 3×3 grid at zoom 18
  // around the centroid for whichever tile-URL templates are available,
  // skipping URLs we've already requested. fetch() with no-store off
  // (the default) lets the browser cache the response under the same
  // URL the TileLayer will use later.
  function prefetchTilesAroundFeature(feature, zoom = 18) {
    if (!feature) return;
    const center = extractCentroid(feature);
    if (!center) return;
    const [lng, lat] = center;
    const { x: cx, y: cy, z } = lnglatToTile(lng, lat, zoom);
    const templates = [preTileUrlRef.current, postTileUrlRef.current].filter(
      Boolean
    );
    if (templates.length === 0) return;
    const seen = prefetchedTilesRef.current;
    for (let dy = -1; dy <= 1; dy++) {
      for (let dx = -1; dx <= 1; dx++) {
        const tx = cx + dx;
        const ty = cy + dy;
        if (tx < 0 || ty < 0) continue;
        for (const tpl of templates) {
          const url = tpl
            .replace("{z}", String(z))
            .replace("{x}", String(tx))
            .replace("{y}", String(ty));
          if (seen.has(url)) continue;
          seen.add(url);
          // Fire-and-forget. mode: 'cors' matches what TileLayer uses
          // internally (XHR with CORS) so the response lands in the
          // same HTTP cache slot; errors are silently ignored — a
          // missed prefetch isn't fatal, the layer will just request
          // it on demand.
          fetch(url, { mode: "cors", credentials: "omit" }).catch(() => {});
        }
      }
    }
  }

  // After the selection settles, warm the cache for the immediate
  // neighbors (±2 in the filtered list) so the next Prev/Next press
  // shows the basemap instantly. Done in an effect so it doesn't block
  // the camera pan.
  useEffect(() => {
    if (!isMapReady || features.length === 0) return;
    if (!preTileUrlRef.current && !postTileUrlRef.current) return;
    // Prefetch the current building too — covers the initial-zoom case
    // and any tile that fell outside the previous frame.
    const pos = filteredIndices.indexOf(selectedIndex);
    const neighbors = [];
    if (pos >= 0) {
      for (const offset of [0, 1, -1, 2, -2]) {
        const i = filteredIndices[pos + offset];
        if (i !== undefined) neighbors.push(i);
      }
    } else {
      neighbors.push(selectedIndex);
    }
    for (const i of neighbors) {
      prefetchTilesAroundFeature(features[i]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedIndex, filteredIndices, isMapReady]);

  function handleLabel(labelValue) {
    const feature = features[selectedIndex];
    if (!feature) return;
    const buildingId = feature.properties?.id;
    setLabels((prev) => {
      const next = {
        ...prev,
        [buildingId]: {
          id: buildingId,
          label: labelValue,
          updatedAt: new Date().toISOString(),
        },
      };
      // Advance to the next unlabeled building
      const nextIdx = features.findIndex(
        (f, i) => i > selectedIndex && !next[f.properties?.id]?.label
      );
      if (nextIdx >= 0) {
        setSelectedIndex(nextIdx);
      }
      return next;
    });
  }

  // Keyboard shortcuts:
  //   1 / 2 / 3       — assign Damaged / NotDamaged / Unknown
  //   ArrowLeft / ArrowRight — move through the filtered list
  //   A / D          — show pre (or basemap) / post imagery
  // The right-panel toggles and dropdown remain focusable; the
  // editable-target guard keeps shortcuts from hijacking typing.
  useEffect(() => {
    const keyMap = { "1": "Damaged", "2": "NotDamaged", "3": "Unknown" };
    function onKeyDown(e) {
      if (shouldIgnoreShortcut(e)) return;
      if (e.ctrlKey || e.altKey || e.metaKey) return;
      const labelValue = keyMap[e.key];
      if (labelValue) {
        handleLabel(labelValue);
        return;
      }
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        navigateInFilter(-1);
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        navigateInFilter(1);
      } else {
        const key = e.key.toLowerCase();
        if (key === "a") setShowPostImagery(false);
        else if (key === "d" && hasPostImagery) setShowPostImagery(true);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [features, selectedIndex, filteredIndices, hasPostImagery]);

  function handleClearLabels() {
    const count = Object.keys(labels).length;
    if (count === 0) return;

    setDialog(
      "Clear validation labels?",
      `This deletes all ${count} validation label${count === 1 ? "" : "s"} ` +
        "for this image layer. This cannot be undone.",
      [
        {
          type: "primary",
          key: "clear",
          text: "Yes, clear them",
          onClick: () => {
            setDialog();
            clearLabels();
          },
        },
        {
          key: "cancel",
          text: "Cancel",
          onClick: () => setDialog(),
        },
      ]
    );
  }

  async function clearLabels() {
    setIsSaving(true);
    try {
      // An empty label set. The server preserves this layer's configured
      // sample size on this route, so clearing does not reset the count.
      await apiPut("PutBuildingValidation", {
        projectId,
        imageLayerId,
        labels: {},
      });
      setLabels({});
      setDialog("Cleared", "Validation labels cleared.", [
        { type: "primary", key: "close", text: "Close", onClick: () => setDialog() },
      ]);
    } catch (e) {
      console.error("Failed to clear validation labels:", e);
      setDialog("Error", "Failed to clear validation labels.", [
        { type: "primary", key: "close", text: "Close", onClick: () => setDialog() },
      ]);
    } finally {
      setIsSaving(false);
    }
  }

  async function handleSave() {
    setIsSaving(true);
    try {
      await apiPut("PutBuildingValidation", {
        projectId,
        imageLayerId,
        labels,
      });
      setDialog("Saved", "Validation labels saved successfully.", [
        { type: "primary", key: "close", text: "Close", onClick: () => setDialog() },
      ]);
    } catch {
      setDialog("Error", "Failed to save validation labels.", [
        { type: "primary", key: "close", text: "Close", onClick: () => setDialog() },
      ]);
    } finally {
      setIsSaving(false);
    }
  }

  function handleDownload() {
    const labeledFeatures = features.map((f) => ({
      ...f,
      properties: {
        ...f.properties,
        label: labels[f.properties?.id]?.label || null,
        labeledAt: labels[f.properties?.id]?.updatedAt || null,
      },
    }));

    const geojson = JSON.stringify(
      { type: "FeatureCollection", features: labeledFeatures },
      null,
      2
    );
    const blob = new Blob([geojson], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `building_validation_${imageLayerId}.geojson`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const labeledCount = Object.keys(labels).length;

  return (
    <div
      className={`${styles.root} building-validation-page`}
      data-map-ready={isDatasourceReady ? "true" : "false"}
    >
      {/* Back button — shares the Interactive Labeler navigation surface. */}
      <div className="labeling-tool-surface labeling-navigation-controls">
        <Button
          id="backButton"
          appearance="transparent"
          icon={<FluentIcon name="ChevronLeft" />}
          onClick={() => navigate(-1)}
        >
          Back
        </Button>
        <Button
          id="validationConfigButton"
          appearance="transparent"
          icon={<FluentIcon name="Settings" />}
          title="Building Validation settings"
          onClick={() => setConfigOpen(true)}
        >
          Settings
        </Button>
      </div>

      {configOpen && (
        <ValidationConfigModal
          projectId={projectId}
          imageLayerId={imageLayerId}
          onClose={() => setConfigOpen(false)}
          onSaved={(size) => {
            if (size !== sampleSize) reloadFootprints(size);
          }}
          onCleared={() => setLabels({})}
        />
      )}

      {/* Map container */}
      <div ref={mapContainerRef} id="validationMap" style={{ flexGrow: 1 }} />

      {loadError && (
        <div className={styles.emptyState} role="alert">
          <p>Building validation could not be loaded.</p>
          <Button
            appearance="primary"
            onClick={() => {
              setLoadError(false);
              setIsMapReady(false);
              setInitAttempt((value) => value + 1);
            }}
          >
            Retry
          </Button>
        </div>
      )}

      {/* Right panel */}
      {isMapReady && features.length > 0 && (
        <BuildingValidationRightPanel
          features={features}
          labels={labels}
          selectedIndex={selectedIndex}
          onLabel={handleLabel}
          onSave={handleSave}
          onDownload={handleDownload}
          onClearLabels={handleClearLabels}
          isSaving={isSaving}
          labeledCount={labeledCount}
          filter={filter}
          setFilter={setFilter}
          filterValues={FILTER_VALUES}
          filteredIndices={filteredIndices}
          onPrev={() => navigateInFilter(-1)}
          onNext={() => navigateInFilter(1)}
          onSkipToNextUnlabeled={skipToNextUnlabeled}
          showFill={showFill}
          setShowFill={setShowFill}
          showPostImagery={showPostEvent}
          setShowPostImagery={setShowPostImagery}
          hasPreImagery={hasPreImagery}
          hasPostImagery={hasPostImagery}
        />
      )}

      {isMapReady && features.length === 0 && (
        <div className={styles.emptyState}>
          No building footprints available for this image layer.
        </div>
      )}
    </div>
  );
};

export default BuildingValidation;
