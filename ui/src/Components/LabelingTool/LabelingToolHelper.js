// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { apiPut } from "../../util/api";
import settings from "../../assets/json/settings.json";
import { getAzureMapsAuthOptions } from "../../util/azureMapsAuth";


export function createShape(drawingManager, selectedPrimaryClass, setDrawingCount) {
  const source = drawingManager.getSource();
  const shapes = source.getShapes();
  const lastShape = shapes[shapes.length - 1];

  if (!lastShape) return;

  const props = {
    ...lastShape.getProperties?.(),
    primaryClass: selectedPrimaryClass,
    source: "Drawn|Imagery",
  };
  lastShape.setProperties(props);

  setDrawingCount(source.getShapes().length);
}

export function updateShape(drawingManager, selectedShape, selectedClass) {
  const source = drawingManager.getSource();
  const shape = source.getShapeById(selectedShape.getId());
  if (shape) {
    const props = {
      ...shape.getProperties?.(),
      primaryClass: selectedClass,
    };
    shape.setProperties(props);
  }
}

export const updateDrawingLayerStyles = (drawingManager, primaryClasses) => {
  const layers = drawingManager.getLayers();

  var colorExpression = [
    "match",
    ["get", "primaryClass"],
  ];

  var strokeColorExpression = [
    "match",
    ["get", "primaryClass"],
  ];

  primaryClasses.forEach((shapeType) => {
    colorExpression.push(shapeType.text);
    colorExpression.push(shapeType.color);

    strokeColorExpression.push(shapeType.text);
    strokeColorExpression.push(shapeType.color);
  });

  colorExpression.push("#FFFFFF");
  strokeColorExpression.push("#FF0000");

  layers.polygonLayer.setOptions({
    fillColor: colorExpression,
  });

  layers.polygonOutlineLayer.setOptions({
    strokeColor: strokeColorExpression,
    strokeWidth: 3,
  });
};


export const layerTypeOptions = [
  {
    key: "azureMapsSatellite",
    text: "Azure Maps Satellite",
  },
  {
    key: "imagery",
    text: "Imagery",
  },
];


export function loadImagery(tileUrl, map, imageryRef, customId, isVisible) {

  var tempTileUrlPath = tileUrl;
  if (tempTileUrlPath === "") {
    tempTileUrlPath = `https://atlas.microsoft.com/map/tile?api-version=2.1&tilesetId=microsoft.imagery&zoom={z}&x={x}&y={y}`;
  }


  imageryRef.current = new window.atlas.layer.TileLayer({
    tileUrl: tempTileUrlPath,
  });

  try {
    imageryRef.current.setOptions({ visible: isVisible });
    imageryRef.current.customId = customId;
    map.layers.add(imageryRef.current);
  } catch (error) {
    console.error("Error loading imagery layer:", error);
  }
}

export function centrateMap(bbox, map, duration = 2500) {
  map.setCamera({
    bounds: bbox,
    padding: 0,
    type: "fly",
    pitch: 0,
    duration: duration,
    maxPitch: 0
  });
}

export function loadStudyArea(map, imageLayer) {

  // Create Data Source
  var dataSource = new window.atlas.source.DataSource();
  map.sources.add(dataSource);

  // Add data
  var geoJsonData = {
    "type": "FeatureCollection",
    "features": imageLayer.features
  };
  dataSource.add(geoJsonData);


  // Create linelayer to define workspace
  var lineLayer = new window.atlas.layer.LineLayer(dataSource, null, {
    strokeColor: settings.labelingToolSettings.grid.gridStrokeColor,
    strokeWidth: 4,
    strokeDashArray: [1.5, 1.5]
  });
  map.layers.add(lineLayer);

  return window.atlas.data.BoundingBox.fromData(geoJsonData);
}

export async function saveLabels(drawingManager, labelingToolDataRef, setIsLoading, setHasUnsavedChanges) {

  var labels = [];
  drawingManager.source.shapes.map((shape) => {
    labels.push(shape.data);
  });



  labelingToolDataRef.current.labels = labels;

  setIsLoading(true, "Saving Labels...");
  try {
    await apiPut("PutLabelsFromLabelTool?imageLayerId", labelingToolDataRef.current);
    setHasUnsavedChanges(false);
    setIsLoading(false);
    return (true);
  } catch (error) {
    setIsLoading(false);
    return (false);
  }
}

export function checkLabelsState(drawingManager) {
  for (const shape of drawingManager.source.shapes) {
    const properties = shape.getProperties();
    const coordinates = shape.data.geometry.coordinates[0];

    var isADot = coordinates.length == 2 && coordinates[0][0] === coordinates[1][0] && coordinates[0][1] === coordinates[1][1];

    if (!properties.primaryClass && !isADot) {
      return false;
    }
  }
  return true;
}

export function parsePrimaryClasses(primaryClasses) {
  return primaryClasses.map((primaryClass) => {
    return {
      key: primaryClass.name,
      text: primaryClass.name,
      color: primaryClass.color,
      styles: {
        root: {
          selectors: {
            ".ms-ChoiceFieldLabel": {
              color: primaryClass.color
            },
          },
        },
      },
    };
  });
}