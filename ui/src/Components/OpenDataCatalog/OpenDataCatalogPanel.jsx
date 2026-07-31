// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Open Data Catalog explorer — a side panel on the Create Image Layer form
// that browses Vantor/Maxar and Planet open disaster imagery and adds a
// scene's COG URL straight into the pre/post imagery inputs.
// See spec/features/open-data-catalog/.
//
// Layout: opens from the left (customNear) and reads left→right — a scene
// list on the left, a map on the right that shows footprints and previews
// the selected scene's imagery (via TiTiler) so you never scroll to preview.
import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import PropTypes from "prop-types";
import {
  Button,
  Checkbox,
  DrawerBody,
  DrawerHeader,
  DrawerHeaderTitle,
  Dropdown,
  MessageBar,
  MessageBarBody,
  Option,
  OverlayDrawer,
  Spinner,
  Tab,
  TabList,
  Text,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";

import {
  discoverEvents,
  fetchEventCatalog,
  bboxIntersects,
  bboxContains,
} from "./openDataCatalog";
import { isAzureMapsPlaceholder } from "../../util/azureMapsAuth";
import OpenDataCatalogMap from "./OpenDataCatalogMap";
import SceneListItem from "./SceneListItem";

const OpenDataCatalogPanel = ({
  isOpen,
  onDismiss,
  onAddScene,
  clipAoi,
  onClipAoiChange,
  preUrls,
  postUrls,
}) => {
  const [events, setEvents] = useState([]);
  const [eventKey, setEventKey] = useState(null);
  const [discovering, setDiscovering] = useState(false);
  const [discoverErrors, setDiscoverErrors] = useState([]);

  const [scenes, setScenes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState([]);
  const [loadError, setLoadError] = useState("");
  const [addError, setAddError] = useState("");

  const [sourceFilter, setSourceFilter] = useState("all");
  const [phaseFilter, setPhaseFilter] = useState("all");
  const [hoveredId, setHoveredId] = useState(null);
  const [selectedScene, setSelectedScene] = useState(null);

  // Server-side clip: drawing a box sets a single layer-level AOI ([w,s,e,n]
  // EPSG:4326). Imagery prep clips the pre/post mosaics to it — the add is
  // instant here (no client-side crop/upload). The AOI persists across scene
  // selection (it's a property of the layer, not a scene).
  const [clipMode, setClipMode] = useState(false);

  // Leaving draw mode when the previewed scene changes (the AOI itself stays).
  useEffect(() => {
    setClipMode(false);
  }, [selectedScene]);

  const handleClipDrawn = useCallback(
    (bbox) => {
      onClipAoiChange(bbox);
      setClipMode(false);
    },
    [onClipAoiChange]
  );

  const event = useMemo(
    () => events.find((e) => e.key === eventKey),
    [events, eventKey]
  );

  // Discover all available events when the panel first opens. Keyed on
  // `isOpen` ONLY — deliberately not on `events.length`/`discovering`, so
  // flipping those bits of state mid-fetch doesn't tear down and cancel the
  // in-flight discovery (which would leave the spinner stuck forever).
  useEffect(() => {
    if (!isOpen || events.length > 0) return undefined;
    let cancelled = false;
    setDiscovering(true);
    setDiscoverErrors([]);
    discoverEvents()
      .then((result) => {
        if (cancelled) return;
        setEvents(result.events);
        setDiscoverErrors(result.errors);
        if (result.events.length > 0) setEventKey(result.events[0].key);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err.message || "Failed to discover events.");
      })
      .finally(() => {
        if (!cancelled) setDiscovering(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  // Load the catalog whenever the selected event changes.
  useEffect(() => {
    if (!isOpen || !event) return undefined;
    let cancelled = false;
    setLoading(true);
    setScenes([]);
    setErrors([]);
    setLoadError("");
    setAddError("");
    setSelectedScene(null);
    setHoveredId(null);

    fetchEventCatalog(event)
      .then((result) => {
        if (cancelled) return;
        setScenes(result.scenes);
        setErrors(result.errors);
        if (result.scenes.length === 0 && result.errors.length > 0) {
          setLoadError(
            "Could not load any open data for this event. See the source errors below."
          );
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(err.message || "Failed to load the open data catalog.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [isOpen, event]);

  // Restrict to scenes whose footprint overlaps the drawn clip AOI. A scene
  // that doesn't overlap the layer-level AOI contributes nothing to the
  // clipped mosaic, so hide it (default on whenever an AOI is set).
  const [aoiOnly, setAoiOnly] = useState(true);
  const aoiScenes = useMemo(() => {
    if (!clipAoi || !aoiOnly) return scenes;
    return scenes.filter((s) => bboxIntersects(s.bbox, clipAoi));
  }, [scenes, clipAoi, aoiOnly]);

  const counts = useMemo(() => {
    const c = { Vantor: 0, Planet: 0, pre: 0, post: 0 };
    for (const s of aoiScenes) {
      c[s.source] = (c[s.source] || 0) + 1;
      if (s.phase) c[s.phase] += 1;
    }
    return c;
  }, [aoiScenes]);

  const filtered = useMemo(
    () =>
      aoiScenes.filter(
        (s) =>
          (sourceFilter === "all" || s.source === sourceFilter) &&
          (phaseFilter === "all" || s.phase === phaseFilter)
      ),
    [aoiScenes, sourceFilter, phaseFilter]
  );

  const preSet = useMemo(() => new Set(preUrls || []), [preUrls]);
  const postSet = useMemo(() => new Set(postUrls || []), [postUrls]);

  const handleAdd = useCallback(
    (scene, field) => {
      const result = onAddScene(scene, field);
      setAddError(result && result.ok ? "" : (result && result.error) || "");
    },
    [onAddScene]
  );

  const activeId = hoveredId || selectedScene?.uid || null;

  // When a scene is selected (notably by clicking a footprint on the map),
  // scroll the matching list row into view so the highlighted/expanded item
  // is visible without hunting for it.
  const listRef = useRef(null);
  useEffect(() => {
    if (!selectedScene || !listRef.current) return;
    const uid = selectedScene.uid || selectedScene.id;
    const el = listRef.current.querySelector(
      `[data-scene-uid="${window.CSS?.escape ? window.CSS.escape(uid) : uid}"]`
    );
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedScene]);

  return (
    <OverlayDrawer
      open={isOpen}
      position="start"
      size="full"
      style={{ width: "min(1120px, 94vw)" }}
      onOpenChange={(_, data) => {
        if (!data.open) onDismiss();
      }}
    >
      <DrawerHeader>
        <DrawerHeaderTitle
          action={
            <Button
              appearance="subtle"
              icon={<FluentIcon name="Cancel" />}
              aria-label="Close Open Data Catalog"
              onClick={onDismiss}
            />
          }
        >
          Open Data Catalog
        </DrawerHeaderTitle>
      </DrawerHeader>
      <DrawerBody style={{ padding: 0, overflow: "hidden" }}>
      <div className="d-flex flex-column" style={{ height: "100%", minHeight: 0 }}>
        {/* Header controls (full width) */}
        <div className="p-3 pb-2" style={{ flex: "none" }}>
          <Text size={200} style={{ color: "#616161" }} block className="mb-2">
            Browse open disaster imagery from the Vantor/Maxar and Planet Open
            Data Programs, then add a scene directly to your pre- or post-event
            imagery. Imagery is licensed CC&nbsp;BY-NC&nbsp;4.0.
          </Text>

          <div className="d-flex flex-wrap align-items-end" style={{ gap: "16px" }}>
            <Dropdown
              placeholder={discovering ? "Discovering events…" : "Select an event"}
              aria-label="Disaster event"
              selectedOptions={eventKey ? [eventKey] : []}
              value={event?.name || ""}
              disabled={discovering}
              onOptionSelect={(_, data) => setEventKey(data.optionValue)}
              style={{ minWidth: 320 }}
            >
              {events.map((item) => (
                <Option key={item.key} value={item.key}>
                  {`${item.name}${
                    item.sources.vantor && item.sources.planet
                      ? " · Vantor + Planet"
                      : item.sources.vantor
                      ? " · Vantor"
                      : " · Planet"
                  }`}
                </Option>
              ))}
            </Dropdown>
            <TabList
              selectedValue={sourceFilter}
              onTabSelect={(_, data) => setSourceFilter(data.value)}
            >
              <Tab value="all">All ({aoiScenes.length})</Tab>
              <Tab value="Vantor">Vantor ({counts.Vantor})</Tab>
              <Tab value="Planet">Planet ({counts.Planet})</Tab>
            </TabList>
            <TabList
              selectedValue={phaseFilter}
              onTabSelect={(_, data) => setPhaseFilter(data.value)}
            >
              <Tab value="all">All phases</Tab>
              <Tab value="pre">Pre ({counts.pre})</Tab>
              <Tab value="post">Post ({counts.post})</Tab>
            </TabList>
          </div>

          {/* When a clip AOI is set, offer to restrict the catalog to scenes
              that actually overlap it — so pre/post picks share the AOI. */}
          {clipAoi && (
            <Checkbox
              className="mt-2"
              label="Only scenes overlapping the clip area (keeps pre/post on the same AOI)"
              checked={aoiOnly}
              onChange={(_, data) => setAoiOnly(!!data.checked)}
            />
          )}
        </div>

        {addError && (
          <MessageBar intent="warning" className="mx-3 mb-2">
            <MessageBarBody>{addError}</MessageBarBody>
          </MessageBar>
        )}
        {loadError && (
          <MessageBar intent="error" className="mx-3 mb-2">
            <MessageBarBody>{loadError}</MessageBarBody>
          </MessageBar>
        )}
        {discoverErrors.map((e) => (
          <MessageBar
            key={`disc-${e.source}`}
            intent="warning"
            className="mx-3 mb-2"
          >
            <MessageBarBody>
              Could not list {e.source} events: {e.message}
            </MessageBarBody>
          </MessageBar>
        ))}
        {errors.map((e) => (
          <MessageBar
            key={e.source}
            intent="warning"
            className="mx-3 mb-2"
          >
            <MessageBarBody>
              {e.source} imagery could not be loaded: {e.message}
            </MessageBarBody>
          </MessageBar>
        ))}

        {/* Body: list (left) + map (right) */}
        <div
          className="d-flex"
          style={{
            flex: 1,
            minHeight: "70vh",
            borderTop: "1px solid #e1e1e1",
          }}
        >
          {/* Scene list */}
          <div
            ref={listRef}
            style={{
              width: 380,
              flex: "none",
              overflowY: "auto",
              borderRight: "1px solid #e1e1e1",
            }}
          >
            {loading || discovering ? (
              <div className="p-4 d-flex justify-content-center">
                <Spinner
                  size="large"
                  label={discovering ? "Discovering events…" : "Loading imagery…"}
                />
              </div>
            ) : filtered.length === 0 ? (
              <Text block className="p-4" style={{ color: "#616161" }}>
                {scenes.length === 0
                  ? "No imagery available for this event."
                  : "No scenes match the current filters."}
              </Text>
            ) : (
              filtered.map((scene) => (
                <SceneListItem
                  key={scene.uid || scene.id}
                  scene={scene}
                  isHovered={hoveredId === (scene.uid || scene.id)}
                  isSelected={selectedScene?.uid === (scene.uid || scene.id)}
                  onHover={setHoveredId}
                  onSelect={setSelectedScene}
                  onAdd={handleAdd}
                  addedPre={scene.cogUrl ? preSet.has(scene.cogUrl) : false}
                  addedPost={scene.cogUrl ? postSet.has(scene.cogUrl) : false}
                  coversAoi={clipAoi ? bboxContains(scene.bbox, clipAoi) : false}
                />
              ))
            )}
          </div>

          {/* Map / preview */}
          <div style={{ flex: 1, minWidth: 0, position: "relative" }}>
            {isOpen && (
              <OpenDataCatalogMap
                scenes={filtered}
                activeId={activeId}
                previewScene={selectedScene}
                clipMode={clipMode}
                clipAoi={clipAoi}
                onHover={setHoveredId}
                onSelect={setSelectedScene}
                onClipDrawn={handleClipDrawn}
              />
            )}

            {/* Server-side clip AOI toolbar */}
            {((selectedScene && selectedScene.cogUrl) || clipAoi) && (
              <div
                style={{
                  position: "absolute",
                  top: 8,
                  left: 8,
                  right: 8,
                  display: "flex",
                  flexWrap: "wrap",
                  gap: 6,
                  alignItems: "center",
                }}
              >
                {clipMode ? (
                  <span
                    style={{
                      background: "rgba(255,255,255,0.95)",
                      border: "1px solid #e1e1e1",
                      borderRadius: 4,
                      padding: "6px 10px",
                      fontSize: 12,
                      display: "inline-flex",
                      gap: 8,
                      alignItems: "center",
                    }}
                  >
                    Drag a box to set the clip area.
                    <Button
                      size="small"
                      onClick={() => setClipMode(false)}
                    >
                      Cancel
                    </Button>
                  </span>
                ) : clipAoi ? (
                  <span
                    style={{
                      background: "rgba(255,255,255,0.95)",
                      border: "1px solid #e1e1e1",
                      borderRadius: 4,
                      padding: "6px 10px",
                      fontSize: 12,
                      display: "inline-flex",
                      gap: 6,
                      alignItems: "center",
                      flexWrap: "wrap",
                    }}
                  >
                    Clip area set — imagery is clipped to it during processing.
                    <Button
                      size="small"
                      disabled={!selectedScene?.cogUrl}
                      onClick={() => setClipMode(true)}
                    >
                      Redraw
                    </Button>
                    <Button
                      size="small"
                      onClick={() => onClipAoiChange(null)}
                    >
                      Clear
                    </Button>
                  </span>
                ) : (
                  <Button
                    icon={<FluentIcon name="Crop" />}
                    onClick={() => setClipMode(true)}
                    style={{ background: "#fff" }}
                  >
                    Set clip area
                  </Button>
                )}
              </div>
            )}
            <div
              style={{
                position: "absolute",
                left: 8,
                bottom: 8,
                right: 8,
                pointerEvents: "none",
              }}
            >
              {selectedScene ? (
                <span
                  style={{
                    display: "inline-block",
                    background: "rgba(255,255,255,0.9)",
                    border: "1px solid #e1e1e1",
                    borderRadius: 4,
                    padding: "4px 8px",
                    fontSize: 12,
                  }}
                >
                  Previewing: {selectedScene.place || selectedScene.title || selectedScene.id}
                </span>
              ) : (
                <span
                  style={{
                    display: "inline-block",
                    background: "rgba(255,255,255,0.9)",
                    border: "1px solid #e1e1e1",
                    borderRadius: 4,
                    padding: "4px 8px",
                    fontSize: 12,
                    color: "#616161",
                  }}
                >
                  Select a scene to preview its imagery here.
                </span>
              )}
              {isAzureMapsPlaceholder && (
                <span
                  style={{
                    display: "block",
                    marginTop: 4,
                    background: "rgba(255,255,255,0.9)",
                    border: "1px solid #e1e1e1",
                    borderRadius: 4,
                    padding: "2px 8px",
                    fontSize: 11,
                    color: "#8a6d00",
                    width: "fit-content",
                  }}
                >
                  Satellite basemap disabled (no Azure Maps key) — footprints and
                  scene previews still work.
                </span>
              )}
            </div>
          </div>
        </div>
      </div>
      </DrawerBody>
    </OverlayDrawer>
  );
};

OpenDataCatalogPanel.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  onDismiss: PropTypes.func.isRequired,
  onAddScene: PropTypes.func.isRequired,
  clipAoi: PropTypes.array,
  onClipAoiChange: PropTypes.func.isRequired,
  preUrls: PropTypes.array,
  postUrls: PropTypes.array,
};

export default OpenDataCatalogPanel;
