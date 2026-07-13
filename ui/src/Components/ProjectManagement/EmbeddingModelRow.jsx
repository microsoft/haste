// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Sub-row for a building-embedding model (building labeling workflow).
// Mirrors ModelRow's column layout but exposes an "Interactive Label" action
// (drops into the Azure Maps labeler) and, once predictions have been saved
// (model.gpkgUrl set), the same Validation/Assessment reports as ModelRow.
import {
  DefaultButton,
  IconButton,
  PrimaryButton,
  Text,
  TooltipHost,
} from "@fluentui/react";
import { useContext, useState } from "react";
import React from "react";
import PropTypes from "prop-types";
import { useNavigate } from "react-router-dom";
import { apiDelete, buildUrl } from "../../util/api";
import { AppContext } from "../../AppContext";
import StatusIndicator from "../OtherComponents/StatusIndicator";
import ValidationReportModal from "../BuildingValidation/ValidationReportModal";
import AssessmentReportModal from "../BuildingValidation/AssessmentReportModal";
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
  EmbeddingModelRow.propTypes = {
    model: PropTypes.object.isRequired,
    projectId: PropTypes.string.isRequired,
    imageLayerId: PropTypes.string.isRequired,
    index: PropTypes.number.isRequired,
    fetchProjectDetails: PropTypes.func.isRequired,
    validationLabelCount: PropTypes.number,
    mobile: PropTypes.bool,
  };

  const { setDialog, setIsLoading } = useContext(AppContext);
  const navigate = useNavigate();
  const [showValidationReport, setShowValidationReport] = useState(false);
  const [showAssessmentReport, setShowAssessmentReport] = useState(false);

  const isProcessed = model.status === "Processed";
  const hasPredictions = !!model.gpkgUrl;
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
        key: "downloadGeopackage",
        text: "Download Geopackage (.gpkg)",
        iconProps: { iconName: "download" },
        disabled: !hasPredictions,
        onClick: () => {
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
        iconProps: { iconName: "ReportDocument" },
        // Match the standard workflow (ModelResultsButton): the validation
        // report needs Building Validation labels to compute precision/recall,
        // so it stays disabled until at least one exists.
        disabled: !hasPredictions || !(validationLabelCount > 0),
        onClick: () => setShowValidationReport(true),
      },
      {
        key: "assessmentReport",
        text: "Assessment Report",
        iconProps: { iconName: "AnalyticsReport" },
        // Predictions alone (+ cached footprints) are enough for the
        // damage-count estimate; labels are optional, so this only needs
        // predictions — same as the standard workflow.
        disabled: !hasPredictions,
        onClick: () => setShowAssessmentReport(true),
      },
    ],
  };

  const moreMenuOptions = {
    items: [
      {
        key: "remove",
        text: "Remove",
        iconProps: { iconName: "Delete" },
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
      {showValidationReport && (
        <ValidationReportModal
          projectId={projectId}
          imageLayerId={imageLayerId}
          modelId={model.modelId}
          modelName={model.name}
          onDismiss={() => setShowValidationReport(false)}
        />
      )}
      {showAssessmentReport && (
        <AssessmentReportModal
          projectId={projectId}
          imageLayerId={imageLayerId}
          modelId={model.modelId}
          modelName={model.name}
          onDismiss={() => setShowAssessmentReport(false)}
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
            <Text variant="small">
              <span className="fw-semibold">Name:</span>{" "}
              <span>{model.name}</span>
            </Text>
          </td>
        </tr>
        <tr>
          <td>
            <Text variant="small">
              <span className="fw-semibold">Model:</span>{" "}
              {embeddingModelLabel(model)}
            </Text>
          </td>
        </tr>
        <tr>
          <td>
            <Text variant="small">
              <span className="fw-semibold">Embedded:</span> {createdDate}
            </Text>
          </td>
        </tr>
        <tr>
          <td className="pe-3 custom-text-no-wrap">
            <Text variant="small">
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
            />
          </td>
        </tr>
        <tr>
          <td className="pb-2 pt-2">
            <div className="d-flex align-items-center">
              <DefaultButton
                id={"interactiveLabel" + index}
                className="dashboard-button"
                onClick={() =>
                  navigate(
                    `/interactive-label/${projectId}/${imageLayerId}/${model.modelId}`
                  )
                }
                disabled={!isProcessed}
              >
                Interactive Label
              </DefaultButton>
              <PrimaryButton
                id={"embeddingResults" + index}
                text="Results"
                menuProps={resultsMenu}
                allowDisabledFocus
                className="dashboard-button ms-2"
                disabled={!hasPredictions}
              />
            </div>
          </td>
        </tr>
        <tr className="model-mobile-row">
          <td className="pb-2">
            <IconButton
              id={`singleEmbeddingMoreOptions${index}`}
              className="no-dropdown-icon"
              menuProps={moreMenuOptions}
              iconProps={{ iconName: "more" }}
              title="Menu"
              ariaLabel="Menu"
            />
          </td>
        </tr>
        {reportModals}
      </React.Fragment>
    );
  }

  return (
    <tr>
      <td className="pe-3 custom-text-no-wrap">
        <TooltipHost content={model.name} delay={2}>
          <Text variant="small">
            <span>{limitTextLength(model.name, false, 59)}</span>
          </Text>
        </TooltipHost>
      </td>
      <td className="pe-3 custom-text-no-wrap d-none d-xxl-table-cell">
        <Text variant="small">
          <span className="fw-semibold">Embedded:</span> {createdDate}
        </Text>
      </td>
      <td className="pe-3 custom-text-no-wrap d-none d-xxl-table-cell">
        <Text variant="small">
          <span className="fw-semibold">User: </span>
          {limitTextLength(model.userId, false, 35)}
        </Text>
      </td>
      <td className="pe-3 custom-text-no-wrap">
        <Text variant="medium">{embeddingModelLabel(model)}</Text>
      </td>
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
        />
      </td>
      <td className="pe-3 custom-text-no-wrap">
        <div className="d-flex align-items-center pt-1 pb-1">
          <DefaultButton
            id={"interactiveLabel" + index}
            className="dashboard-button"
            onClick={() =>
              navigate(
                `/interactive-label/${projectId}/${imageLayerId}/${model.modelId}`
              )
            }
            disabled={!isProcessed}
          >
            Interactive Label
          </DefaultButton>{" "}
          <PrimaryButton
            id={"embeddingResults" + index}
            text="Results"
            menuProps={resultsMenu}
            allowDisabledFocus
            className="dashboard-button ms-2"
            disabled={!hasPredictions}
          />
        </div>
      </td>
      <td>
        <IconButton
          id={`singleEmbeddingMoreOptions${index}`}
          className="no-dropdown-icon"
          menuProps={moreMenuOptions}
          iconProps={{ iconName: "more" }}
          title="Menu"
          ariaLabel="Menu"
        />
      </td>
      {reportModals}
    </tr>
  );
};

export default EmbeddingModelRow;
