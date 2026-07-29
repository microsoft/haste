// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import {
  Button,
  Tooltip,
  Menu,
  MenuTrigger,
  MenuPopover,
  MenuList,
  MenuItem,
  OverlayDrawer,
  DrawerHeader,
  DrawerHeaderTitle,
  DrawerBody,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
import PropTypes from "prop-types";
import React, { useContext, useState } from "react";
import { apiDelete } from "../../util/api";
import { limitTextLength } from "../../util/conversion";
import { satellitePlaceholder } from "../../util/satellitePlaceholders";
import { AppContext } from "../../AppContext";
import ModelRow from "./ModelRow";
import StatusIndicatorModal from "../OtherComponents/StatusIndicatorModal";
import CreateEditModelTrainingModal from "../CreateEditModelTrainingModal";
import CreateEditEmbeddingModal from "../CreateEditEmbeddingModal";
import { useNavigate } from "react-router-dom";
import { fileDownload } from "../../util/file";
import { validateTimestamp } from "../../util/validation";

/** Map an image-layer status to a pcard status tone. Mirrors the solid
 *  status colors used by StatusIndicator (.modelStatus-*) in the list view. */
function getLayerStatusTone(status) {
  if (status === "Processed" || status === "Completed") return "processed";
  if (status === "Failed" || status === "Cancelled") return "failed";
  if (status === "InProgress") return "inprogress";
  if (status === "Queued") return "queued";
  if (!status) return "draft";
  return "queued";
}

// Parse a raw statusMessage string into the {timestamp, message} rows that
// StatusIndicatorModal renders. Mirrors the logic in StatusIndicator so the
// card status badge opens the exact same info modal as the list's (i) button.
const STATUS_LABELS_TO_REPLACE = [
  { original: "trainStartTime:", replacement: "Training start time:" },
  { original: "epoch:", replacement: "Epoch: " },
  { original: "elapsedDurationInMinutes:", replacement: "Minutes Elapsed:" },
  {
    original: "approxMinutesToComplete:",
    replacement: "Aprox. minutes to complete: ",
  },
  { original: "completedDate:", replacement: "Completed date:" },
];

function buildStatusMessages(statusMessage) {
  if (!statusMessage) return [];
  let temp = statusMessage;
  STATUS_LABELS_TO_REPLACE.forEach((label) => {
    temp = temp.replace(new RegExp(label.original, "g"), label.replacement);
  });
  return temp.split("\n").map((line) => {
    if (validateTimestamp(line)) {
      return {
        message: line.substring(33),
        timestamp:
          line.substring(0, 10) + ", " + line.substring(11, 19) + " UTC",
      };
    }
    return { message: line, timestamp: "" };
  });
}

