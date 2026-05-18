// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Dependencies
import { useEffect, useRef, useState, useContext } from "react";
import { apiGet } from "../../util/api";
import { useParams } from "react-router-dom";
import Labels from "./Labels";
import { AppContext } from "../../AppContext";
import PropType from "prop-types";
import { convertDateToString } from "../../util/conversion";
import VisualizerImageryControls from "./VisualizerImageryControls"
import "../../assets/css/visualizer.css";
import { getAzureMapsAuthOptions } from "../../util/azureMapsAuth";


const Visualizer = ({ setModalComponent }) => {
  Visualizer.propTypes = {
    setModalComponent: PropType.func.isRequired,
  };


  // Constants
  const { projectId, imageLayerId, modelId } = useParams();
  const [globalVisualizerResults, setGlobalVisualizerResults] = useState({});
  const { setIsLoading, updateAppParams, appParams } = useContext(AppContext);
  const primaryMapRef = useRef(null);
  const secondaryMapRef = useRef(null);
  const swipeMapRef = useRef(null);
  const zoomControlRef = useRef(null);
  const [swipeStateMobile, setSwipeStateMobile] = useState("post");

  const [imageryValues, setImageryValues] = useState({
    opacity: 1,
    contrast: 0,
    hueRotation: 0,
    saturation: 0,
  });

  // Visualizer data fetching function
  async function getVisualizerResults() {
    setIsLoading(true);
    return await apiGet(
      "GetVisualizerResults?projectId=" +
      projectId +
      "&imageLayerId=" +
      imageLayerId +
      "&modelId=" +
      modelId
    )
      .then((response) => {
        setIsLoading(false);
                console.log(response);
        return response;

      })
      .catch((error) => {
        console.error("Error fetching visualizer results:", error);
        throw error;
      });
  }

  useEffect(() => {
    if (swipeMapRef.current) {
      if (swipeStateMobile === "post") {
        swipeMapRef.current.setOptions({
          sliderPosition: 0,
        });
      } else {
        swipeMapRef.current.setOptions({
          sliderPosition: window.innerWidth,
        });
      }
    }
  }, [swipeStateMobile]);


  function checkResponsiveness() {
    const bootstrapBreakpoint = appParams.bootstrapBreakpoint;
    if (bootstrapBreakpoint < 4) {
      if (swipeMapRef.current) {
        swipeMapRef.current.setOptions({
          sliderPosition: swipeStateMobile === "post" ? 0 : window.innerWidth,
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
          sliderPosition: window.innerWidth / 2
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
    const initializeMaps = async () => {
      if (window.atlas) {

        // Create zoom control reference, so it can be referenced when deleting and resetting regarding responsiveness
        zoomControlRef.current = new window.atlas.control.ZoomControl();

        var visualizerResults = await getVisualizerResults();

        updateAppParams({
          visualizerTitle: convertToVisualizerTitle(visualizerResults),
        });

        var authOptions = getAzureMapsAuthOptions();

        // PRE EVENT MAP SETUP
        const primaryMap = new window.atlas.Map(primaryMapRef.current, {
          style: "satellite",
          authOptions: authOptions,
        });

        // POST EVENT MAP SETUP
        const secondaryMap = new window.atlas.Map(secondaryMapRef.current, {
          style: "satellite",
          authOptions: authOptions,
        });

        // SwipeMap object to enable swipe functionality
        swipeMapRef.current = new window.atlas.SwipeMap(
          primaryMap,
          secondaryMap
        );

        // Primary map event listeners
        primaryMap.events.add("ready", async function () {
          // Avoid map rotation
          avoidRotation(primaryMap);

          await loadPreOrPostDisasterLayer(
            primaryMap,
            visualizerResults.preDisasterImagery,
            "preDisasterImagery"
          );

          loadPredictedDamageLayer(
            primaryMap,
            visualizerResults.predictedDamageLayer,
          );

          loadPredictionsLayer(
            primaryMap,
            visualizerResults.predictionsLayer,
          );

          await loadStudyArea(primaryMap, visualizerResults.studyArea);

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

          loadPredictedDamageLayer(
            secondaryMap,
            visualizerResults.predictedDamageLayer
          );

          loadPredictionsLayer(
            secondaryMap,
            visualizerResults.predictionsLayer
          );

          loadStudyArea(secondaryMap, visualizerResults.studyArea);
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

    window.addEventListener("keydown", handleKeyboardShortcuts);
    //On component dismount
    return () => {
      setModalComponent(null);
      updateAppParams({ visualizerTitle: "" });
      window.removeEventListener("keydown", handleKeyboardShortcuts);
    };

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleKeyboardShortcuts = (event) => {
    // Ignore when typing in an input/textarea/contenteditable element.
    const target = event.target;
    const tag = target?.tagName;
    if (
      tag === "INPUT" ||
      tag === "TEXTAREA" ||
      target?.isContentEditable
    ) {
      return;
    }
    if (event.ctrlKey || event.altKey || event.metaKey) {
      return;
    }
    if (!swipeMapRef.current) {
      return;
    }
    switch (event.key.toLowerCase()) {
      case "a":
        swipeMapRef.current.setOptions({
          sliderPosition: 1,
        });
        break;
      case "s":
        swipeMapRef.current.setOptions({
          sliderPosition: window.innerWidth / 2,
        });
        break;
      case "d":
        swipeMapRef.current.setOptions({
          sliderPosition: window.innerWidth - 1,
        });
        break;
      default:
        break;
    }
  };

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
    // Create Data Source
    var dataSource = new window.atlas.source.DataSource();
    map.sources.add(dataSource);

    // Add data
    var geoJsonData = {
      type: "FeatureCollection",
      features: studyArea,
    };
    dataSource.add(geoJsonData);

    // Create linelayer to define workspace
    var lineLayer = new window.atlas.layer.LineLayer(dataSource, null, {
      strokeColor: "#FFFFFF",
      strokeWidth: 2,
    });
    map.layers.add(lineLayer);

    resetMapPosition(studyArea, 3000);
  }

  // Reset map position to study area
  function resetMapPosition(studyArea, duration = 700) {
    primaryMapRef.current.setCamera({
      bounds: studyArea[0].bbox,
      type: "fly",
      duration: duration,
      padding: 100,
    });
  }

  // Adds a layer with pre or post disaster imagery
  async function loadPreOrPostDisasterLayer(map, disasterLayer, customId) {

    if (!disasterLayer || disasterLayer.url != "") {
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

      var imagery = new window.atlas.layer.TileLayer({
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

  // Adds a layer with predicted damage
  function loadPredictedDamageLayer(map, predictedDamageLayer) {
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

  // Adds a layer with the raw model predictions (rendered via TiTiler colormap).
  // Hidden by default; toggle from the InfoPanel.
  function loadPredictionsLayer(map, predictionsLayer) {
    if (!predictionsLayer || !predictionsLayer.url) {
      return;
    }
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
    const layers = currentMap.current.layers.getLayers();
    return layers.find((layer) => layer.customId === customId);
  }

  // Toggles visibility of predicted damage layer
  function togglePredictedDamageLayerVisibility(customId, isVisible) {
    const layer = getLayerById(primaryMapRef, customId);
    if (layer) {
      layer.setOptions({ visible: isVisible });
    }

    const layer2 = getLayerById(secondaryMapRef, customId);
    if (layer2) {
      layer2.setOptions({ visible: isVisible });
    }
  }

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

      var preImageryRef = getLayerById(primaryMapRef, "preDisasterImagery");
      var postImageryRef = getLayerById(secondaryMapRef, "postDisasterImagery");

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

      var preImageryRef = getLayerById(primaryMapRef, "preDisasterImagery");
      var postImageryRef = getLayerById(secondaryMapRef, "postDisasterImagery");

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


  return (
    <div className="visualizer-container">
      <div id="primaryMap" ref={primaryMapRef} className="map"></div>
      <div id="secondaryMap" ref={secondaryMapRef} className="map"></div>

      <Labels
        togglePredictedDamageLayerVisibility={
          togglePredictedDamageLayerVisibility
        }
        resetMapPosition={resetMapPosition}
        visualizerResults={globalVisualizerResults}
        setSwipeStateMobile={setSwipeStateMobile}
        swipeStateMobile={swipeStateMobile}
      />

      <VisualizerImageryControls
        updateImageryProperties={updateImageryProperties}
        resetImageryProperties={resetImageryProperties}
        imageryValues={imageryValues}
        visualizerResults={globalVisualizerResults}
      />
    </div>
  );
};

export default Visualizer;
