// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useEffect, useRef, useState, useContext } from "react";
import {
  loadImagery,
  parsePrimaryClasses,
  updateDrawingLayerStyles,
  createShape,
  loadStudyArea,
} from "./LabelingToolHelper.js";
import { getAzureMapsAuthOptions, isAzureMapsPlaceholder } from "../../util/azureMapsAuth";
import { useParams } from "react-router-dom";
import LabelingToolLeftPanel from "./LabelingToolLeftPanel.jsx";
import LabelingToolRightPanel from "./LabelingToolRightPanel.jsx";
import { setGuidedTourState, initGuidedTourState } from "../GuidedTourHelper.js";
import PropType from "prop-types";
import { AppContext } from "../../AppContext.jsx";
import { useDrawingUndoRedo } from "./UndoRedo.jsx";
import { splitShape } from "./SplitShape.jsx";
import { waitForMapReady } from "../InteractiveLabeler/interactiveLabelerLoading.js";
import {
  getWorkspaceCameraOptions,
  getWorkspaceBounds,
  waitForMapIdle,
} from "./labelingToolLoading.js";
import "../../assets/css/drawingToolbar.css";

const LabelingTool = ({
  setModalComponent,
  workspace,
  signal,
  onLoadStep,
  onReady,
  onError,
}) => {
  const { projectId, imageLayerId } = useParams();

  const {
    setDialog,
    setIsLoading,
    initCurrentTour,
    setAppHeaderRightButtons,
    appParams,
  } = useContext(AppContext);

  const mapContainerRef = useRef(null);
  const mapRef = useRef(null);
  const [drawingManager, setDrawingManager] = useState(null);
  const [selectedPrimaryClass, setSelectedPrimaryClass] = useState(0);
  const primaryClassesRef = useRef([]);
  const preImageryRef = useRef(null);
  const postImageryRef = useRef(null);
  const labelingToolDataRef = useRef([]);
  const [primaryClasses, setPrimaryClasses] = useState([]);
  const [drawingCount, setDrawingCount] = useState(0);
  const [isMapReady, setIsMapReady] = useState(false);
  const [selectedShape, setSelectedShape] = useState(null);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [eventTypes, setEventTypes] = useState([]);
  const [imageLayer, setImageLayer] = useState(null);
  const { undo, redo } = useDrawingUndoRedo(drawingManager, mapRef);

  useEffect(() => {
    let active = true;
    const initializeMap = async () => {
      try {
        signal?.throwIfAborted();
        if (!window.atlas) throw new Error("Azure Maps is unavailable.");
        // eslint-disable-next-line react-hooks/immutability
        await createMap(signal);
        if (!active) return;
        setIsMapReady(true);
        onReady();
      } catch (error) {
        if (!active || error.name === "AbortError") return;
        mapRef.current?.dispose();
        mapRef.current = null;
        setDrawingManager(null);
        setIsMapReady(false);
        onError("The labeling map could not be prepared.");
      }
    };

    initializeMap();

    //On component dismount
    return () => {
      active = false;
      if (mapRef.current) {
        mapRef.current.dispose();
        mapRef.current = null;
      }
      initCurrentTour(null);
      setAppHeaderRightButtons([]);
      setModalComponent(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!mapRef.current || !drawingManager) return;


    setDrawingCount(drawingManager.source.shapes.length);
    updateDrawingLayerStyles(drawingManager, primaryClassesRef.current);

    // Handler: drawingchanged
    const handleDrawingChanged = () => {
      const mode = drawingManager.getOptions().mode;
      if (mode === "draw-polygon") {
        createShape(drawingManager, selectedPrimaryClass, setDrawingCount);
        setHasUnsavedChanges(true);
      }
    };

    // Handler: drawingmodechanged
    const handleDrawingModeChanged = () => {
      setTimeout(() => {
        const mode = drawingManager.getOptions().mode;
        if (mode !== "edit-geometry") {
          setSelectedShape(null);
          setDrawingCount(drawingManager.source.shapes.length);
        }
      }, 50);
    };

    // Handler: drawingstarted
    const handleDrawingStarted = (e) => {
      const mode = drawingManager.getOptions().mode;
      if (mode === "edit-geometry") {
        setSelectedShape(e);
        setHasUnsavedChanges(true);
        setSelectedPrimaryClass(e.getProperties().primaryClass);
      }
    };

    // Handler: drawingerased
    const handleDrawingErased = () => {
      setDrawingCount(drawingManager.source.shapes.length);
      setHasUnsavedChanges(true);
      setTimeout(() => {
        drawingManager.setOptions({ mode: "erase-geometry" });
      }, 50);
    };

    // Handler: drawingcomplete
    const handleDrawingComplete = (e) => {

      if (drawingManager.getOptions().mode === "draw-line") {
        splitShape(drawingManager, e);
      }

      const properties = e.getProperties();
      if (!properties.primaryClass) {
        drawingManager.source.remove(e);
      }
      
    };

    // Add all the handlers
    const map = mapRef.current;
    map.events.add("drawingchanged", drawingManager, handleDrawingChanged);
    map.events.add("drawingmodechanged", drawingManager, handleDrawingModeChanged);
    map.events.add("drawingstarted", drawingManager, handleDrawingStarted);
    map.events.add("drawingerased", drawingManager, handleDrawingErased);
    map.events.add("drawingcomplete", drawingManager, handleDrawingComplete);

    // Handler cleanup
    return () => {
      initGuidedTourState("labelingToolGuide", appParams.guidedTourProperties);
      map.events.remove("drawingchanged", drawingManager, handleDrawingChanged);
      map.events.remove("drawingmodechanged", drawingManager, handleDrawingModeChanged);
      map.events.remove("drawingstarted", drawingManager, handleDrawingStarted);
      map.events.remove("drawingerased", drawingManager, handleDrawingErased);
      map.events.remove("drawingcomplete", drawingManager, handleDrawingComplete);
    };
  }, [
    appParams.guidedTourProperties,
    mapRef,
    drawingManager,
    selectedPrimaryClass
  ]);

  useEffect(() => {
    // Handler: keydown to update drawing count on escape key
    const handleKeyDown = (e) => {
      if (e.key === "Escape") {
        if (drawingManager) {
          setDrawingCount(drawingManager.source.shapes.length);
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [drawingManager]);


  async function createMap(abortSignal) {
    const labelProject = workspace.labelProject;
    labelingToolDataRef.current = labelProject;
    setEventTypes(workspace.eventTypes || []);
    setImageLayer(workspace.imageLayer || null);
    const workspaceBounds = getWorkspaceBounds(window.atlas, labelProject);
    const map = new window.atlas.Map(mapContainerRef.current, {
      preserveDrawingBuffer: true,
      maxPitch: 0,
      pitch: 0,
      style: isAzureMapsPlaceholder ? "blank" : "grayscale_light",
      language: "en-US",
      authOptions: getAzureMapsAuthOptions(),
      ...(workspaceBounds
        ? { bounds: workspaceBounds, padding: 24 }
        : { center: [0, 0], zoom: 3 }),
    });
    mapRef.current = map;
    let idlePromise = null;
    const idleController = new AbortController();
    const abortIdle = () => idleController.abort();
    abortSignal.addEventListener("abort", abortIdle, { once: true });

    try {
      await waitForMapReady(map, {
        signal: abortSignal,
        onReady: () => {
        idlePromise = waitForMapIdle(map, {
          signal: idleController.signal,
        });
        map.setUserInteraction({
          dragRotateInteraction: false,
          scrollZoomInteraction: true,
          pinchZoomInteraction: true,
          pinchRotateInteraction: false,
        });
        map.controls.add(new window.atlas.control.ZoomControl(), {
          position: "bottom-left",
        });

        loadImagery(
          labelProject.imagery?.preEventTileUrl || "",
          map,
          preImageryRef,
          "preEventImageryLayer",
          false,
          { allowFallback: !isAzureMapsPlaceholder }
        );
        loadImagery(
          labelProject.imagery?.postEventTileUrl || "",
          map,
          postImageryRef,
          "postEventImageryLayer",
          true,
          {
            allowFallback: !isAzureMapsPlaceholder,
            required: true,
          }
        );

        const drawingManagerTemp =
          new window.atlas.drawing.DrawingManager(map, {});
        const primaryClasses = workspace.primaryClasses || [];
        drawingManagerTemp.source.add(labelProject.labels || []);
        primaryClassesRef.current = parsePrimaryClasses(primaryClasses);
        setPrimaryClasses(primaryClassesRef.current);
        setSelectedPrimaryClass(primaryClassesRef.current[0]?.key || 0);
        loadStudyArea(map, labelProject);
        setDrawingManager(drawingManagerTemp);

        map.setCamera(getWorkspaceCameraOptions(workspaceBounds));

        },
      });
      onLoadStep(2);
      if (!idlePromise) throw new Error("Azure Maps did not become ready.");
      await idlePromise;
      initGuidedTourState(
        "labelingToolGuide",
        appParams.guidedTourProperties
      );
      initCurrentTour("labelingToolGuide");
      setAppHeaderRightButtons([
        {
          iconName: "help",
          title: "Help",
          id: "helpButton",
          onClick: () =>
            setGuidedTourState(
              false,
              initCurrentTour,
              "labelingToolGuide",
              appParams.guidedTourProperties
            ),
        },
      ]);
    } catch (error) {
      idleController.abort();
      await idlePromise?.catch(() => {});
      throw error;
    } finally {
      abortSignal.removeEventListener("abort", abortIdle);
    }
  }

  return (
    <>
      <div
        ref={mapContainerRef}
        id="map"
        className="labeling-tool-page d-flex flex-grow-1 p-0 m-0"
        data-map-ready={
          isMapReady && drawingManager !== null ? "true" : "false"
        }
      >
        {isMapReady && drawingManager !== null ? (

          <>

            <LabelingToolLeftPanel
              mapRef={mapRef}
              drawingCount={drawingCount}
              preImageryRef={preImageryRef}
              postImageryRef={postImageryRef}
              hasUnsavedChanges={hasUnsavedChanges}
              setDialog={setDialog}
              setIsLoading={setIsLoading}
              drawingManager={drawingManager}
              imageLayerId={imageLayerId}
              labelingToolDataRef={labelingToolDataRef}
              setHasUnsavedChanges={setHasUnsavedChanges}
              primaryClasses={primaryClasses}
            />

            <LabelingToolRightPanel
              primaryClasses={primaryClasses}
              selectedPrimaryClass={selectedPrimaryClass}
              setSelectedPrimaryClass={setSelectedPrimaryClass}
              drawingManager={drawingManager}
              setDrawingManager={setDrawingManager}
              setDialog={setDialog}
              labelingToolDataRef={labelingToolDataRef}
              setIsLoading={setIsLoading}
              setHasUnsavedChanges={setHasUnsavedChanges}
              hasUnsavedChanges={hasUnsavedChanges}
              setModalComponent={setModalComponent}
              projectId={projectId}
              drawingCount={drawingCount}
              setDrawingCount={setDrawingCount}
              selectedShape={selectedShape}
              imageLayerId={imageLayerId}
              imageLayer={imageLayer}
              eventTypes={eventTypes}
              undo={undo}
              redo={redo}
            />
          </>
        ) : null}
      </div>
    </>
  );
};

LabelingTool.propTypes = {
  setModalComponent: PropType.func.isRequired,
  workspace: PropType.shape({
    labelProject: PropType.object.isRequired,
    imageLayer: PropType.object.isRequired,
    eventTypes: PropType.array,
    primaryClasses: PropType.array,
  }).isRequired,
  signal: PropType.shape({
    aborted: PropType.bool,
    addEventListener: PropType.func,
    removeEventListener: PropType.func,
    throwIfAborted: PropType.func,
  }).isRequired,
  onLoadStep: PropType.func.isRequired,
  onReady: PropType.func.isRequired,
  onError: PropType.func.isRequired,
};

export default LabelingTool;
