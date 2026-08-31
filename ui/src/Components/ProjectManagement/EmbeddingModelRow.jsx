// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Sub-row for a building-embedding model (building labeling workflow).
// Mirrors ModelRow's column layout but exposes an "Interactive Label" action
// (drops into the Azure Maps labeler) and, once predictions have been saved
// (model.gpkgUrl set), the same Validation/Assessment reports as ModelRow.
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
import { useContext, useState } from "react";
import React from "react";
import PropTypes from "prop-types";
import { useNavigate } from "react-router-dom";
import { apiDelete, buildUrl } from "../../util/api";
import { AppContext } from "../../AppContext";
import StatusIndicator from "../OtherComponents/StatusIndicator";
import ValidationReportModal from "../BuildingValidation/ValidationReportModal";
import AssessmentReportModal from "../BuildingValidation/AssessmentReportModal";
import PublishDatasetModal from "../PublishDatasetModal";
import DownloadPredictionsDialog from "../OtherComponents/DownloadPredictionsDialog";
import {
  buildVersionGpkgUrl,
  hasPredictionVersionChoice,
} from "../Visualizer/predictionVersions";
import { fileDownload } from "../../util/file";
import { limitTextLength } from "../../util/conversion";

// Friendly per-row label for the embedding backbone column. The Model schema
// stores ``embeddingModel`` as the raw backbone name passed to the workflow
// (e.g. "mosaiks", "dinov2_vits14"); the display strings here are intentionally
// short — full run parameters are surfaced in the Status Messages info box.
//
// Keep in sync with EMBEDDING_MODEL_OPTIONS in CreateEditEmbeddingModal.jsx
// and build_embedding_model() in hastelib/src/hastegeo/workflows/embed_buildings.py.
const EMBEDDING_MODEL_LABELS = {
  mosaiks: "MOSAIKS",
  dinov2_vits14: "DINOv2 ViT-S/14",
  dinov2_vitb14: "DINOv2 ViT-B/14",
  dinov2_vitl14: "DINOv2 ViT-L/14",
};

function embeddingModelLabel(model) {
  const name = model.embeddingModel || "mosaiks";
  return EMBEDDING_MODEL_LABELS[name] || name;
}

// Run parameters surfaced in the Status Messages info box. MOSAIKS has a
// configurable output dim that is not implied by the backbone label, so it
// gets the extra Number-of-features row; DINOv2 variants have a fixed
// per-variant dim so they don't.
function embeddingInfoMetadata(model) {
  const items = [
    { label: "Embedding model", value: embeddingModelLabel(model) },
  ];
  if ((model.embeddingModel || "mosaiks") === "mosaiks" && model.numFeatures) {
    items.push({ label: "Number of features", value: String(model.numFeatures) });
  }
  if (model.resizeFactor) {
    items.push({ label: "Resize factor", value: `${model.resizeFactor}x` });
  }
  if (model.batchSize) {
    items.push({ label: "Batch size", value: String(model.batchSize) });
  }
  return items;
}

