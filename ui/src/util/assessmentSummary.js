const formatPercent = (value) =>
  value == null ? "—" : `${(value * 100).toFixed(1)}%`;

const formatInteger = (value) =>
  value == null ? "—" : Math.round(value).toLocaleString();


export function buildAssessmentSummary(report) {
  const predictions = report?.predictions;
  if (!predictions) return "";

  if (predictions.total === 0) {
    return "There are no building footprints in the results, so no damage rate or validation metrics can be reported.";
  }

  let summary =
    `Out of a total of ${formatInteger(predictions.total)} building footprints in the results, ` +
    `${formatInteger(predictions.cloudy)} were excluded because of cloud or unknown coverage.`;

  if ((predictions.unscored ?? 0) > 0) {
    summary +=
      ` ${formatInteger(predictions.unscored)} had no observation (outside coverage or NoData) and were excluded.`;
  }

  if (predictions.knownNonCloudy === 0) {
    return summary + " No scored, non-cloudy observations are available, so no damage rate or validation metrics can be reported.";
  }

  summary +=
    ` Among the ${formatInteger(predictions.knownNonCloudy)} non-cloudy footprints with observations, the model ` +
    `predicted that ${formatInteger(predictions.predictedDamaged)} ` +
    `(${predictions.predictedDamagedPctOfKnown ?? 0}%) were damaged to some extent.`;

  if ((report.matched ?? 0) <= 0) {
    if ((report.totalLabels ?? 0) > 0) {
      return summary + " No human validation labels could be matched to scored predictions for this run; accuracy, precision, and recall are unavailable.";
    }
    return (
      summary +
      " No human validation labels are available for this image layer yet — " +
      "labeling some via the Building Validation tool will populate the " +
      "metrics and population estimate."
    );
  }

  summary +=
    ` We independently labeled ${formatInteger(report.totalLabels)} footprints; ` +
    `${formatInteger(report.sureLabels)} were sure-labeled. Estimated recall ` +
    `${formatPercent(report.metrics?.recall)} and precision ` +
    `${formatPercent(report.metrics?.precision)}.`;

  const population = report.populationEstimate;
  if (population && population.N > 0) {
    summary +=
      ` Extrapolating to all ${formatInteger(population.N)} buildings with area > ` +
      `${population.minAreaM2.toFixed(0)} m², we estimate ` +
      `${formatInteger(population.estimatedDamaged)} damaged buildings ` +
      `(${formatPercent(population.pHat)}) with a 95% CI of ` +
      `[${formatInteger(population.ciLower)}, ${formatInteger(population.ciUpper)}].`;
  }
  return summary;
}