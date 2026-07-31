// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Azure Maps footprint view for the Open Data Catalog explorer. Reuses the
// app's global `window.atlas` map stack (loaded in index.html) — no new
// dependency. Footprints are colored by source and stay in sync with the
// list's hover/selection state.
import { useEffect, useRef, useCallback, useState } from "react";
import PropTypes from "prop-types";
import { Spinner } from "@fluentui/react-components";

import {
  getAzureMapsAuthOptions,
  isAzureMapsPlaceholder,
} from "../../util/azureMapsAuth";
import { SOURCE_COLORS, titilerTileUrl } from "./openDataCatalog";

// atlas.Map hides the underlying Mapbox-GL fork; reach it (for getLayer().source)
// via this duck-typed scan. Mirrors findGlMap in InteractiveLabeler.jsx.
// Normal footprint fill opacity (active scene emphasized). Kept as a constant
// so the preview effect can restore it after transparently disabling the fill.
const FILL_OPACITY_EXPR = ["case", ["get", "_active"], 0.35, 0.12];

function findGlMap(atlasMap) {
  if (!atlasMap) return null;
  const direct = [atlasMap.map, atlasMap._map, atlasMap.gl, atlasMap._gl];
  for (const c of direct) {
    if (c && typeof c.getLayer === "function") return c;
  }
  for (const k of Object.keys(atlasMap)) {
    const v = atlasMap[k];
    if (v && typeof v === "object" && typeof v.getLayer === "function") return v;
  }
  return null;
}

// Build a GeoJSON FeatureCollection from normalized scenes, tagging each
// feature with the id + a per-source color + an "active" flag the layer
// style expressions read (so hover/select highlight is data-driven).
function scenesToFeatureCollection(scenes, activeId) {
  const features = [];
  for (const scene of scenes) {
    if (!scene.geometry) continue;
    const uid = scene.uid || scene.id;
    features.push({
      type: "Feature",
      geometry: scene.geometry,
      properties: {
        sceneId: uid,
        _color: SOURCE_COLORS[scene.source] || "#616161",
        _active: uid === activeId,
      },
    });
  }
  return { type: "FeatureCollection", features };
}