const EmbeddingModelRow = ({
  model,
  projectId,
  imageLayerId,
  index,
  fetchProjectDetails,
  validationLabelCount = 0,
  mobile = false,
}) => {
  const { appParams, setDialog, setIsLoading } = useContext(AppContext);
  const navigate = useNavigate();
  const [showValidationReport, setShowValidationReport] = useState(false);
  const [showAssessmentReport, setShowAssessmentReport] = useState(false);
  const [showPublishDataset, setShowPublishDataset] = useState(false);
  const [showDownloadPredictions, setShowDownloadPredictions] =
    useState(false);

  const isProcessed = model.status === "Processed";
  const hasPredictions = !!model.gpkgUrl;
  // Viewing results opens the visualizer, which is also where predictions are
  // reviewed and edited. `predictionsReady` is the server-derived readiness
  // flag; models saved before it existed fall back to "a GeoPackage exists".
  const canViewResults = model.predictionsReady ?? hasPredictions;
  const viewResultsTooltip =
    "Predict buildings in the Interactive Labeler before viewing results";

  const createdDate = model.creationDate
    ? `${model.creationDate.substring(0, 10)} ${model.creationDate.substring(
        11,
        19
      )}`
    : "";

  async function handleDeletion() {
    setDialog();
    setIsLoading(true, "Removing Embedding...");
    try {
      await apiDelete(
        `DeleteModel?projectId=${projectId}&modelId=${model.modelId}`
      );
      fetchProjectDetails();
    } catch (error) {
      console.error("Error removing embedding:", error);
      setDialog("Error", "There was an error removing the embedding.");
    }
    setIsLoading(false);
  }

  const resultsMenu = {
    items: [
      {
        // Same destination and ordering as the standard workflow's Results
        // menu (ModelResultsButton): View first, downloads/reports after.
        key: "viewResults",
        text: "View",
        icon: <FluentIcon name="Forward" />,
        disabled: !canViewResults,
        tooltip: viewResultsTooltip,
        onClick: () => {
          navigate(
            `/visualizer/${projectId}/${imageLayerId}/${model.modelId}`
          );
        },
      },
      {
        key: "downloadGeopackage",
        text: "Download Geopackage (.gpkg)",
        icon: <FluentIcon name="download" />,
        disabled: !hasPredictions,
        onClick: () => {
          // With saved edits there is a real choice to make, and downloading
          // the raw output silently would throw away the analyst's work.
          if (hasPredictionVersionChoice(model.editedPredictions)) {
            setShowDownloadPredictions(true);
            return;
          }
          // Stream the predictions GeoPackage through the same-origin API
          // (GetModelArtifact) rather than the raw blob URL, so it works for
          // remote labelers behind the storage firewall — matching how the
          // labeler fetches the model's other artifacts.
          fileDownload(
            buildUrl(
              `GetModelArtifact?projectId=${projectId}` +
                `&modelId=${model.modelId}&kind=gpkg`
            ),
            setDialog
          );
        },
      },
      {
        key: "validationReport",
        text: "Validation Report",
        icon: <FluentIcon name="ReportDocument" />,
        // Match the standard workflow (ModelResultsButton): the validation
        // report needs Building Validation labels to compute precision/recall,
        // so it stays disabled until at least one exists.
        disabled: !hasPredictions || !(validationLabelCount > 0),
        onClick: () => setShowValidationReport(true),
      },
      {
        key: "assessmentReport",
        text: "Assessment Report",
        icon: <FluentIcon name="AnalyticsReport" />,
        // Predictions alone (+ cached footprints) are enough for the
        // damage-count estimate; labels are optional, so this only needs
        // predictions — same as the standard workflow.
        disabled: !hasPredictions,
        onClick: () => setShowAssessmentReport(true),
      },
      ...(appParams.publishingEnabled
        ? [
            {
              key: "publishDataset",
              text: "Publish dataset…",
              icon: <FluentIcon name="Upload" />,
              disabled: !isProcessed || !hasPredictions,
              onClick: () => setShowPublishDataset(true),
            },
          ]
        : []),
    ],
  };

  // Rendered identically by the mobile and desktop layouts below. Disabled
  // Fluent menu items stay hoverable/focusable, so a tooltip can explain why
  // an action isn't available yet.
  const renderResultsMenuItems = () =>
    resultsMenu.items.map((mi) => {
      const menuItem = (
        <MenuItem
          key={mi.key}
          icon={mi.icon}
          disabled={mi.disabled}
          onClick={mi.onClick}
        >
          {mi.text}
        </MenuItem>
      );
      return mi.disabled && mi.tooltip ? (
        <Tooltip
          key={mi.key}
          content={mi.tooltip}
          relationship="description"
          withArrow
        >
          {menuItem}
        </Tooltip>
      ) : (
        menuItem
      );
    });

  const moreMenuOptions = {
    items: [
      {
        key: "remove",
        text: "Remove",
        icon: <FluentIcon name="Delete" />,
        onClick: () => {
          setDialog("Important", `Do you want to remove this embedding?`, [
            {
              type: "primary",
              key: "yes",
              text: "Yes",
              onClick: handleDeletion,
            },
            {
              type: "default",
              key: "no",
              text: "No",
              onClick: () => setDialog(),
            },
          ]);
        },
      },
    ],
  };

  const reportModals = (
    <>
      {showDownloadPredictions && (
        <DownloadPredictionsDialog
          versions={model.editedPredictions}
          modelName={model.name}
          onDownload={(version) =>
            fileDownload(
              buildUrl(
                buildVersionGpkgUrl({
                  projectId,
                  imageLayerId,
                  modelId: model.modelId,
                  version,
                })
              ),
              setDialog
            )
          }
          onDismiss={() => setShowDownloadPredictions(false)}
        />
      )}
      {showValidationReport && (
        <ValidationReportModal
          projectId={projectId}
          imageLayerId={imageLayerId}
          modelId={model.modelId}
          modelName={model.name}
          versions={model.editedPredictions}
          onDismiss={() => setShowValidationReport(false)}
        />
      )}
      {showAssessmentReport && (
        <AssessmentReportModal
          projectId={projectId}
          imageLayerId={imageLayerId}
          modelId={model.modelId}
          modelName={model.name}
          versions={model.editedPredictions}
          onDismiss={() => setShowAssessmentReport(false)}
        />
      )}
      {showPublishDataset && (
        <PublishDatasetModal
          projectId={projectId}
          imageLayerId={imageLayerId}
          modelId={model.modelId}
          onDismiss={() => setShowPublishDataset(false)}
          onStarted={() =>
            setDialog(
              "Publishing started",
              "Track progress in Published Datasets.",
              [
                {
                  type: "primary",
                  key: "view",
                  text: "View",
                  onClick: () => {
                    setDialog();
                    navigate("/published-datasets");
                  },
                },
                {
                  type: "default",
                  key: "close",
                  text: "Close",
                  onClick: () => setDialog(),
                },
              ],
            )
          }
        />
      )}
    </>
  );

  // Stacked mobile layout: one field per row with full-width action buttons,
  // mirroring ModelRowMobile's standard-model layout so the embedding list
  // doesn't stay squished into desktop columns on narrow screens.
  if (mobile) {
    return (
      <React.Fragment
        key={"embeddingMobile_" + projectId + "_" + model.modelId}
      >
        <tr>
          <td className="custom-text-no-wrap pt-1">
            <Text size={200}>
              <span className="fw-semibold">Name:</span>{" "}
              <span>{model.name}</span>
            </Text>
          </td>
        </tr>
        <tr>
          <td>
            <Text size={200}>
              <span className="fw-semibold">Model:</span>{" "}
              {embeddingModelLabel(model)}
            </Text>
          </td>
        </tr>
        <tr>
          <td>
            <Text size={200}>
              <span className="fw-semibold">Embedded:</span> {createdDate}
            </Text>
          </td>
        </tr>
        <tr>
          <td className="pe-3 custom-text-no-wrap">
            <Text size={200}>
              <span className="fw-semibold">User:</span>{" "}
              {limitTextLength(model.userId, false, 35)}
            </Text>
          </td>
        </tr>
        <tr>
          <td className="pe-3 custom-text-no-wrap d-flex align-items-center">
            <StatusIndicator
              currentStep={model.currentStep}
              totalSteps={model.totalSteps}
              progressPct={model.progressPct}
              status={model.status}
              statusMessage={model.statusMessage}
              id={`singleEmbeddingStatus${index}`}
              prefix={embeddingModelLabel(model)}
              infoMetadata={embeddingInfoMetadata(model)}
              contextLabel={`Model: ${model.name}`}
            />
          </td>
        </tr>
        <tr>
          <td className="pb-2 pt-2">
            <div className="d-flex align-items-center">
              <Button
                id={"interactiveLabel" + index}
                className="dashboard-button dashboard-button-light"
                onClick={() =>
                  navigate(
                    `/interactive-label/${projectId}/${imageLayerId}/${model.modelId}`
                  )
                }
                disabled={!isProcessed}
              >
                Interactive Label
              </Button>
              <Menu positioning="below-end">
                <MenuTrigger disableButtonEnhancement>
                  <Button
                    appearance="primary"
                    id={"embeddingResults" + index}
                    className="dashboard-button ms-2"
                    disabled={!(hasPredictions || canViewResults)}
                  >
                    Results
                  </Button>
                </MenuTrigger>
                <MenuPopover>
                  <MenuList>{renderResultsMenuItems()}</MenuList>
                </MenuPopover>
              </Menu>
            </div>
          </td>
        </tr>
        <tr className="model-mobile-row">
          <td className="pb-2">
            <Menu positioning="below-end">
              <MenuTrigger disableButtonEnhancement>
                <Button
                  id={`singleEmbeddingMoreOptions${index}`}
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
        {reportModals}
      </React.Fragment>
    );
  }

  return (
    <div className="lmodel">
      <div className="lmodel-info">
        <div className="lmodel-name-row">
          <Tooltip content={model.name} relationship="label">
            <span className="lmodel-name">
              {limitTextLength(model.name, false, 59)}
            </span>
          </Tooltip>
          <span className="lmodel-chip">{embeddingModelLabel(model)}</span>
        </div>
        <div className="lmodel-meta">
          {createdDate && (
            <span>
              <b>Embedded:</b> {createdDate}
            </span>
          )}
          {createdDate && model.userId && (
            <span className="lmodel-meta-sep">&middot;</span>
          )}
          {model.userId && (
            <span>
              <b>User:</b> {limitTextLength(model.userId, false, 35)}
            </span>
          )}
        </div>
      </div>
      <div className="lmodel-status">
        <StatusIndicator
          currentStep={model.currentStep}
          totalSteps={model.totalSteps}
          progressPct={model.progressPct}
          status={model.status}
          statusMessage={model.statusMessage}
          id={`singleEmbeddingStatus${index}`}
          prefix={embeddingModelLabel(model)}
          infoMetadata={embeddingInfoMetadata(model)}
        />
      </div>
      <div className="lmodel-actions">
        <Button
          id={"interactiveLabel" + index}
          className="dashboard-button dashboard-button-light"
          onClick={() =>
            navigate(
              `/interactive-label/${projectId}/${imageLayerId}/${model.modelId}`
            )
          }
          disabled={!isProcessed}
        >
          Interactive Label
        </Button>
        <Menu positioning="below-end">
          <MenuTrigger disableButtonEnhancement>
            <Button
              appearance="primary"
              id={"embeddingResults" + index}
              className="dashboard-button"
              disabled={!(hasPredictions || canViewResults)}
            >
              Results
            </Button>
          </MenuTrigger>
          <MenuPopover>
            <MenuList>{renderResultsMenuItems()}</MenuList>
          </MenuPopover>
        </Menu>
        <Menu positioning="below-end">
          <MenuTrigger disableButtonEnhancement>
            <Button
              id={`singleEmbeddingMoreOptions${index}`}
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
      </div>
      {reportModals}
    </div>
  );
};

EmbeddingModelRow.propTypes = {
  model: PropTypes.object.isRequired,
  projectId: PropTypes.string.isRequired,
  imageLayerId: PropTypes.string.isRequired,
  index: PropTypes.number.isRequired,
  fetchProjectDetails: PropTypes.func.isRequired,
  validationLabelCount: PropTypes.number,
  mobile: PropTypes.bool,
};

export default EmbeddingModelRow;
