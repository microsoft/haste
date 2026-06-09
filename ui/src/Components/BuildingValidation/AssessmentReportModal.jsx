// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useEffect, useState } from "react";
import { Dialog, DialogType, DialogFooter } from "@fluentui/react/lib/Dialog";
import { DefaultButton, Spinner, SpinnerSize, Text } from "@fluentui/react";
import PropTypes from "prop-types";
import { apiGet } from "../../util/api";

// ─── Small presentational helpers ─────────────────────────────────────────

const pct = (v) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);
const int = (v) => (v == null ? "—" : Math.round(v).toLocaleString());
const num = (v, d = 4) => (v == null ? "—" : Number(v).toFixed(d));

const MetricRow = ({ label, value }) => (
  <tr>
    <td style={{ padding: "4px 12px 4px 0", fontWeight: 500, color: "#444" }}>
      {label}
    </td>
    <td style={{ padding: "4px 0", fontFamily: "monospace" }}>{value}</td>
  </tr>
);
MetricRow.propTypes = {
  label: PropTypes.string.isRequired,
  value: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
};

// ─── Precision-recall sparkline (no extra deps; tiny inline SVG) ──────────

const PrecisionRecallChart = ({ precision, recall }) => {
  if (!precision || !recall || precision.length === 0) return null;
  const w = 360;
  const h = 200;
  const pad = 28;
  const xScale = (r) => pad + r * (w - 2 * pad);
  const yScale = (p) => h - pad - p * (h - 2 * pad);
  // recall/precision arrive from the server in PR-curve order (descending
  // threshold); for a clean monotone-ish polyline, sort by ascending recall.
  const points = recall
    .map((r, i) => [r, precision[i]])
    .sort((a, b) => a[0] - b[0])
    .map(([r, p]) => `${xScale(r).toFixed(1)},${yScale(p).toFixed(1)}`)
    .join(" ");
  const ticks = [0, 0.25, 0.5, 0.75, 1.0];
  return (
    <svg
      width={w}
      height={h}
      role="img"
      aria-label="Precision-recall curve"
      style={{ border: "1px solid #dee2e6", borderRadius: 4 }}
    >
      {/* Axes */}
      <line x1={pad} y1={h - pad} x2={w - pad} y2={h - pad} stroke="#999" />
      <line x1={pad} y1={pad} x2={pad} y2={h - pad} stroke="#999" />
      {/* Gridlines + tick labels */}
      {ticks.map((t) => (
        <g key={`x-${t}`}>
          <line
            x1={xScale(t)}
            y1={pad}
            x2={xScale(t)}
            y2={h - pad}
            stroke="#eee"
          />
          <text
            x={xScale(t)}
            y={h - pad + 12}
            fontSize="10"
            fill="#666"
            textAnchor="middle"
          >
            {t.toFixed(2)}
          </text>
        </g>
      ))}
      {ticks.map((t) => (
        <g key={`y-${t}`}>
          <line
            x1={pad}
            y1={yScale(t)}
            x2={w - pad}
            y2={yScale(t)}
            stroke="#eee"
          />
          <text
            x={pad - 4}
            y={yScale(t) + 3}
            fontSize="10"
            fill="#666"
            textAnchor="end"
          >
            {t.toFixed(2)}
          </text>
        </g>
      ))}
      <text
        x={w / 2}
        y={h - 4}
        fontSize="11"
        fill="#444"
        textAnchor="middle"
      >
        Recall (damaged)
      </text>
      <text
        x={10}
        y={h / 2}
        fontSize="11"
        fill="#444"
        textAnchor="middle"
        transform={`rotate(-90 10 ${h / 2})`}
      >
        Precision (damaged)
      </text>
      <polyline
        points={points}
        fill="none"
        stroke="#0078D4"
        strokeWidth="1.5"
      />
    </svg>
  );
};
PrecisionRecallChart.propTypes = {
  precision: PropTypes.arrayOf(PropTypes.number),
  recall: PropTypes.arrayOf(PropTypes.number),
};

// ─── Modal ────────────────────────────────────────────────────────────────

