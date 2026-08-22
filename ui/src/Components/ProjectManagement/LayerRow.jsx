// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Imports
import {
  Text,
  Tooltip,
  Button,
  Menu,
  MenuTrigger,
  MenuPopover,
  MenuList,
  MenuItem,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
import PropTypes from "prop-types";
import ModelRow from "./ModelRow";
import React, { useContext, useState, useEffect } from "react";
import { apiDelete } from "../../util/api";
import { limitTextLength } from "../../util/conversion";
import { imageLayerThumbnail } from "../../util/satellitePlaceholders";
import { AppContext } from "../../AppContext";
import CreateEditModelTrainingModal from "../CreateEditModelTrainingModal";
import CreateEditEmbeddingModal from "../CreateEditEmbeddingModal";
import ValidationConfigModal from "../BuildingValidation/ValidationConfigModal";
import { useNavigate } from "react-router-dom";
import StatusIndicator from "../OtherComponents/StatusIndicator";
import { fileDownload } from "../../util/file";
import { useImagePreload } from "./useImagePreload";

const LayerRow = ({
  item,
  index,
  visibleModelId,
  projectId,
  columns,
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
    columns: PropTypes.array,
    onComponentChange: PropTypes.func.isRequired,
    setModalComponent: PropTypes.func.isRequired,
    fetchProjectDetails: PropTypes.func.isRequired,
    setComponentState: PropTypes.func,
    eventTypes: PropTypes.array.isRequired
  };
  const navigate = useNavigate();
  const { setIsLoading, appParams } = useContext(AppContext);
  const isCompactLayout = appParams.bootstrapBreakpoint < 4;
  const thumbnailUrl = imageLayerThumbnail(item);
  const { isLoading: isThumbnailLoading, loadedUrl: loadedThumbnailUrl } =
    useImagePreload(thumbnailUrl);

  // Optional columns controlled by the Customize-Columns menu. When no
  // `columns` prop is supplied every optional column is shown.
  const activeColumns = columns || [
    "status",
    "labeling",
    "training",
    "validation",
    "creator",
    "creationDate",
  ];
  const showColumn = (key) => activeColumns.includes(key);


  // Building labeling workflow: layers created with workflowType "building"
  // get an Embed button (kicks off a MOSAIKS embedding job) instead of the
  // Label/Train actions. Everything else (imageryprep, Building Validation)
  // is shared with the standard workflow.
  const isBuildingWorkflow = item.workflowType === "building";
  const embeddingModels =
    (item.models || []).filter((m) => m.modelType === "embedding") || [];
  const hasModels = !!(item.models && item.models.length > 0);
  // Auto-expand when this layer is the "visible" one chosen by the parent:
  // the layer referenced by the URL's imageLayerId, or (when the URL has
  // none) the first layer that has models.
  const [isExpanded, setIsExpanded] = useState(
    hasModels && visibleModelId === item.imageLayerId
  );

  useEffect(() => {
    if (hasModels && visibleModelId === item.imageLayerId) {
      setIsExpanded(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibleModelId, item.imageLayerId]);

  function toggleExpanded() {
    if (hasModels) {
      setIsExpanded((prev) => !prev);
    }
  }

  function handleEmbed() {
    setModalComponent(
      <CreateEditEmbeddingModal
        onClose={() => setModalComponent(null)}
        projectId={projectId}
        imageLayer={item}
        fetchProjectDetails={fetchProjectDetails}
      />
    );
  }

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
        icon: <FluentIcon name="Download" />,
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
        icon: <FluentIcon name="Download" />,
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
        icon: <FluentIcon name="Download" />,
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
        icon: <FluentIcon name="Edit" />,
        onClick: () => {
          setModalComponent(
            navigate("/edit-imageLayer/" + projectId + "/" + item.imageLayerId)
          );
        },
      },
      {
        key: "remove",
        text: "Remove",
        icon: <FluentIcon name="Delete" />,
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
      {/** keep row metadata explicit so mobile CSS can match Projects-style cards */}
      <tr
        className={
          "lrow-main " +
          (hasModels ? "lrow-has-models " : "") +
          (
            isExpanded && hasModels
              ? "lrow-expanded"
              : ""
          )
        }
      >
        <td
          id={"singleProjectExpandCollapseImageLayerModels" + index}
          style={{ width: "32px" }}
          className="align-items-center pgrid-expand-cell"
          data-label=""
        >
          {!isCompactLayout && hasModels && (
            <Button
              appearance="subtle"
              onClick={toggleExpanded}
              aria-label="expand-collapse"
              icon={
                <FluentIcon
                  name={
                    isExpanded
                      ? "ChevronDown"
                      : "ChevronRight"
                  }
                />
              }
            />
          )}
        </td>
        <td
          className={
            "custom-text-no-wrap " +
            (hasModels ? "lrow-name-expandable" : "")
          }
          data-label="Name"
        >
          <div className="lrow-name-cell">
            <span
              className={`lrow-thumb ${loadedThumbnailUrl ? "lrow-thumb--image" : "lrow-thumb--empty"}`}
              role="img"
              aria-label={loadedThumbnailUrl ? "Post-event imagery" : "No imagery available"}
              style={
                loadedThumbnailUrl
                  ? { backgroundImage: `url("${loadedThumbnailUrl}")` }
                  : undefined
              }
            >
              {isThumbnailLoading ? (
                <span className="thumbnail-preloader" role="status" aria-label="Loading imagery" />
              ) : !loadedThumbnailUrl && (
                <span className="no-image-icon" aria-hidden="true">
                  <FluentIcon name="FileImage" />
                </span>
              )}
            </span>
            <span
              className="me-4"
              id={"singleProjectName" + index}
            >
              {isCompactLayout ? (
                <span>{limitTextLength(item.name, false, 45)}</span>
              ) : (
                <Tooltip content={item.name} relationship="label">
                  <span>{limitTextLength(item.name, false, 45)}</span>
                </Tooltip>
              )}
            </span>
          </div>
        </td>
        {showColumn("status") && (
          <td className="custom-text-no-wrap" data-label="Status">
            <StatusIndicator
              id={"singleProjectImageLayerStatus" + index}
              currentStep={item.currentStep}
              totalSteps={item.totalSteps}
              progressPct={item.progressPct}
              status={item.status}
              statusMessage={item.statusMessage}
              prefix="Imagery"
              contextLabel={`Image Layer: ${item.name}`}
            />
          </td>
        )}
        {showColumn("labeling") && (
          <td className="pgrid-action-cell" data-label="Labeling">
            {isBuildingWorkflow ? (
              <>
                <Button
                  id={"singleProjectEmbed" + index}
                  className="dashboard-button dashboard-button-light"
                  onClick={handleEmbed}
                  disabled={
                    item.status !== "Processed" || !item.buildingFootprintsUrl
                  }
                >
                  Embed
                </Button>{" "}
                <Text className="pgrid-action-count" size={200}>
                  ({embeddingModels.length})
                </Text>
              </>
            ) : (
              <>
                <Button
                  id={"singleProjectLabelingToolLaunch" + index}
                  className="dashboard-button dashboard-button-light"
                  onClick={() =>
                    navigate(`/labeling-tool/${projectId}/${item.imageLayerId}`)
                  }
                  disabled={item.status !== "Processed"}
                >
                  Launch
                </Button>{" "}
                <Text className="pgrid-action-count" size={200}>
                  ({item.labelProjectCount})
                </Text>
              </>
            )}
          </td>
        )}
        {showColumn("training") && (
          <td className="pgrid-action-cell" data-label="Model Training">
            {isBuildingWorkflow ? (
              <Text className="pgrid-action-count" size={200}>
                &mdash;
              </Text>
            ) : (
              <>
                <Button
                  id={"singleProjectModelTraining" + index}
                  className="dashboard-button dashboard-button-light"
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
                        eventTypes={eventTypes}
                      />
                    )
                  }
                  disabled={
                    item.status !== "Processed" || item.labelProjectCount < 1
                  }
                >
                  Train
                </Button>{" "}
                <Text className="pgrid-action-count" size={200}>
                  (
                  {item.models && item.models.length > 0
                    ? item.models.length
                    : 0}
                  )
                </Text>
              </>
            )}
          </td>
        )}
        {showColumn("validation") && (
          <td className="pgrid-action-cell" data-label="Building Validation">
            <Button
              id={"singleProjectBuildingValidation" + index}
              className="dashboard-button dashboard-button-light"
              onClick={() => navigate(`/validation/${projectId}/${item.imageLayerId}`)}
              disabled={!item.buildingFootprintsUrl}
            >
              Launch
            </Button>{" "}
            <Tooltip content="Building Validation settings" relationship="label">
              <Button
                id={"singleProjectBuildingValidationConfig" + index}
                appearance="subtle"
                icon={<FluentIcon name="Settings" />}
                disabled={!item.buildingFootprintsUrl}
                onClick={() =>
                  setModalComponent(
                    <ValidationConfigModal
                      projectId={projectId}
                      imageLayerId={item.imageLayerId}
                      onClose={() => setModalComponent(null)}
                      onCleared={fetchProjectDetails}
                    />
                  )
                }
              />
            </Tooltip>{" "}
            <Text className="pgrid-action-count" size={200}>
              ({item.validationLabelCount || 0})
            </Text>
          </td>
        )}
        {showColumn("creator") && (
          <td className="custom-text-no-wrap" data-label="Creator">
            <Tooltip
              content={item.userId}
              relationship="label"
            >
              <span
                className="me-4"
                id={"singleProjectCreator" + index}
              >
                {item.userId !== null ? limitTextLength(item.userId, false, 30) : "User"}
              </span>
            </Tooltip>
          </td>
        )}
        {showColumn("creationDate") && (
          <td className="custom-text-no-wrap" data-label="Creation Date">
            <span
              className="pe-4"
              id={"singleProjectCreationDate" + index}
            >
              {item.creationDate.substring(0, 10) +
                " " +
                item.creationDate.substring(11, 19)}
            </span>
          </td>
        )}
        {isCompactLayout && (
          <td className="pgrid-action-cell" data-label="Models">
            <Button
              id={"singleProjectViewModels" + index}
              className="dashboard-button dashboard-button-light"
              onClick={toggleExpanded}
              disabled={!hasModels}
            >
              {isExpanded ? "Hide models" : "View models"}
            </Button>{" "}
            <Text className="pgrid-action-count" size={200}>
              ({hasModels ? item.models.length : 0})
            </Text>
          </td>
        )}
        <td className="pgrid-td-numeric" data-label="">
          <Menu positioning="below-end">
            <MenuTrigger disableButtonEnhancement>
              <Button
                id={"singleProjectMoreOptions" + index}
                appearance="subtle"
                className="no-dropdown-icon"
                icon={<FluentIcon name="More" />}
                title="Menu"
                aria-label="Menu"
              />
            </MenuTrigger>
            <MenuPopover>
              <MenuList>
                {moreMenuOptions.items.map((mi) => (
                  <MenuItem
                    key={mi.key}
                    className={mi.className}
                    icon={mi.icon}
                    disabled={mi.disabled}
                    onClick={mi.onClick}
                  >
                    {mi.text}
                  </MenuItem>
                ))}
              </MenuList>
            </MenuPopover>
          </Menu>
        </td>
      </tr>

      {isExpanded && hasModels && (
        <tr className="lrow-models-row">
          <td
            colSpan={activeColumns.length + 3}
            className="custom-text-no-wrap pgrid-nested-td"
          >
            <div className="lmodels">
              <div className="lmodels-list">
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
              </div>
            </div>
          </td>
        </tr>
      )}
    </React.Fragment>
  );
};

export default LayerRow;
