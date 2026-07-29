// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

import { useEffect, useState } from "react";

import {
  Checkbox,
  Button,
} from "@fluentui/react-components";


import SectionModal from "../SectionModal";
import proptypes from "prop-types";


const ImportLabelsModal = ({ onClose, geojsonData, labelingToolDataRef, drawingManager, setDrawingManager, setHasUnsavedChanges, primaryClasses, setDrawingCount }) => {
  ImportLabelsModal.propTypes = {
    onClose: proptypes.func.isRequired,
    projectId: proptypes.string,
    labelingToolDataRef: proptypes.object.isRequired,
    drawingManager: proptypes.object.isRequired,
    setDrawingManager: proptypes.func.isRequired,
    setHasUnsavedChanges: proptypes.func.isRequired,
    primaryClasses: proptypes.array.isRequired,
    setDrawingCount: proptypes.func.isRequired,
  };

  const [invalidLabels, setInvalidLabels] = useState([]);
  const [validLabels, setValidLabels] = useState([]);
  const [processedFile, setProcessedFile] = useState(false);
  const [includeInvalidLabels, setIncludeInvalidLabels] = useState(false);
  const [outOfStudyAreaLabels, setOutOfStudyAreaLabels] = useState([]);
  const [repeatedLabels, setRepeatedLabels] = useState([]);


  useEffect(() => {
    if (geojsonData) {
      processFile();
    }
  }, [geojsonData]);

  function processFile() {
    var geojsonDataTemp = geojsonData;
    // convert all class properties to primaryClass
    geojsonDataTemp.features.forEach((feature) => {
      if (feature.properties && feature.properties.class) {
        feature.properties.primaryClass = feature.properties.class;
        delete feature.properties.class;
      }
    });

    geojsonDataTemp = removeOfStudyAreaLabels(geojsonDataTemp);
    geojsonDataTemp = removeRepeatedLabels(geojsonDataTemp);
    geojsonDataTemp = removeInvalidLabels(geojsonDataTemp);
    setValidLabels(geojsonDataTemp.features);
    setProcessedFile(true);
  }


  function removeInvalidLabels(geojsonData) {
    // Identify invalid labels first
    const invalid = geojsonData.features.filter((feature) => {
      const hasPrimaryClass = feature.properties && feature.properties.primaryClass;
      const isValidClass = hasPrimaryClass && primaryClasses.some(c => c.key === feature.properties.primaryClass);
      return !isValidClass;
    });

    setInvalidLabels(invalid);

    // Remove invalid labels from geojsonData and return it
    geojsonData.features = geojsonData.features.filter((feature) => {
      const hasPrimaryClass = feature.properties && feature.properties.primaryClass;
      const isValidClass = hasPrimaryClass && primaryClasses.some(c => c.key === feature.properties.primaryClass);
      return isValidClass;
    });
    return geojsonData;
  }

  function removeRepeatedLabels(geojsonData) {
    const existingLabels = new Set(drawingManager.source.shapes.map((label) => JSON.stringify(label.data.geometry.coordinates)));

    // Find repeated labels
    const repeated = geojsonData.features.filter((feature) => {
      const coords = JSON.stringify(feature.geometry.coordinates);
      return existingLabels.has(coords);
    });

    setRepeatedLabels(repeated);

    // Remove repeated labels from geojsonData and return it
    geojsonData.features = geojsonData.features.filter((feature) => {
      const coords = JSON.stringify(feature.geometry.coordinates);
      return !existingLabels.has(coords);
    });
    return geojsonData;
  }

  function removeOfStudyAreaLabels(geojsonData) {
    
    const studyArea = labelingToolDataRef.current.features[0].bbox;

    // Filter features outside studyArea bbox
    const [minX, minY, maxX, maxY] = studyArea;

    const outOfStudyArea = geojsonData.features.filter((feature) => {
      // Get all coordinates from the feature geometry
      const getCoords = (geometry) => {
        if (geometry.type === "Point") return [geometry.coordinates];
        if (geometry.type === "MultiPoint" || geometry.type === "LineString") return geometry.coordinates;
        if (geometry.type === "MultiLineString" || geometry.type === "Polygon") return geometry.coordinates.flat();
        if (geometry.type === "MultiPolygon") return geometry.coordinates.flat(2);
        return [];
      };
      const coords = getCoords(feature.geometry);

      // Check if any coordinate is outside the bbox
      return coords.some(([lng, lat]) =>
        lng < minX || lng > maxX || lat < minY || lat > maxY
      );
    });

    setOutOfStudyAreaLabels(outOfStudyArea);

    // Remove outOfStudyArea from the main geojsonData and return
    geojsonData.features = geojsonData.features.filter((feature) => !outOfStudyArea.includes(feature));
    return geojsonData;
  }

  function importLabels() {
    validLabels.forEach((feature) => {
      feature.id = `${Date.now()}-${Math.random().toString(36).substring(2, 11)}`;
      drawingManager.source.add(feature);
    });

    if (includeInvalidLabels) {
      invalidLabels.forEach((feature) => {
        feature.id = `${Date.now()}-${Math.random().toString(36).substring(2, 11)}`;
        drawingManager.source.add(feature);
      });
    }

    setDrawingManager(drawingManager);
    setHasUnsavedChanges(true);
    setDrawingCount(drawingManager.source.shapes.length);
    onClose();
  }

  return (
    <SectionModal
      title={"Import Labels"}
      body={
        processedFile ? (
          <div className="container-create-edit-project-modal p-3">

            <div className="row">

              <div className="col-12 p-0 mb-3">
                <ul>
                <li>{validLabels.length} valid label(s) found, will be imported</li>
                


            {invalidLabels.length > 0 &&
                  <li><Checkbox labelPosition="before" onChange={(e, data) => setIncludeInvalidLabels(data.checked)} label={`${invalidLabels.length} label(s) found in study area with missing primary class. Include in import?`} /></li> 
            }



            {outOfStudyAreaLabels.length > 0 &&  (
              <li>{outOfStudyAreaLabels.length} label(s) found outside study area will be ignored</li>
            )}

            {repeatedLabels.length === 0 && (
              <li>{repeatedLabels.length} duplicate label(s) will be ignored</li>
            )}

            </ul>
                </div>
              </div>


            <div className="row">
              <div className="col-12 d-flex justify-content-end pt-2">
                <Button appearance="primary" onClick={importLabels} className="me-2" id="createEditProjectSubmit" disabled={validLabels.length === 0 && invalidLabels.length === 0}>
                  Import
                </Button>
                <Button onClick={onClose}>Cancel</Button>
              </div>
            </div>
          </div>
        ) : <></>
      }
      onClose={onClose}
      icon="Upload"
    />
  );
}

export default ImportLabelsModal;
