// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useEffect, useState } from "react";
import { ChoiceGroup, PrimaryButton, Slider } from "@fluentui/react";
import CreateEditModelTrainingModal from "../CreateEditModelTrainingModal";
import { saveLabels, checkLabelsState } from "./LabelingToolHelper";
import DrawingToolbar from "./DrawingToolbar";
import PropType from "prop-types";
import { updateShape } from "./LabelingToolHelper";
import ImportLabelsModal from "./ImportLabelsModal";
import { fileDownload } from "../../util/file";
import { apiGet } from "../../util/api";

const LabelingToolRightPanel = ({
  primaryClasses,
  selectedPrimaryClass,
  setSelectedPrimaryClass,
  drawingManager,
  setDrawingManager,
  setDialog,
  labelingToolDataRef,
  setIsLoading,
  setHasUnsavedChanges,
  hasUnsavedChanges,
  setModalComponent,
  projectId,
  drawingCount,
  setDrawingCount,
  selectedShape,
  imageLayerId,
  undo,
  redo,
}) => {
  LabelingToolRightPanel.propTypes = {
    primaryClasses: PropType.array.isRequired,
    selectedPrimaryClass: PropType.string.isRequired,
    setSelectedPrimaryClass: PropType.func.isRequired,
    drawingManager: PropType.object.isRequired,
    setDrawingManager: PropType.func.isRequired,
    setDialog: PropType.func.isRequired,
    labelingToolDataRef: PropType.object.isRequired,
    setIsLoading: PropType.func.isRequired,
    setHasUnsavedChanges: PropType.func.isRequired,
    hasUnsavedChanges: PropType.bool.isRequired,
    setModalComponent: PropType.func.isRequired,
    projectId: PropType.string.isRequired,
    drawingCount: PropType.number.isRequired,
    setDrawingCount: PropType.func.isRequired,
    selectedShape: PropType.object,
    imageLayerId: PropType.string.isRequired,
    undo: PropType.func.isRequired,
    redo: PropType.func.isRequired,
  };

  useEffect(() => {
    if (selectedShape !== null) {
      updateShape(
        drawingManager,
        selectedShape,
        selectedPrimaryClass,
      );
      setHasUnsavedChanges(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedPrimaryClass]);

  async function handleSave() {

    var message = "Labels saved successfully";
    if (checkLabelsState(drawingManager)) {
      const isSaved = await saveLabels(
        drawingManager,
        labelingToolDataRef,
        setIsLoading,
        setHasUnsavedChanges
      );

      if (!isSaved) {
        message = "There was an error saving the labels";
      }
    } else {
      message = "There are labels without a valid primary class. Please classify or remove them before saving.";
    };

    const buttons = [
      {
        type: "primary",
        key: "close",
        text: "Close",
        onClick: () => {
          setDialog("", "", []);
        },
      },
    ];

    setDialog("Important", message, buttons);
  }

  function handlePrimaryClassChange(newClass) {
    if (selectedShape !== null) {
      const buttons = [
        {
          type: "primary",
          key: "yes",
          text: "Yes",
          onClick: () => {
            setSelectedPrimaryClass(newClass);
            setDialog("", "", []);
            setTimeout(() => {
              document.getElementById("pointer").click();
            }, 100);
          }
        },
        {
          type: "default",
          key: "no",
          text: "No",
          onClick: () => {
            setDialog("", "", []);
          },
        },
      ];
      setDialog("Important", "You are about to change the primary class of the selected label. Do you want to continue?", buttons);
    } else {
      setSelectedPrimaryClass(newClass);
    }
  }

  async function handleSaveAndTrain() {
    if (checkLabelsState(drawingManager)) {
      const isSaved = await saveLabels(
        drawingManager,
        labelingToolDataRef,
        setIsLoading,
        setHasUnsavedChanges
      );

      if (!isSaved) {
        const buttons = [
          {
            type: "primary",
            key: "close",
            text: "Close",
            onClick: () => {
              setDialog("", "", []);
            },
          },
        ];

        setDialog("Important", "There was an error saving the labels", buttons);
      } else {
        setModalComponent(
          <CreateEditModelTrainingModal
            onClose={() => setModalComponent(null)}
            projectId={projectId}
            imageLayer={labelingToolDataRef.current}
            guidedTour="createEditModelTrainingModalGuide"
            autoLaunchGuidedTour={true}
          />
        );
      }
    } else {
      const buttons = [
        {
          type: "primary",
          key: "close",
          text: "Close",
          onClick: () => {
            setDialog("", "", []);
          },
        },
      ];
      setDialog("Important", "There are labels without a valid primary class. Please classify or remove them before saving.", buttons);
    }
  }

  const labelSavingMenuOptions = () => ({
    items: [
      {
        key: "import",
        text: "Import from GeoJSON",
        iconProps: { iconName: "Upload" },
        title: "",
        onClick: () => {
          handleImport();
        },
      },
      {
        key: "exportToGeoJSON",
        text: "Export to GeoJSON",
        iconProps: { iconName: "Download" },
        onClick: () => {
          handleLabelExport();
        },
      },
      {
        key: "save",
        text: "Save",
        iconProps: { iconName: "Save" },
        title: drawingCount === 0 ? "Saving requires at least one label" : "",
        disabled: drawingCount === 0,
        onClick: () => {
          handleSave();
        },
      },
      {
        key: "saveAndTrain",
        text: "Save and Train",
        iconProps: { iconName: "SaveAndClose" },
        title: drawingCount === 0 ? "Training requires at least one label" : "",
        disabled: drawingCount === 0,
        onClick: () => {
          handleSaveAndTrain();
        },
      },
    ],
  });

  async function handleLabelExport() {

    if (hasUnsavedChanges) {
      setDialog("Important", "There are unsaved changes. Please save before continue.", [
        {
          type: "primary",
          key: "close",
          text: "Close",
          onClick: () => {
            setDialog("", "", []);
          },
        },
      ]);
      return false;
    }

    try {
      setIsLoading(true, "Exporting Labels to GeoJSON");
      const project = await apiGet("GetProjectDetails?projectId=" + projectId);
      const imageLayer = project.imageLayer.find(layer => layer.imageLayerId === imageLayerId);

      if (imageLayer.labelsUrl) {
        if (import.meta.env.VITE_STORAGE_APIM_URL) {
          imageLayer.labelsUrl = imageLayer.labelsUrl.replace(
            /^https?:\/\/[^/]+/,
            import.meta.env.VITE_STORAGE_APIM_URL
          );
        }
        fileDownload(imageLayer.labelsUrl, setDialog);
      }
      setIsLoading(false);
    } catch (error) {
      setDialog("Error", "An error occurred while exporting labels.", [
        {
          type: "primary",
          key: "close",
          text: "Close",
          onClick: () => {
            setDialog("", "", []);
          },
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  }

  function handleImport() {

    const fileInput = document.getElementById("importGeoJSON");

    const handleFileChange = (e) => {
      const file = e.target.files[0];
      if (!file) return;

      const reader = new FileReader();
      reader.onload = (event) => {
        try {
          const geojsonData = JSON.parse(event.target.result);

          if (geojsonData.type === "FeatureCollection" && Array.isArray(geojsonData.features)) {
            setModalComponent(
              <ImportLabelsModal
                onClose={() => setModalComponent(null)}
                geojsonData={geojsonData}
                labelingToolDataRef={labelingToolDataRef}
                drawingManager={drawingManager}
                setDrawingManager={setDrawingManager}
                setHasUnsavedChanges={setHasUnsavedChanges}
                primaryClasses={primaryClasses}
                setDrawingCount={setDrawingCount}
                undo={undo}
                redo={redo}
              />
            );

            fileInput.value = "";
          } else {
            throw new Error("The file is not a valid GeoJSON FeatureCollection.");
            fileInput.value = "";
          }
        } catch (err) {
          console.error("Error importing GeoJSON:", err);
          const buttons = [
            {
              type: "primary",
              key: "close",
              text: "Close",
              onClick: () => {
                setDialog("", "", []);
              },
            },
          ];

          setDialog("Important", "The selected file is not a valid GeoJSON.", buttons);
          fileInput.value = "";
        }
      };

      reader.readAsText(file);
      fileInput.removeEventListener("change", handleFileChange);
    };

    fileInput.addEventListener("change", handleFileChange);
    fileInput.click();
  }

  return (
    <>
      <DrawingToolbar drawingManager={drawingManager} setDrawingManager={setDrawingManager} undo={undo} redo={redo} />
      <div
        style={{
          position: "absolute",
          right: 10,
          top: 70,
          backgroundColor: "rgba(255, 255, 255, 1)",
          padding: "5px 10px",
          borderRadius: "5px",
          zIndex: 1000,
        }}
        id="rightPanel"
      >
        <div className="col-12 d-flex">
          <ChoiceGroup
            options={
              primaryClasses && primaryClasses.length > 0 ? primaryClasses : []
            }
            selectedKey={selectedPrimaryClass}
            label="Primary Class"
            onChange={(e, option) => {
              handlePrimaryClassChange(option.key);
            }}
          />
        </div>
        <div className="col-12 d-flex mt-2 flex-column pt-2 pb-2">
          <PrimaryButton
            id="saveAndTrainButton"
            split
            menuProps={labelSavingMenuOptions()}
            className="w-100"
            text="Actions"
          />
        </div>
      </div>
      <input type="file" id="importGeoJSON" className="d-none" accept=".geojson" />
    </>
  );
};

export default LabelingToolRightPanel;
