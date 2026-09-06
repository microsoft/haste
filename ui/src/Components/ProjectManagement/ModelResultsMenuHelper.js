// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { canViewResults, readinessDetail } from "../Visualizer/predictionResults.js";

// Raw downloads/reports must not depend on vector tiles or attributes. Prefer
// the server's readiness flag; older cached rows may only carry a GeoPackage.
export function hasRawPredictions(model) {
  return model.rawPredictionsReady ??
    (!!model.gpkgUrl && model.buildingCount !== 0 && !(model.predictionVersion > 0));
}

// Row projections use editedPredictions; the Visualizer uses predictionVersions.
// Prefer canonical readiness, retaining compatibility with older cached rows.
export function savedPredictionVersions(model) {
  return model.predictionVersions ?? model.editedPredictions ?? [];
}

export function hasEditedPredictions(model) {
  return model.hasEditedPredictions ?? (
    model.hasEdits === true || model.predictionVersion > 0 ||
    savedPredictionVersions(model).some((entry) => !!entry.gpkgUrl)
  );
}

export function currentPredictionRevision(model) {
  return model.currentPredictionRevision ?? model.predictionRevision;
}

export function modelResultsItems({
  model, workflow, validationLabelCount = 0, publishingEnabled = false,
  downloading = false, artifactItems = [], onView, onDownload, openModal,
}) {
  const rawReady = hasRawPredictions(model);
  const editedReady = hasEditedPredictions(model);
  const viewReady = canViewResults(model) ||
    (editedReady && savedPredictionVersions(model).some(canViewResults));
  const completed = workflow === "embedding"
    ? model.status === "Processed"
    : model.inferenceStatus === "Processed";
  // Keep the existing reporting semantics: standard reports can provide a
  // partial assessment after inference; embedding reports require predictions.
  const reportReady = (workflow === "embedding" ? rawReady : completed) || editedReady;
  return [
    {
      key: "viewResults", text: "View", icon: "Forward",
      disabled: !viewReady, tooltip: readinessDetail(model),
      onClick: onView,
    },
    {
      key: "downloadGeopackage", text: "Download Geopackage (.gpkg)", icon: "download",
      disabled: (!rawReady && !editedReady) || downloading, onClick: onDownload,
    },
    ...artifactItems,
    {
      key: "validationReport", text: "Validation Report", icon: "ReportDocument",
      disabled: !reportReady || !(validationLabelCount > 0),
      onClick: () => openModal("validation"),
    },
    {
      key: "assessmentReport", text: "Assessment Report", icon: "AnalyticsReport",
      disabled: !reportReady, onClick: () => openModal("assessment"),
    },
    ...(publishingEnabled ? [{
      key: "publishDataset", text: "Publish dataset…", icon: "Upload",
      disabled: !completed || !rawReady || !model.gpkgUrl,
      onClick: () => openModal("publish"),
    }] : []),
  ];
}