const LayerCard = ({
  item,
  index,
  projectId,
  setModalComponent,
  fetchProjectDetails,
  setComponentState,
  eventTypes,
}) => {
  LayerCard.propTypes = {
    item: PropTypes.object.isRequired,
    index: PropTypes.number.isRequired,
    projectId: PropTypes.string.isRequired,
    setModalComponent: PropTypes.func.isRequired,
    fetchProjectDetails: PropTypes.func.isRequired,
    setComponentState: PropTypes.func,
    eventTypes: PropTypes.array.isRequired,
  };

  const navigate = useNavigate();
  const { setIsLoading, setDialog } = useContext(AppContext);
  const [modelsOpen, setModelsOpen] = useState(false);

  // Building labeling workflow: layers created with workflowType "building"
  // get an Embed button instead of the Label/Train actions.
  const isBuildingWorkflow = item.workflowType === "building";
  const embeddingModels =
    (item.models || []).filter((m) => m.modelType === "embedding") || [];

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

  function applyStorageProxy(url) {
    if (url && import.meta.env.VITE_STORAGE_APIM_URL) {
      return url.replace(
        /^https?:\/\/[^/]+/,
        import.meta.env.VITE_STORAGE_APIM_URL
      );
    }
    return url;
  }

  const moreMenuItems = [
    {
      key: "ExportLabelsToGeoJSON",
      text: "Export Labels to GeoJSON",
      icon: <FluentIcon name="Download" />,
      disabled: item.labelsUrl === null,
      onClick: () => {
        if (item.labelsUrl) {
          fileDownload(applyStorageProxy(item.labelsUrl), setDialog);
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
          fileDownload(applyStorageProxy(item.buildingFootprintsUrl), setDialog);
        } else {
          setDialog(
            "Error",
            "No building footprints available for this image layer."
          );
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
          fileDownload(applyStorageProxy(item.validAreaMaskUrl), setDialog);
        } else {
          setDialog(
            "Error",
            "No valid area mask available for this image layer."
          );
        }
      },
    },
    {
      key: "edit",
      text: "Edit",
      icon: <FluentIcon name="Edit" />,
      onClick: () => {
        navigate("/edit-imageLayer/" + projectId + "/" + item.imageLayerId);
      },
    },
    {
      key: "remove",
      text: "Remove",
      icon: <FluentIcon name="Delete" />,
      onClick: () => {
        setDialog(
          "Important",
          `Do you want to remove the image layer "${limitTextLength(
            item.name,
            40,
            40
          )}"?. This will remove all child Labels and Models.`,
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
  ];

  const tone = getLayerStatusTone(item.status);
  const modelCount =
    item.models && item.models.length > 0 ? item.models.length : 0;

  function openStatusInfo() {
    setModalComponent(
      <StatusIndicatorModal
        statusMessages={buildStatusMessages(item.statusMessage)}
        onClose={() => setModalComponent(null)}
      />
    );
  }

  return (
    <div className="pcard pcard--static" id={"singleProjectCard" + index}>
      {/* AOI post-event thumbnail placeholder (imagery wiring pending) */}
      <div
        className="lcard-thumb lcard-thumb--empty"
        style={{
          backgroundImage:
            'url("' +
            satellitePlaceholder(item.imageLayerId, index) +
            '")',
        }}
      >
        {item.statusMessage ? (
          <button
            type="button"
            className={`pcard-status pcard-status--${tone} pcard-status-btn lcard-thumb-status`}
            onClick={openStatusInfo}
            title="Show status messages"
          >
            {item.status || "Draft"}
          </button>
        ) : (
          <span
            className={`pcard-status pcard-status--${tone} lcard-thumb-status`}
          >
            {item.status || "Draft"}
          </span>
        )}
      </div>
      <div className="pcard-top">
        <div className="pcard-title pcard-title--static">
          <FluentIcon name="FileImage" className="pcard-icon" />
          <Tooltip content={item.name} relationship="label">
            <span className="pcard-name" id={"singleProjectName" + index}>
              {limitTextLength(item.name, false, 40)}
            </span>
          </Tooltip>
        </div>
        <div className="pcard-top-right">
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
                {moreMenuItems.map((mi) => (
                  <MenuItem
                    key={mi.key}
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
        </div>
      </div>

      <div className="pcard-stats">
        {isBuildingWorkflow ? (
          <div className="pcard-stat" title="Embeddings">
            <FluentIcon name="ModelingView" className="pcard-stat-icon" />
            {embeddingModels.length}
          </div>
        ) : (
          <>
            <div className="pcard-stat" title="Labeling projects">
              <FluentIcon name="BulletedList" className="pcard-stat-icon" />
              {item.labelProjectCount || 0}
            </div>
            <div className="pcard-stat" title="Models">
              <FluentIcon name="ModelingView" className="pcard-stat-icon" />
              {modelCount}
            </div>
          </>
        )}
        <div className="pcard-stat" title="Validation labels">
          <FluentIcon name="ReportDocument" className="pcard-stat-icon" />
          {item.validationLabelCount || 0}
        </div>
      </div>

      <div className="lcard-actions">
        {isBuildingWorkflow ? (
          <Tooltip
            content="Embed imagery — building labeling workflow"
            relationship="label"
          >
            <Button
              id={"singleProjectEmbed" + index}
              size="small"
              appearance="subtle"
              className="lcard-icon-btn"
              icon={<FluentIcon name="ModelingView" />}
              aria-label="Embed imagery (building labeling workflow)"
              onClick={handleEmbed}
              disabled={
                item.status !== "Processed" || !item.buildingFootprintsUrl
              }
            />
          </Tooltip>
        ) : (
          <>
            <Tooltip
              content="Launch labeling — standard labeling workflow"
              relationship="label"
            >
              <Button
                id={"singleProjectLabelingToolLaunch" + index}
                size="small"
                appearance="subtle"
                className="lcard-icon-btn"
                icon={<FluentIcon name="BulletedList" />}
                aria-label="Launch standard labeling workflow"
                onClick={() =>
                  navigate(`/labeling-tool/${projectId}/${item.imageLayerId}`)
                }
                disabled={item.status !== "Processed"}
              />
            </Tooltip>
            <Tooltip content="Train a model" relationship="label">
              <Button
                id={"singleProjectModelTraining" + index}
                size="small"
                appearance="subtle"
                className="lcard-icon-btn"
                icon={<FluentIcon name="ReleaseDefinition" />}
                aria-label="Train a model"
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
              />
            </Tooltip>
          </>
        )}
        <Tooltip content="Launch building validation" relationship="label">
          <Button
            id={"singleProjectBuildingValidation" + index}
            size="small"
            appearance="subtle"
            className="lcard-icon-btn"
            icon={<FluentIcon name="Checkmark" />}
            aria-label="Launch building validation"
            onClick={() =>
              navigate(`/validation/${projectId}/${item.imageLayerId}`)
            }
            disabled={!item.buildingFootprintsUrl}
          />
        </Tooltip>
        <Tooltip content={`View models (${modelCount})`} relationship="label">
          <Button
            id={"singleProjectViewModels" + index}
            size="small"
            appearance="subtle"
            className="lcard-icon-btn"
            icon={<FluentIcon name="AppsList" />}
            aria-label={`View models (${modelCount})`}
            onClick={() => setModelsOpen(true)}
            disabled={modelCount === 0}
          />
        </Tooltip>
      </div>

      <OverlayDrawer
        position="end"
        open={modelsOpen}
        onOpenChange={(_, { open }) => setModelsOpen(open)}
        className="lcard-models-drawer"
      >
        <DrawerHeader>
          <DrawerHeaderTitle
            action={
              <Button
                appearance="subtle"
                aria-label="Close"
                icon={<FluentIcon name="Cancel" />}
                onClick={() => setModelsOpen(false)}
              />
            }
          >
            <span className="lcard-models-drawer-title">
              <FluentIcon name="ModelingView" />
              Models
              <span className="lmodels-count">{modelCount}</span>
            </span>
          </DrawerHeaderTitle>
        </DrawerHeader>
        <DrawerBody>
          <div className="lmodels-list">
            {modelCount > 0 && (
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
            )}
          </div>
        </DrawerBody>
      </OverlayDrawer>

      <div className="pcard-footer pcard-footer--stacked">
        <span className="pcard-footer-item" title={item.userId}>
          <FluentIcon name="UserEvent" className="pcard-stat-icon" />
          {item.userId ? (
            limitTextLength(item.userId, 24, 40)
          ) : (
            <span className="pgrid-muted">User</span>
          )}
        </span>
        <span className="pcard-footer-item">
          <FluentIcon name="Calendar" className="pcard-stat-icon" />
          {item.creationDate ? item.creationDate.substring(0, 10) : "—"}
        </span>
      </div>
    </div>
  );
};

export default LayerCard;
