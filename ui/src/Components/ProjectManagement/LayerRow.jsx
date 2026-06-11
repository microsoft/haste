// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Imports
import { DefaultButton, IconButton, Text, TooltipHost } from "@fluentui/react";
import PropTypes from "prop-types";
import ModelRow from "./ModelRow";
import ModelRowMobile from "./ModelRowMobile";
import React, { useContext } from "react";
import { apiDelete } from "../../util/api";
import { limitTextLength } from "../../util/conversion";
import { AppContext } from "../../AppContext";
import CreateEditModelTrainingModal from "../CreateEditModelTrainingModal";
import { useNavigate } from "react-router-dom";
import StatusIndicator from "../OtherComponents/StatusIndicator";
import ImageLayerInfoMobile from "./ImageLayerInfoMobile";
import { fileDownload } from "../../util/file";

const LayerRow = ({
  item,
  index,
  visibleModelId,
  projectId,
  onComponentChange,
  setModalComponent,
  fetchProjectDetails,
  setComponentState,
  eventTypes
}) => {
  LayerRow.propTypes = {
    item: PropTypes.object.isRequired,
    index: PropTypes.number.isRequired,
    visibleModelId: PropTypes.string.isRequired,
    projectId: PropTypes.string.isRequired,
    onComponentChange: PropTypes.func.isRequired,
    setModalComponent: PropTypes.func.isRequired,
    fetchProjectDetails: PropTypes.func.isRequired,
    setComponentState: PropTypes.func,
    eventTypes: PropTypes.array.isRequired
  };
  const navigate = useNavigate();
  const { setIsLoading, appParams } = useContext(AppContext);
  async function handleDeletion() {
    setDialog();
    setIsLoading(true, "Removing Image Layer");
    await apiDelete(
      `DeleteLayer?imageLayerId=${item.imageLayerId}&projectId=${projectId}`
    )
      .then(() => {
        fetchProjectDetails();
      })
      .catch((error) => {
        console.error("Error removing image layer:", error);
      });
    setIsLoading(false);
  }

  const { setDialog } = React.useContext(AppContext);

  const moreMenuOptions = {
    items: [
      {
        key: "ExportLabelsToGeoJSON",
        text: "Export Labels to GeoJSON",
        iconProps: { iconName: "Download" },
        disabled: item.labelsUrl === null,
        onClick: () => {
          if (item.labelsUrl) {
            if (import.meta.env.VITE_STORAGE_APIM_URL) {
              item.labelsUrl = item.labelsUrl.replace(
                /^https?:\/\/[^/]+/,
                import.meta.env.VITE_STORAGE_APIM_URL
              );
            }
            fileDownload(item.labelsUrl, setDialog);
          } else {
            setDialog("Error", "No labels available for export.");
          }
        },
      },
      {
        key: "DownloadBuildingFootprints",
        text: "Download Building Footprints",
        iconProps: { iconName: "Download" },
        disabled: !item.buildingFootprintsUrl,
        onClick: () => {
          if (item.buildingFootprintsUrl) {
            let url = item.buildingFootprintsUrl;
            if (import.meta.env.VITE_STORAGE_APIM_URL) {
              url = url.replace(
                /^https?:\/\/[^/]+/,
                import.meta.env.VITE_STORAGE_APIM_URL
              );
            }
            fileDownload(url, setDialog);
          } else {
            setDialog("Error", "No building footprints available for this image layer.");
          }
        },
      },
      {
        key: "DownloadValidAreaMask",
        text: "Download Valid Area Mask",
        iconProps: { iconName: "Download" },
        disabled: !item.validAreaMaskUrl,
        onClick: () => {
          if (item.validAreaMaskUrl) {
            let url = item.validAreaMaskUrl;
            if (import.meta.env.VITE_STORAGE_APIM_URL) {
              url = url.replace(
                /^https?:\/\/[^/]+/,
                import.meta.env.VITE_STORAGE_APIM_URL
              );
            }
            fileDownload(url, setDialog);
          } else {
            setDialog("Error", "No valid area mask available for this image layer.");
          }
        },
      },
      {
        key: "edit",
        text: "Edit",
        iconProps: { iconName: "Edit" },
        onClick: () => {
          setModalComponent(
            navigate("/edit-imageLayer/" + projectId + "/" + item.imageLayerId)
          );
        },
      },
      {
        key: "remove",
        text: "Remove",
        iconProps: { iconName: "Delete" },
        onClick: () => {
          setDialog(
            "Important",
            `Do you want to remove the image layer "${limitTextLength(item.name, 40, 40)}"?. This will remove all child Labels and Models.`,
            [
              {
                type: "primary",
                key: "yes",
                text: "Yes",
                onClick: () => {
                  handleDeletion();
                },
              },
              {
                type: "default",
                key: "no",
                text: "No",
                onClick: () => setDialog(),
              },
            ]
          );
        },
      },
    ],
  };

  return (
    <React.Fragment>
      <tr>
        <td
          id={"singleProjectExpandCollapseImageLayerModels" + index}
          style={{ width: '43px' }}
          className="align-items-center"
        >
          {((item.models && item.models.length > 0) || appParams.bootstrapBreakpoint < 4) && (
            <IconButton
              onClick={() =>
                onComponentChange(item.imageLayerId, "visibleModelId")
              }
              className="me-2"
              aria-label="expand-collapse"
              iconProps={{
                iconName:
                  visibleModelId == item.imageLayerId
                    ? "ChevronDown"
                    : "ChevronRight",
                styles: {
                  root: {
                    fontSize: 12,
                  },
                },
              }}
            />
          )}
        </td>
        <td className="custom-text-no-wrap">
          <Text
            variant="medium"
            className="me-4"
            id={"singleProjectName" + index}
          >
            {
              <TooltipHost content={item.name} delay={2}>
                {limitTextLength(item.name, false, 45)}
              </TooltipHost>
            }
          </Text>
        </td>
        <td className="custom-text-no-wrap d-none d-xl-table-cell">
          <StatusIndicator
            id={"singleProjectImageLayerStatus" + index}
            currentStep={item.currentStep}
            totalSteps={item.totalSteps}
            progressPct={item.progressPct}
            status={item.status}
            statusMessage={item.statusMessage}
            prefix="Imagery"
          />
        </td>
        <td className="custom-text-no-wrap d-none d-xl-table-cell">
          <DefaultButton
            id={"singleProjectLabelingToolLaunch" + index}
            className="dashboard-button"
            onClick={() =>
              navigate(`/labeling-tool/${projectId}/${item.imageLayerId}`)
            }
            disabled={item.status !== "Processed"}
          >
            Launch
          </DefaultButton>{" "}
          <Text className="pe-4" variant="small">
            ({item.labelProjectCount})
          </Text>
        </td>
        <td className="custom-text-no-wrap d-none d-xl-table-cell">
          <DefaultButton
            id={"singleProjectModelTraining" + index}
            className="dashboard-button"
            onClick={() =>
              setModalComponent(
                <CreateEditModelTrainingModal
                  onClose={() => setModalComponent(null)}
                  projectId={projectId}
                  imageLayer={item}
                  fetchProjectDetails={fetchProjectDetails}
                  setImageLayerComponentState={setComponentState}
                  guidedTour="createEditModelTrainingModalGuide"
                  autoLaunchGuidedTour={true}
                />
              )
            }
            disabled={item.status !== "Processed" || item.labelProjectCount < 1}
          >
            Train
          </DefaultButton>{" "}
          <Text className="pe-4" variant="small">
            ({item.models && item.models.length > 0 ? item.models.length : 0})
          </Text>
        </td>
        <td className="custom-text-no-wrap d-none d-xl-table-cell">
          <DefaultButton
            id={"singleProjectBuildingValidation" + index}
            className="dashboard-button"
            onClick={() => navigate(`/validation/${projectId}/${item.imageLayerId}`)}
            disabled={!item.buildingFootprintsUrl}
          >
            Launch
          </DefaultButton>{" "}
          <Text className="pe-4" variant="small">
            ({item.validationLabelCount || 0})
          </Text>
        </td>
        <td className=" custom-text-no-wrap d-none d-xxl-table-cell">
          <TooltipHost
            content={item.userId}
            delay={2}
          >
            <Text
              variant="medium"
              className="me-4"
              id={"singleProjectCreator" + index}
            >
              {item.userId !== null ? limitTextLength(item.userId, false, 30) : "User"}
            </Text>
          </TooltipHost>
        </td>
        <td className="custom-text-no-wrap d-none d-xxl-table-cell">
          <Text
            variant="medium"
            className="pe-4"
            id={"singleProjectCreationDate" + index}
          >
            {item.creationDate.substring(0, 10) +
              " " +
              item.creationDate.substring(11, 19)}
          </Text>
        </td>
        <td className=" d-flex align-items-start align-items-md-center justify-content-end ">
          <IconButton
            id={"singleProjectMoreOptions" + index}
            className="no-dropdown-icon"
            menuProps={moreMenuOptions}
            iconProps={{ iconName: "more" }}
            title="Menu"
            ariaLabel="Menu"
          />
        </td>
      </tr>

      {visibleModelId == item.imageLayerId && item.models && item.models.length > 0 && (
        <tr>
          <td
            colSpan={9}
            className="dashboard-table-for-inner-table-td custom-text-no-wrap"
          >
            <table className="col-12 dashboard-inner-table p-3 pb-2 pt-2">
              <tbody>
                {appParams.bootstrapBreakpoint >= 4 ? (
                  <ModelRow
                    models={item.models}
                    imageLayerId={item.imageLayerId}
                    imagerySource={item.sourceTypePostEvent}
                    eventTypes={eventTypes}
                    projectId={projectId}
                    fetchProjectDetails={fetchProjectDetails}
                    setModalComponent={setModalComponent}
                    validationLabelCount={item.validationLabelCount || 0}
                  />
                ) : (
                  <>
                    <ImageLayerInfoMobile
                      item={item}
                      setModalComponent={setModalComponent}
                      fetchProjectDetails={fetchProjectDetails}
                      setComponentState={setComponentState}
                    />
                    <ModelRowMobile
                      models={item.models}
                      imageLayerId={item.imageLayerId}
                      imagerySource={item.sourceTypePostEvent}
                      eventTypes={eventTypes}
                      projectId={projectId}
                      fetchProjectDetails={fetchProjectDetails}
                      setComponentState={setComponentState}
                      setModalComponent={setModalComponent}
                      validationLabelCount={item.validationLabelCount || 0}
                    />
                  </>
                )}
              </tbody>
            </table>
          </td>
        </tr>
      )}
    </React.Fragment>
  );
};

export default LayerRow;
