// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useEffect, useRef, useState, useContext } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { apiGet, apiPut } from "../../util/api";
import { getAzureMapsAuthOptions, isAzureMapsPlaceholder } from "../../util/azureMapsAuth";
import { AppContext } from "../../AppContext.jsx";
import BuildingValidationRightPanel from "./BuildingValidationRightPanel.jsx";
import { loadImagery } from "../LabelingTool/LabelingToolHelper.js";

const LABEL_COLORS = {
  Damaged: "#e74c3c",
  NotDamaged: "#27ae60",
  Unknown: "#7f8c8d",
  unlabeled: "#3498db",
};

const BuildingValidation = () => {
  const { projectId, imageLayerId } = useParams();
  const navigate = useNavigate();
  const { setIsLoading, setDialog, setAppHeaderRightButtons } = useContext(AppContext);

  const mapContainerRef = useRef(null);
  const mapRef = useRef(null);
  const datasourceRef = useRef(null);
  const preImageryRef = useRef(null);
  const postImageryRef = useRef(null);

  const [isMapReady, setIsMapReady] = useState(false);
  const [features, setFeatures] = useState([]);
  const [labels, setLabels] = useState({});
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [isSaving, setIsSaving] = useState(false);

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

        // Polygon fill layer
        map.layers.add(
          new window.atlas.layer.PolygonLayer(datasource, "buildingFill", {
            fillColor: [
              "case",
              ["==", ["get", "_label"], "Damaged"], LABEL_COLORS.Damaged,
              ["==", ["get", "_label"], "NotDamaged"], LABEL_COLORS.NotDamaged,
              ["==", ["get", "_label"], "Unknown"], LABEL_COLORS.Unknown,
              LABEL_COLORS.unlabeled,
            ],
            fillOpacity: 0.5,
          })
        );

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

        // Click handler: select building by clicking on map
        map.events.add("click", "buildingFill", (e) => {
          if (e.shapes && e.shapes.length > 0) {
            const clickedId = e.shapes[0].getProperties().id;
            const idx = featuresArr.findIndex((f) => f.properties?.id === clickedId);
            if (idx >= 0) {
              setSelectedIndex(idx);
            }
          }
        });
        map.getCanvasContainer().style.cursor = "pointer";

        // Fit map to footprints bounding box
        const bounds = window.atlas.data.BoundingBox.fromData(footprintsGeoJSON);
        map.setCamera({ bounds, padding: 40, duration: 1500 });
      }
    });

    mapRef.current = map;
  }

  // Update polygon properties when labels or selectedIndex change
  useEffect(() => {
    if (!datasourceRef.current || features.length === 0) return;

    const updatedFeatures = features.map((f, idx) => ({
      ...f,
      properties: {
        ...f.properties,
        _label: labels[f.properties?.id]?.label || null,
        _selected: idx === selectedIndex,
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
  }, [labels, selectedIndex, features]);

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
    setLabels((prev) => ({
      ...prev,
      [buildingId]: {
        id: buildingId,
        label: labelValue,
        updatedAt: new Date().toISOString(),
      },
    }));
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