const AssessmentReportModal = ({
  projectId,
  imageLayerId,
  modelId,
  modelName,
  onDismiss,
}) => {
  AssessmentReportModal.propTypes = {
    projectId: PropTypes.string.isRequired,
    imageLayerId: PropTypes.string.isRequired,
    modelId: PropTypes.string.isRequired,
    modelName: PropTypes.string,
    onDismiss: PropTypes.func.isRequired,
  };

  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    apiGet(
      `GetAssessmentReport?projectId=${projectId}&imageLayerId=${imageLayerId}&modelId=${modelId}`
    )
      .then((data) => {
        if (data && data.error && !data.predictions) {
          // Hard error from the server (no inference / no footprints).
          setError(data.error);
        } else {
          setReport(data);
        }
      })
      .catch(() => setError("Failed to load assessment report."))
      .finally(() => setLoading(false));
  }, [projectId, imageLayerId, modelId]);

  const preds = report?.predictions;
  const pop = report?.populationEstimate;
  const metrics = report?.metrics;
  const sample = report?.evaluationSample;
  const hasLabels = (report?.matched ?? 0) > 0;

  // One-paragraph summary, modeled on the CLI script.
  const summarySentence =
    report && preds
      ? `Out of a total of ${int(preds.total)} building footprints in the study area, ` +
        `${int(preds.cloudy)} were obscured by clouds; of the remaining ` +
        `${int(preds.knownNonCloudy)} non-cloudy footprints, the model ` +
        `predicted that ${int(preds.predictedDamaged)} ` +
        `(${preds.predictedDamagedPctOfKnown ?? 0}%) were damaged to some extent.` +
        (hasLabels
          ? ` We independently labeled ${int(report.totalLabels)} footprints; ` +
            `${int(report.sureLabels)} were sure-labeled. Estimated recall ` +
            `${pct(metrics?.recall)} and precision ${pct(metrics?.precision)}. ` +
            (pop && pop.N > 0
              ? `Extrapolating to all ${int(pop.N)} buildings with area > ` +
                `${pop.minAreaM2.toFixed(0)} m², we estimate ` +
                `${int(pop.estimatedDamaged)} damaged buildings ` +
                `(${pct(pop.pHat)}) with a 95% CI of ` +
                `[${int(pop.ciLower)}, ${int(pop.ciUpper)}].`
              : "")
          : " No human validation labels are available for this image layer yet — labeling some via the Building Validation tool will populate the metrics and population estimate.");

  return (
    <Dialog
      hidden={false}
      onDismiss={onDismiss}
      dialogContentProps={{
        type: DialogType.largeHeader,
        title: `Assessment Report — ${modelName || modelId}`,
        subText: loading ? "Computing…" : error ? error : summarySentence,
      }}
      modalProps={{ isBlocking: false }}
      minWidth={620}
    >
      {loading && (
        <div style={{ padding: "24px 0", textAlign: "center" }}>
          <Spinner size={SpinnerSize.large} label="Computing assessment…" />
        </div>
      )}

      {!loading && error && (
        <div style={{ padding: "16px 0", color: "#a4000f" }}>
          <Text>{error}</Text>
        </div>
      )}

      {!loading && report && !error && (
        <div style={{ padding: "4px 0 16px" }}>
          {/* Predictions section */}
          <Text
            variant="mediumPlus"
            style={{ fontWeight: 600, display: "block", marginBottom: 8 }}
          >
            Predictions
          </Text>
          <table style={{ marginBottom: 16 }}>
            <tbody>
              <MetricRow label="Buildings with a prediction" value={int(preds.total)} />
              <MetricRow label="Non-cloudy" value={int(preds.knownNonCloudy)} />
              <MetricRow label="Cloud-covered (excluded)" value={int(preds.cloudy)} />
              <MetricRow
                label={`Predicted damaged (> ${report.threshold})`}
                value={`${int(preds.predictedDamaged)} (${preds.predictedDamagedPctOfKnown ?? 0}% of non-cloudy)`}
              />
            </tbody>
          </table>

          {/* Population estimate */}
          <Text
            variant="mediumPlus"
            style={{ fontWeight: 600, display: "block", marginBottom: 8 }}
          >
            Damaged-building population estimate
          </Text>
          <table style={{ marginBottom: 16 }}>
            <tbody>
              <MetricRow
                label={`N (buildings with area > ${pop?.minAreaM2?.toFixed(0)} m²)`}
                value={int(pop?.N)}
              />
              <MetricRow label="Sample size (n)" value={int(pop?.n)} />
              <MetricRow label="Damaged in sample (x)" value={int(pop?.x)} />
              <MetricRow label="Sample damage rate (p̂)" value={pct(pop?.pHat)} />
              <MetricRow label="Sampling fraction (n/N)" value={num(pop?.samplingFraction, 6)} />
              <MetricRow label="Std. error of p̂" value={num(pop?.sePHat, 6)} />
              <MetricRow
                label="Estimated damaged buildings (Ŷ)"
                value={int(pop?.estimatedDamaged)}
              />
              <MetricRow
                label="95% CI"
                value={
                  pop?.ciLower != null && pop?.ciUpper != null
                    ? `[${int(pop.ciLower)}, ${int(pop.ciUpper)}]`
                    : "—"
                }
              />
            </tbody>
          </table>

          {/* Metrics & PR curve — only when labels exist */}
          {hasLabels && (
            <>
              <Text
                variant="mediumPlus"
                style={{ fontWeight: 600, display: "block", marginBottom: 8 }}
              >
                Binary metrics (positive class = Damaged)
              </Text>
              <table style={{ marginBottom: 16 }}>
                <tbody>
                  <MetricRow label="Accuracy" value={pct(metrics?.accuracy)} />
                  <MetricRow label="Precision" value={pct(metrics?.precision)} />
                  <MetricRow label="Recall" value={pct(metrics?.recall)} />
                  <MetricRow
                    label="Average precision"
                    value={pct(metrics?.averagePrecision)}
                  />
                  <MetricRow label="Matched sample" value={int(sample?.n)} />
                  <MetricRow
                    label="True damaged / not damaged"
                    value={`${int(sample?.trueDamaged)} / ${int(sample?.trueNotDamaged)}`}
                  />
                </tbody>
              </table>

              {sample?.hasBothClasses === false && (
                <Text
                  variant="small"
                  style={{ color: "#8a6d3b", display: "block", marginBottom: 8 }}
                >
                  Note: the labeled sample contains only one class; metrics may
                  be degenerate.
                </Text>
              )}

              <Text
                variant="mediumPlus"
                style={{ fontWeight: 600, display: "block", marginBottom: 8 }}
              >
                Precision-recall curve
              </Text>
              <PrecisionRecallChart
                precision={report.precisionRecallCurve?.precision}
                recall={report.precisionRecallCurve?.recall}
              />

              {report.labeledMissingFromPredictions > 0 && (
                <Text
                  variant="small"
                  style={{ color: "#666", display: "block", marginTop: 12 }}
                >
                  {report.labeledMissingFromPredictions} sure label
                  {report.labeledMissingFromPredictions === 1 ? "" : "s"} had
                  no matching prediction and were dropped.
                </Text>
              )}
            </>
          )}
        </div>
      )}

      <DialogFooter>
        <DefaultButton onClick={onDismiss} text="Close" />
      </DialogFooter>
    </Dialog>
  );
};

export default AssessmentReportModal;
