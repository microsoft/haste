// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
export function precisionRecallPresentation(report) {
  const curve = report?.precisionRecallCurve;
  const point = (report?.predictionVersion ?? 0) > 0 || curve?.mode === "operating_point";
  const precision = curve?.precision || [];
  const recall = curve?.recall || [];
  const valid = precision.length === recall.length &&
    [...precision, ...recall].every((value) => Number.isFinite(value) && value >= 0 && value <= 1) &&
    (!point || precision.length === 1);
  return {
    mode: point ? "operating_point" : "curve",
    precision: valid ? precision : [],
    recall: valid ? recall : [],
    averagePrecision: (report?.predictionVersion ?? 0) > 0 ? null : report?.metrics?.averagePrecision,
  };
}