const OpenDataCatalogMap = ({
  scenes,
  activeId,
  previewScene,
  clipMode,
  clipAoi,
  onHover,
  onSelect,
  onClipDrawn,
  center,
}) => {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const dataSourceRef = useRef(null);
  const previewLayerRef = useRef(null);
  const fillLayerRef = useRef(null);
  const clipSourceRef = useRef(null);
  const drawingRef = useRef(null);
  // Preview tile-loading indicator: the GL source id of the current COG
  // preview layer, and whether its tiles are still loading.
  const previewSourceIdRef = useRef(null);
  const [tilesLoading, setTilesLoading] = useState(false);
  const readyRef = useRef(false);

  // Latest props addressable from the (once-bound) map events / camera fit
  // without rebinding. Updated in an effect (not during render) so the
  // rules-of-hooks ref guidance is respected.
  const scenesRef = useRef(scenes);
  const activeIdRef = useRef(activeId);
  const clipAoiRef = useRef(clipAoi);
  const handlersRef = useRef({ onHover, onSelect, onClipDrawn });
  useEffect(() => {
    scenesRef.current = scenes;
    activeIdRef.current = activeId;
    clipAoiRef.current = clipAoi;
    handlersRef.current = { onHover, onSelect, onClipDrawn };
  });

  // Draw (or clear) the persistent clip-AOI rectangle from a [w,s,e,n] bbox.
  const renderClipAoi = useCallback((bbox) => {
    const ds = clipSourceRef.current;
    if (!ds) return;
    ds.clear();
    if (bbox && bbox.length === 4) {
      const [w, s, e, n] = bbox;
      ds.add({
        type: "Feature",
        geometry: {
          type: "Polygon",
          coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
        },
      });
    }
  }, []);

  // Push scene data into the datasource and fit the camera to the footprints.
  const syncData = useCallback(() => {
    const ds = dataSourceRef.current;
    if (!ds || !readyRef.current) return;
    const fc = scenesToFeatureCollection(scenesRef.current, activeIdRef.current);
    ds.clear();
    ds.add(fc);
    if (fc.features.length > 0 && mapRef.current) {
      const bounds = window.atlas.data.BoundingBox.fromData(fc);
      mapRef.current.setCamera({
        bounds,
        padding: 40,
        type: "fly",
        duration: 500,
      });
    }
  }, []);

  // Create the map once.
  useEffect(() => {
    if (!window.atlas || !containerRef.current) return undefined;

    const map = new window.atlas.Map(containerRef.current, {
      center: center || [0, 0],
      zoom: center ? 6 : 2,
      maxPitch: 0,
      pitch: 0,
      style: isAzureMapsPlaceholder ? "blank" : "satellite",
      language: "en-US",
      authOptions: getAzureMapsAuthOptions(),
    });
    mapRef.current = map;

    map.events.add("ready", () => {
      map.setUserInteraction({
        dragRotateInteraction: false,
        scrollZoomInteraction: true,
        pinchRotateInteraction: false,
      });
      map.controls.add(new window.atlas.control.ZoomControl(), {
        position: "bottom-left",
      });

      const dataSource = new window.atlas.source.DataSource();
      map.sources.add(dataSource);
      dataSourceRef.current = dataSource;

      const fillLayer = new window.atlas.layer.PolygonLayer(dataSource, "odcFill", {
        fillColor: ["get", "_color"],
        fillOpacity: FILL_OPACITY_EXPR,
      });
      fillLayerRef.current = fillLayer;
      const lineLayer = new window.atlas.layer.LineLayer(dataSource, "odcLine", {
        strokeColor: ["case", ["get", "_active"], "#ffffff", ["get", "_color"]],
        strokeWidth: ["case", ["get", "_active"], 3, 1.7],
      });
      map.layers.add([fillLayer, lineLayer]);

      // Persistent clip-AOI rectangle (drawn above footprints/preview).
      const clipSource = new window.atlas.source.DataSource();
      map.sources.add(clipSource);
      clipSourceRef.current = clipSource;
      map.layers.add(
        new window.atlas.layer.LineLayer(clipSource, "odcClip", {
          strokeColor: "#d83b01",
          strokeWidth: 3,
          strokeDashArray: [3, 2],
        })
      );

      map.events.add("mousemove", fillLayer, (e) => {
        const shapeProps = e.shapes?.[0]?.getProperties?.();
        const id = shapeProps?.sceneId;
        map.getCanvasContainer().style.cursor = id ? "pointer" : "";
        if (id) handlersRef.current.onHover(id);
      });
      map.events.add("mouseleave", fillLayer, () => {
        map.getCanvasContainer().style.cursor = "";
        handlersRef.current.onHover(null);
      });
      map.events.add("click", fillLayer, (e) => {
        const shapeProps = e.shapes?.[0]?.getProperties?.();
        const id = shapeProps?.sceneId;
        if (!id) return;
        const scene = (scenesRef.current || []).find(
          (s) => (s.uid || s.id) === id
        );
        if (scene) handlersRef.current.onSelect(scene);
      });

      // Clear the preview loading indicator once the COG preview source has
      // finished loading its tiles for the current view.
      map.events.add("sourcedata", (e) => {
        if (
          e &&
          e.isSourceLoaded &&
          e.sourceId &&
          e.sourceId === previewSourceIdRef.current
        ) {
          setTilesLoading(false);
        }
      });

      readyRef.current = true;
      syncData();
      renderClipAoi(clipAoiRef.current);
    });

    return () => {
      readyRef.current = false;
      dataSourceRef.current = null;
      if (drawingRef.current) {
        drawingRef.current.dispose?.();
        drawingRef.current = null;
      }
      if (mapRef.current) {
        mapRef.current.dispose();
        mapRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Rectangle clip-box drawing. When clipMode turns on we put the drawing
  // manager into draw-rectangle mode; on completion we hand the box's
  // EPSG:4326 bbox ([w,s,e,n]) back to the panel and idle the tool.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current || !window.atlas?.drawing) return;

    if (clipMode) {
      if (!drawingRef.current) {
        const dm = new window.atlas.drawing.DrawingManager(map, {});
        map.events.add("drawingcomplete", dm, (shape) => {
          try {
            const geo =
              typeof shape.toJson === "function" ? shape.toJson() : shape;
            const b = window.atlas.data.BoundingBox.fromData(geo);
            handlersRef.current.onClipDrawn?.([b[0], b[1], b[2], b[3]]);
          } catch (err) {
            console.warn("Failed to read clip bbox:", err);
          }
          dm.setOptions({ mode: "idle" });
        });
        drawingRef.current = dm;
      }
      drawingRef.current.getSource().clear();
      drawingRef.current.setOptions({ mode: "draw-rectangle" });
    } else if (drawingRef.current) {
      drawingRef.current.setOptions({ mode: "idle" });
      drawingRef.current.getSource().clear();
    }
  }, [clipMode]);

  // Re-sync features (and refit) whenever the scene set changes.
  useEffect(() => {
    syncData();
  }, [scenes, syncData]);

  // Update only the active-highlight flag on hover/select without refitting.
  useEffect(() => {
    const ds = dataSourceRef.current;
    if (!ds || !readyRef.current) return;
    for (const shape of ds.getShapes()) {
      const shapeProps = shape.getProperties();
      const active = shapeProps.sceneId === activeId;
      if (shapeProps._active !== active) {
        shape.setProperties({ ...shapeProps, _active: active });
      }
    }
  }, [activeId]);

  // Render the persistent clip-AOI rectangle whenever it changes.
  useEffect(() => {
    if (!readyRef.current) return;
    renderClipAoi(clipAoi);
  }, [clipAoi, renderClipAoi]);

  // Preview the selected scene's actual imagery by streaming its COG through
  // TiTiler as a tile layer (no Azure Maps subscription needed), inserted
  // below the footprint outlines so they stay visible on top.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;

    if (previewLayerRef.current) {
      map.layers.remove(previewLayerRef.current);
      previewLayerRef.current = null;
    }
    previewSourceIdRef.current = null;

    const tileUrl = titilerTileUrl(previewScene?.cogUrl);

    // While previewing imagery, make the footprint fill fully transparent
    // (not hidden) so its colored tint doesn't wash out the scene BUT the
    // footprints stay clickable — the user can click another footprint on the
    // map to switch scenes. Outlines (the line layer) remain visible.
    if (fillLayerRef.current) {
      fillLayerRef.current.setOptions({
        fillOpacity: tileUrl ? 0 : FILL_OPACITY_EXPR,
      });
    }

    if (!tileUrl) {
      setTilesLoading(false);
      return;
    }

    const layer = new window.atlas.layer.TileLayer(
      {
        tileUrl,
        opacity: 1,
        minSourceZoom: 1,
        maxSourceZoom: 22,
        bounds: previewScene.bbox,
      },
      "odcPreview"
    );
    // Insert beneath the footprint fill so outlines remain on top.
    map.layers.add(layer, "odcFill");
    previewLayerRef.current = layer;

    // Track this preview's GL source id so the "sourcedata" listener knows
    // when ITS tiles have loaded, and show the loading indicator meanwhile.
    setTilesLoading(true);
    const glMap = findGlMap(map);
    previewSourceIdRef.current =
      glMap?.getLayer?.("odcPreview")?.source ?? null;
    // Fallback so the spinner never sticks if the source id can't be resolved
    // or tiles error out silently.
    const sceneUid = previewScene.uid || previewScene.id;
    const timer = setTimeout(() => {
      if ((previewScene.uid || previewScene.id) === sceneUid) {
        setTilesLoading(false);
      }
    }, 15000);

    if (previewScene.bbox) {
      map.setCamera({
        bounds: previewScene.bbox,
        padding: 60,
        type: "fly",
        duration: 600,
      });
    }

    return () => clearTimeout(timer);
  }, [previewScene]);

  return (
    <div style={{ position: "relative", width: "100%", height: "100%", minHeight: 240 }}>
      <div
        ref={containerRef}
        style={{ width: "100%", height: "100%", background: "#f5f5f5" }}
      />
      {tilesLoading && (
        <div
          style={{
            position: "absolute",
            top: 8,
            left: "50%",
            transform: "translateX(-50%)",
            display: "flex",
            alignItems: "center",
            gap: 8,
            background: "rgba(255,255,255,0.95)",
            border: "1px solid #e1e1e1",
            borderRadius: 999,
            padding: "4px 12px",
            fontSize: 12,
            boxShadow: "0 2px 6px rgba(0,0,0,0.12)",
            zIndex: 5,
            pointerEvents: "none",
          }}
        >
          <Spinner size="tiny" /> Loading imagery…
        </div>
      )}
    </div>
  );
};

OpenDataCatalogMap.propTypes = {
  scenes: PropTypes.array.isRequired,
  activeId: PropTypes.string,
  previewScene: PropTypes.object,
  clipMode: PropTypes.bool,
  clipAoi: PropTypes.array,
  onHover: PropTypes.func.isRequired,
  onSelect: PropTypes.func.isRequired,
  onClipDrawn: PropTypes.func,
  center: PropTypes.array,
};

export default OpenDataCatalogMap;
