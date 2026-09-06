// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useContext, useEffect, useMemo, useState } from "react";
import PropTypes from "prop-types";
import {
  Button, Menu, MenuTrigger, MenuPopover, MenuList, MenuItem, Tooltip,
} from "@fluentui/react-components";
import { useNavigate } from "react-router-dom";
import { AppContext } from "../../AppContext";
import { buildUrl } from "../../util/api";
import { FluentIcon } from "../../util/icons";
import ValidationReportModal from "../BuildingValidation/ValidationReportModal";
import AssessmentReportModal from "../BuildingValidation/AssessmentReportModal";
import DownloadPredictionsDialog from "../OtherComponents/DownloadPredictionsDialog";
import PublishDatasetModal from "../PublishDatasetModal";
import { buildRawGpkgUrl, buildVisualizerResultsUrl } from "../Visualizer/predictionResults.js";
import { currentPredictionRevision, modelResultsItems } from "./ModelResultsMenuHelper.js";
import { createModelResultsDownload } from "./ModelResultsDownloadHelper.js";

// Common results actions only. Row layout, ZIP downloads and job-status
// indicators stay with their workflow. Version discovery and report/download
// modals belong here, not in either row.
export default function ModelResultsMenu({
  model, projectId, imageLayerId, workflow, validationLabelCount,
  buttonId, className, artifactItems,
}) {
  const { appParams, setDialog } = useContext(AppContext);
  const navigate = useNavigate();
  const [modal, setModal] = useState(null);
  const modelId = model.modelId;
  const ids = { projectId, imageLayerId, modelId };
  const routeKey = `${projectId}/${imageLayerId}/${modelId}`;
  const currentRevision = currentPredictionRevision(model);
  const [downloadState, setDownloadState] = useState(null);
  const downloadOperation = useMemo(() => createModelResultsDownload({
    rawUrl: buildUrl(buildRawGpkgUrl({ projectId, imageLayerId, modelId })),
    onChooseVersion: () => setModal("download"),
    onChange: (next) => setDownloadState({ routeKey, ...next }),
  }), [projectId, imageLayerId, modelId, routeKey]);
  useEffect(() => () => downloadOperation.cancel(), [downloadOperation]);
  const dismiss = () => setModal(null);
  const items = modelResultsItems({
    model, workflow, validationLabelCount, artifactItems,
    publishingEnabled: appParams.publishingEnabled,
    downloading: downloadState?.routeKey === routeKey && !!downloadState.loading,
    onView: () => navigate(`/visualizer/${projectId}/${imageLayerId}/${model.modelId}`),
    onDownload: async () => {
      const outcome = await downloadOperation.run(buildUrl(buildVisualizerResultsUrl(ids)));
      if (outcome.error) setDialog("Download failed", outcome.error);
    },
    openModal: setModal,
  });

  return (
    <>
      <Menu positioning="below-end">
        <MenuTrigger disableButtonEnhancement>
          <Button appearance="primary" id={buttonId} className={className}
            disabled={items.every((item) => item.disabled)}>
            Results
          </Button>
        </MenuTrigger>
        <MenuPopover>
          <MenuList>
            {items.map((item) => {
              const menuItem = (
                <MenuItem key={item.key} icon={<FluentIcon name={item.icon} />}
                  disabled={item.disabled} onClick={item.onClick}>
                  {item.text}
                </MenuItem>
              );
              return item.disabled && item.tooltip ? (
                <Tooltip key={item.key} content={item.tooltip} relationship="description" withArrow>
                  {menuItem}
                </Tooltip>
              ) : menuItem;
            })}
          </MenuList>
        </MenuPopover>
      </Menu>
      {modal === "download" && (
        <DownloadPredictionsDialog {...ids} modelName={model.name}
          currentRevision={currentRevision} onDismiss={dismiss} />
      )}
      {modal === "validation" && (
        <ValidationReportModal {...ids} modelName={model.name}
          currentRevision={currentRevision} onDismiss={dismiss} />
      )}
      {modal === "assessment" && (
        <AssessmentReportModal {...ids} modelName={model.name}
          currentRevision={currentRevision} onDismiss={dismiss} />
      )}
      {modal === "publish" && (
        <PublishDatasetModal {...ids} onDismiss={dismiss}
          onStarted={() => setDialog(
            "Publishing started",
            "Track progress in Published Datasets.",
            [
              {
                type: "primary", key: "view", text: "View",
                onClick: () => { setDialog(); navigate("/published-datasets"); },
              },
              {
                type: "default", key: "close", text: "Close",
                onClick: () => setDialog(),
              },
            ],
          )}
        />
      )}
    </>
  );
}

ModelResultsMenu.propTypes = {
  model: PropTypes.object.isRequired,
  projectId: PropTypes.string.isRequired,
  imageLayerId: PropTypes.string.isRequired,
  workflow: PropTypes.oneOf(["inference", "embedding"]).isRequired,
  validationLabelCount: PropTypes.number,
  buttonId: PropTypes.string,
  className: PropTypes.string,
  artifactItems: PropTypes.arrayOf(PropTypes.object),
};
