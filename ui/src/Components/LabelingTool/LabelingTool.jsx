// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useEffect, useRef, useState, useContext } from "react";
import { apiGet } from "../../util/api";
import {
  loadImagery,
  parsePrimaryClasses,
  updateDrawingLayerStyles,
  createShape,
  loadStudyArea,
  centrateMap,
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
import "../../assets/css/drawingToolbar.css";

const LabelingTool = ({ setModalComponent }) => {
  LabelingTool.propTypes = {
    setModalComponent: PropType.func.isRequired,
  };

  const { projectId, imageLayerId } = useParams();

  const {
    setDialog,
    setIsLoading,
    initCurrentTour,
    setAppHeaderRightButtons,
    appParams,
  } = useContext(AppContext);

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
  const { undo, redo } = useDrawingUndoRedo(drawingManager, mapRef);

  useEffect(() => {
    const initializeMap = async () => {
      if (window.atlas) {
        setIsLoading(true);
        await createMap();
        setIsMapReady(true);
        setIsLoading(false);
      }
    };

    initializeMap();

    //On component dismount
    return () => {
      initCurrentTour(null);
      setAppHeaderRightButtons([]);
      setModalComponent(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!mapRef || !drawingManager) return;


    setDrawingCount(drawingManager.source.shapes.length);
    updateDrawingLayerStyles(drawingManager, primaryClassesRef.current);

    // Handler: drawingchanged
    const handleDrawingChanged = (e) => {
      const mode = drawingManager.getOptions().mode;
      if (mode === "draw-polygon") {
        createShape(drawingManager, selectedPrimaryClass, setDrawingCount);
        setHasUnsavedChanges(true);
      }
    };

    // Handler: drawingmodechanged
    const handleDrawingModeChanged = (e) => {
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
    const handleDrawingErased = (e) => {
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
    mapRef.current.events.add("drawingchanged", drawingManager, handleDrawingChanged);
    mapRef.current.events.add("drawingmodechanged", drawingManager, handleDrawingModeChanged);
    mapRef.current.events.add("drawingstarted", drawingManager, handleDrawingStarted);
    mapRef.current.events.add("drawingerased", drawingManager, handleDrawingErased);
    mapRef.current.events.add("drawingcomplete", drawingManager, handleDrawingComplete);

    // Handler cleanup
    return () => {
      initGuidedTourState("labelingToolGuide", appParams.guidedTourProperties);
      if (!mapRef.current) return;
      mapRef.current.events.remove("drawingchanged", drawingManager, handleDrawingChanged);
      mapRef.current.events.remove("drawingmodechanged", drawingManager, handleDrawingModeChanged);
      mapRef.current.events.remove("drawingstarted", drawingManager, handleDrawingStarted);
      mapRef.current.events.remove("drawingerased", drawingManager, handleDrawingErased);
      mapRef.current.events.remove("drawingcomplete", drawingManager, handleDrawingComplete);
    };
  }, [
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


  async function createMap() {
    labelingToolDataRef.current = await apiGet(
      "GetLayerLabelingToolData?projectId=" +
      projectId +
      "&imageLayerId=" +
      imageLayerId
    );
    const projectDetails = await apiGet(
      "GetProjectDetails?projectId=" + projectId
    );

    const map = new window.atlas.Map(mapRef.current, {
      center: [0, 0],
      preserveDrawingBuffer: true,
      zoom: 3,
      maxPitch: 0,
      pitch: 0,
      style: isAzureMapsPlaceholder ? "blank" : "grayscale_light",
      language: "en-US",
      authOptions: getAzureMapsAuthOptions(),
    });

    map.events.add("ready", async function () {
      // Avoid map rotation
      map.setUserInteraction({
        dragRotateInteraction: false,
        scrollZoomInteraction: true,
        pinchZoomInteraction: true,
        pinchRotateInteraction: false,
      });

      map.controls.add(new window.atlas.control.ZoomControl(), {
        position: "bottom-left",
      });

      map.setCamera({
        bearing: 0,
      });

      loadImagery(
        labelingToolDataRef.current.imagery.preEventTileUrl,
        map,
        preImageryRef,
        "preEventImageryLayer",
        false
      );

      loadImagery(
        labelingToolDataRef.current.imagery.postEventTileUrl,
        map,
        postImageryRef,
        "postEventImageryLayer",
        true
      );

      var drawingManagerTemp = new window.atlas.drawing.DrawingManager(map, {});
      

      const primaryClasses = projectDetails.primaryClasses;
      drawingManagerTemp.source.add(
        labelingToolDataRef.current.labels != null
          ? labelingToolDataRef.current.labels
          : []
      );

      primaryClassesRef.current = parsePrimaryClasses(primaryClasses);
      setPrimaryClasses(primaryClassesRef.current);
      setSelectedPrimaryClass(primaryClassesRef.current[0].key);


      const bbox = loadStudyArea(map, labelingToolDataRef.current);
      setDrawingManager(drawingManagerTemp);
      centrateMap(bbox, map, 2500);

      initGuidedTourState("labelingToolGuide", appParams.guidedTourProperties);
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
    });


    mapRef.current = map;
  }

  return (
    <>
      <div
        ref={mapRef}
        id="map"
        className="labeling-tool-page d-flex flex-grow-1 p-0 m-0"
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
              undo={undo}
              redo={redo}
            />
          </>
        ) : null}
      </div>
    </>
  );
};

export default LabelingTool;
