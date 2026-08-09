const formatPercent = (value) =>
  value == null ? "—" : `${(value * 100).toFixed(1)}%`;

const formatInteger = (value) =>
  value == null ? "—" : Math.round(value).toLocaleString();


export function buildAssessmentSummary(report) {
  const predictions = report?.predictions;
  if (!predictions) return "";

  let summary =
    `Out of a total of ${formatInteger(predictions.total)} building footprints in the study area, ` +
    `${formatInteger(predictions.cloudy)} were obscured by clouds; of the remaining ` +
    `${formatInteger(predictions.knownNonCloudy)} non-cloudy footprints, the model ` +
    `predicted that ${formatInteger(predictions.predictedDamaged)} ` +
    `(${predictions.predictedDamagedPctOfKnown ?? 0}%) were damaged to some extent.`;

  if ((report.matched ?? 0) <= 0) {
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