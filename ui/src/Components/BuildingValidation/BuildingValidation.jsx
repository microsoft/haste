// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useEffect, useMemo, useRef, useState, useContext } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { apiGet, apiPut } from "../../util/api";
import { getAzureMapsAuthOptions, isAzureMapsPlaceholder } from "../../util/azureMapsAuth";
import { AppContext } from "../../AppContext.jsx";
import BuildingValidationRightPanel from "./BuildingValidationRightPanel.jsx";
import { loadImagery } from "../LabelingTool/LabelingToolHelper.js";

const LABEL_COLORS = {
  Damaged: "#e74c3c",
  NotDamaged: "#27ae60",
  Unknown: "#5a6268",
  unlabeled: "#3498db",
};

// Filter values used by the right-panel dropdown and the map dim logic.
// 'all' means no filter; 'unlabeled' means buildings with no label set yet;
// the three class names match the values stored on labels[id].label.
export const FILTER_VALUES = ["all", "unlabeled", "Damaged", "NotDamaged", "Unknown"];

function buildingMatchesFilter(feature, labels, filter) {
  if (filter === "all") return true;
  const lbl = labels[feature.properties?.id]?.label;
  if (filter === "unlabeled") return !lbl;
  return lbl === filter;
}

const BuildingValidation = () => {
  const { projectId, imageLayerId } = useParams();
  const navigate = useNavigate();
  const { setIsLoading, setDialog, setAppHeaderRightButtons } = useContext(AppContext);

  const mapContainerRef = useRef(null);
  const mapRef = useRef(null);
  const datasourceRef = useRef(null);
  const preImageryRef = useRef(null);
  const postImageryRef = useRef(null);
  const fillLayerRef = useRef(null);

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
        await createMap();
        setIsMapReady(true);
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
  }, []);

  async function createMap() {
    // Load imagery tile URLs (reuse labeling tool endpoint); may not exist if no labels yet
    let layerData = null;
    try {
      layerData = await apiGet(
        `GetLayerLabelingToolData?projectId=${projectId}&imageLayerId=${imageLayerId}`
      );
    } catch {
      // No label project yet — imagery won't be shown, validation still works
    }

    // Load building footprints as GeoJSON (random sample of 200)
    const footprintsGeoJSON = await apiGet(
      `GetBuildingFootprintsGeoJSON?projectId=${projectId}&imageLayerId=${imageLayerId}&sample=200`
    );

    // Load any existing validation labels
    const validationData = await apiGet(
      `GetBuildingValidation?projectId=${projectId}&imageLayerId=${imageLayerId}`
    );

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
      }
      if (layerData?.imagery?.postEventTileUrl) {
        loadImagery(
          layerData.imagery.postEventTileUrl,
          map,
          postImageryRef,
          "postEventImageryLayer",
          true
        );
      }

      // Create datasource for building polygons
      const datasource = new window.atlas.source.DataSource();
      map.sources.add(datasource);
      datasourceRef.current = datasource;

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

  // Toggle post-event imagery layer so the user can compare the
  // post-event view against the basemap satellite underneath.
  useEffect(() => {
    if (postImageryRef.current) {
      postImageryRef.current.setOptions({ visible: showPostImagery });
    }
  }, [showPostImagery, isMapReady]);

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [labels, selectedIndex, features, filter]);

  // When the filter changes such that the current selection no longer
  // matches, jump to the first building that does — so the user isn't
  // looking at a building that's hidden under the dim layer.
  useEffect(() => {
    if (filteredIndices.length === 0) return;
    if (!filteredIndices.includes(selectedIndex)) {
      setSelectedIndex(filteredIndices[0]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

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
      const lng = coords.reduce((s, c) => s + c[0], 0) / coords.length;
      const lat = coords.reduce((s, c) => s + c[1], 0) / coords.length;
      return [lng, lat];
    } catch {
      return null;
    }
  }

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

  // Keyboard shortcuts: 1 = Damaged, 2 = Not Damaged, 3 = Unknown
  useEffect(() => {
    const keyMap = { "1": "Damaged", "2": "NotDamaged", "3": "Unknown" };
    function onKeyDown(e) {
      // Ignore when focus is in an input/textarea
      if (["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName)) return;
      const labelValue = keyMap[e.key];
      if (labelValue) handleLabel(labelValue);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [features, selectedIndex]);

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
    } catch (e) {
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
    <div style={{ display: "flex", flexGrow: 1, position: "relative", overflow: "hidden" }}>
      {/* Back button */}
      <button
        onClick={() => navigate(`/project/${projectId}`)}
        style={{
          position: "absolute",
          top: 12,
          left: 12,
          zIndex: 1000,
          background: "rgba(255,255,255,0.9)",
          border: "1px solid #ccc",
          borderRadius: 4,
          padding: "6px 14px",
          cursor: "pointer",
          fontWeight: 500,
        }}
      >
        ← Back to Project
      </button>

      {/* Map container */}
      <div ref={mapContainerRef} id="validationMap" style={{ flexGrow: 1 }} />

      {/* Right panel */}
      {isMapReady && features.length > 0 && (
        <BuildingValidationRightPanel
          features={features}
          labels={labels}
          selectedIndex={selectedIndex}
          setSelectedIndex={setSelectedIndex}
          onLabel={handleLabel}
          onSave={handleSave}
          onDownload={handleDownload}
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
          showPostImagery={showPostImagery}
          setShowPostImagery={setShowPostImagery}
          hasPostImagery={!!postImageryRef.current}
        />
      )}

      {isMapReady && features.length === 0 && (
        <div
          style={{
            position: "absolute",
            top: 70,
            right: 16,
            background: "rgba(255,255,255,0.95)",
            padding: "16px 20px",
            borderRadius: 6,
            zIndex: 1000,
          }}
        >
          No building footprints available for this image layer.
        </div>
      )}
    </div>
  );
};

export default BuildingValidation;
