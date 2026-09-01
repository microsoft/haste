// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useEffect, useState } from "react";
import {
  Button,
  Spinner,
  Text,
  MessageBar,
  MessageBarBody,
  Dialog,
  DialogSurface,
  DialogBody,
  DialogTitle,
  DialogContent,
  DialogActions,
  tokens as fluentTokens,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
import PropTypes from "prop-types";
import { apiGet } from "../../util/api";
import { buildAssessmentSummary } from "../../util/assessmentSummary";
import PredictionVersionPicker from "../OtherComponents/PredictionVersionPicker";
import { defaultPredictionVersion } from "../Visualizer/predictionVersions";

/* ── Theme-aware design tokens (follow light/dark via Fluent) ─── */
const tokens = {
  colorNeutralBackground1: fluentTokens.colorNeutralBackground1,
  colorNeutralBackground2: fluentTokens.colorNeutralBackground2,
  colorNeutralForeground1: fluentTokens.colorNeutralForeground1,
  colorNeutralForeground2: fluentTokens.colorNeutralForeground2,
  colorNeutralForeground3: fluentTokens.colorNeutralForeground3,
  colorNeutralStroke1: fluentTokens.colorNeutralStroke1,
  colorNeutralStroke2: fluentTokens.colorNeutralStroke2,
  colorBrandForeground1: fluentTokens.colorBrandForeground1,
  colorSuccessForeground1: fluentTokens.colorStatusSuccessForeground1,
  colorDangerForeground1: fluentTokens.colorStatusDangerForeground1,
  spacingS: fluentTokens.spacingVerticalS,
  spacingM: fluentTokens.spacingVerticalM,
  borderRadius: fluentTokens.borderRadiusMedium,
};

// ─── Helpers ──────────────────────────────────────────────────────────────

const pct = (v) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);
const int = (v) => (v == null ? "—" : Math.round(v).toLocaleString());
const num = (v, d = 4) => (v == null ? "—" : Number(v).toFixed(d));

/* ── Styles ──────────────────────────────────────────────────── */
const metricCardStyle = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  padding: "8px 12px",
  borderRadius: tokens.borderRadius,
  background: tokens.colorNeutralBackground2,
  border: `1px solid ${tokens.colorNeutralStroke2}`,
};

const heroCardStyle = {
  flex: 1,
  padding: "12px 16px",
  borderRadius: tokens.borderRadius,
  background: tokens.colorNeutralBackground2,
  border: `1px solid ${tokens.colorNeutralStroke2}`,
};

const halfItemStyle = { minWidth: 0, flex: "1 1 220px" };
const rowStyle = { display: "flex", gap: tokens.spacingS, flexWrap: "wrap" };

/* ── Sub-components ──────────────────────────────────────────── */
const SectionTitle = ({ children }) => (
  <Text style={{ fontWeight: 600, color: tokens.colorNeutralForeground1, display: "block", marginBottom: tokens.spacingM }}>
    {children}
  </Text>
);
SectionTitle.propTypes = { children: PropTypes.node.isRequired };

const MetricCard = ({ label, value, accent }) => (
  <div style={metricCardStyle}>
    <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>{label}</Text>
    <Text style={{ fontWeight: 600, color: accent || tokens.colorNeutralForeground1 }}>
      {value}
    </Text>
  </div>
);
MetricCard.propTypes = {
  label: PropTypes.string.isRequired,
  value: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
  accent: PropTypes.string,
};

const HeroCard = ({ label, value, color }) => (
  <div style={heroCardStyle}>
    <Text size={200} style={{ color: tokens.colorNeutralForeground3, display: "block", marginBottom: 10 }}>
      {label}
    </Text>
    <Text size={700} style={{ fontWeight: 600, color, lineHeight: 1 }}>
      {value}
    </Text>
  </div>
);
HeroCard.propTypes = {
  label: PropTypes.string.isRequired,
  value: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
  color: PropTypes.string.isRequired,
};

// ─── Precision-recall chart (full width SVG) ──────────────────────────────

const PrecisionRecallChart = ({ precision, recall }) => {
  if (!precision || !recall || precision.length === 0) return null;
  const h = 180;
  const pad = 32;
  const w = 400;
  const points = recall
    .map((r, i) => [r, precision[i]])
    .sort((a, b) => a[0] - b[0]);
  const ticks = [0, 0.25, 0.5, 0.75, 1.0];
  return (
    <div style={{ maxWidth: 480, margin: "0 auto" }}>
      <svg
        width="100%"
        viewBox={`0 0 ${w} ${h}`}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label="Precision-recall curve"
        style={{ border: `1px solid ${tokens.colorNeutralStroke2}`, borderRadius: tokens.borderRadius, display: "block" }}
      >
        <line x1={pad} y1={h - pad} x2={w - pad} y2={h - pad} stroke={tokens.colorNeutralStroke1} />
        <line x1={pad} y1={pad} x2={pad} y2={h - pad} stroke={tokens.colorNeutralStroke1} />
        {ticks.map((t) => {
          const x = pad + t * (w - 2 * pad);
          const y = h - pad - t * (h - 2 * pad);
          return (
            <g key={`t-${t}`}>
              <line x1={x} y1={pad} x2={x} y2={h - pad} stroke={tokens.colorNeutralStroke2} />
              <line x1={pad} y1={y} x2={w - pad} y2={y} stroke={tokens.colorNeutralStroke2} />
              <text x={x} y={h - pad + 13} fontSize="9" fill={tokens.colorNeutralForeground3} textAnchor="middle">{t.toFixed(2)}</text>
              <text x={pad - 5} y={y + 3} fontSize="9" fill={tokens.colorNeutralForeground3} textAnchor="end">{t.toFixed(2)}</text>
            </g>
          );
        })}
        <text x={w / 2} y={h - 4} fontSize="10" fill={tokens.colorNeutralForeground2} textAnchor="middle">Recall (damaged)</text>
        <text x={10} y={h / 2} fontSize="10" fill={tokens.colorNeutralForeground2} textAnchor="middle" transform={`rotate(-90 10 ${h / 2})`}>Precision (damaged)</text>
        <polyline
          points={points.map(([r, p]) => `${(pad + r * (w - 2 * pad)).toFixed(1)},${(h - pad - p * (h - 2 * pad)).toFixed(1)}`).join(" ")}
          fill="none"
          stroke={tokens.colorBrandForeground1}
          strokeWidth="2"
        />
      </svg>
    </div>
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
  versions,
  onDismiss,
}) => {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  // Which predictions the assessment counts. Defaults to the newest saved
  // edit, matching what the server would have picked on its own.
  const [version, setVersion] = useState(() =>
    defaultPredictionVersion(versions)
  );

  const fetchReport = () => {
    setLoading(true);
    setError(null);
    setReport(null);
    apiGet(
      `GetAssessmentReport?projectId=${projectId}&imageLayerId=${imageLayerId}&modelId=${modelId}&version=${version}`
    )
      .then((data) => {
        if (data && data.error && !data.predictions) {
          setError(data.error);
        } else {
          setReport(data);
        }
      })
      .catch(() => setError("Failed to load assessment report."))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    // State updates occur after the report request resolves.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchReport();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, imageLayerId, modelId, version]);

  const preds = report?.predictions;
  const pop = report?.populationEstimate;
  const metrics = report?.metrics;
  const sample = report?.evaluationSample;
  const hasLabels = (report?.matched ?? 0) > 0;

  const summarySentence = buildAssessmentSummary(report);

  return (
    <Dialog
      open={true}
      onOpenChange={(_, d) => {
        if (!d.open) onDismiss();
      }}
    >
      <DialogSurface style={{ width: "min(920px, 94vw)", maxWidth: "94vw" }}>
        <DialogBody>
          <DialogTitle
            action={
              <Button
                appearance="subtle"
                aria-label="Close"
                icon={<FluentIcon name="Cancel" />}
                onClick={onDismiss}
              />
            }
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <FluentIcon name="AnalyticsReport" style={{ fontSize: 20, color: tokens.colorBrandForeground1 }} />
              <span>{`Assessment Report — ${modelName || modelId}`}</span>
            </div>
          </DialogTitle>
          <DialogContent>
            <PredictionVersionPicker
              versions={versions}
              value={version}
              onChange={setVersion}
              disabled={loading}
              label="Report on"
            />
            {!loading && !error && summarySentence && (
              <Text style={{ display: "block", color: tokens.colorNeutralForeground2, marginBottom: 16 }}>
                {summarySentence}
              </Text>
            )}

            {loading && (
              <div className="app-loading-inline">
                <div className="app-loading-card">
                  <Text className="app-loading-message">Computing assessment…</Text>
                  <Spinner size="tiny" className="app-loading-spinner" />
                </div>
              </div>
            )}

            {!loading && error && (
              <MessageBar intent="error">
                <MessageBarBody>{error}</MessageBarBody>
              </MessageBar>
            )}

            {!loading && report && !error && (
              <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
                {/* Predictions — 2 columns, 2 per row */}
                <div>
                  <SectionTitle>Predictions</SectionTitle>
                  <div style={{ display: "flex", flexDirection: "column", gap: tokens.spacingS }}>
                    <div style={rowStyle}>
                      <div style={{ flexGrow: 1, ...halfItemStyle }}>
                        <MetricCard label="Buildings with a prediction" value={int(preds?.total)} />
                      </div>
                      <div style={{ flexGrow: 1, ...halfItemStyle }}>
                        <MetricCard label="Non-cloudy" value={int(preds?.knownNonCloudy)} />
                      </div>
                    </div>
                    <div style={rowStyle}>
                      <div style={{ flexGrow: 1, ...halfItemStyle }}>
                        <MetricCard label="Cloud-covered (excluded)" value={int(preds?.cloudy)} />
                      </div>
                      <div style={{ flexGrow: 1, ...halfItemStyle }}>
                        <MetricCard label={`Predicted damaged (> ${report.threshold})`} value={`${int(preds?.predictedDamaged)} (${preds?.predictedDamagedPctOfKnown ?? 0}% of non-cloudy)`} accent={tokens.colorDangerForeground1} />
                      </div>
                    </div>
                  </div>
                </div>

                {/* Population estimate — 2 columns, 2 per row */}
                <div>
                  <SectionTitle>Damaged-building population estimate</SectionTitle>
                  <div style={{ display: "flex", flexDirection: "column", gap: tokens.spacingS }}>
                    <div style={rowStyle}>
                      <div style={{ flexGrow: 1, ...halfItemStyle }}>
                        <MetricCard label={`N (buildings with area > ${pop?.minAreaM2?.toFixed(0)} m²)`} value={int(pop?.N)} />
                      </div>
                      <div style={{ flexGrow: 1, ...halfItemStyle }}>
                        <MetricCard label="Sample size (n)" value={int(pop?.n)} />
                      </div>
                    </div>
                    <div style={rowStyle}>
                      <div style={{ flexGrow: 1, ...halfItemStyle }}>
                        <MetricCard label="Damaged in sample (x)" value={int(pop?.x)} />
                      </div>
                      <div style={{ flexGrow: 1, ...halfItemStyle }}>
                        <MetricCard label="Sample damage rate (p̂)" value={pct(pop?.pHat)} accent={tokens.colorDangerForeground1} />
                      </div>
                    </div>
                    <div style={rowStyle}>
                      <div style={{ flexGrow: 1, ...halfItemStyle }}>
                        <MetricCard label="Sampling fraction (n/N)" value={num(pop?.samplingFraction, 6)} />
                      </div>
                      <div style={{ flexGrow: 1, ...halfItemStyle }}>
                        <MetricCard label="Std. error of p̂" value={num(pop?.sePHat, 6)} />
                      </div>
                    </div>
                    <div style={rowStyle}>
                      <div style={{ flexGrow: 1, ...halfItemStyle }}>
                        <MetricCard label="Estimated damaged buildings (Ŷ)" value={int(pop?.estimatedDamaged)} accent={tokens.colorDangerForeground1} />
                      </div>
                      <div style={{ flexGrow: 1, ...halfItemStyle }}>
                        <MetricCard label="95% CI" value={pop?.ciLower != null && pop?.ciUpper != null ? `[${int(pop.ciLower)}, ${int(pop.ciUpper)}]` : "—"} />
                      </div>
                    </div>
                  </div>
                </div>

                {/* Metrics & PR curve — only when labels exist */}
                {hasLabels && (
                  <>
                    {/* Binary metrics — 2 columns, 2 per row */}
                    <div>
                      <SectionTitle>Binary metrics (positive class = Damaged)</SectionTitle>
                      <div style={{ display: "flex", flexDirection: "column", gap: tokens.spacingS }}>
                        <div style={rowStyle}>
                          <div style={{ flexGrow: 1, ...halfItemStyle }}>
                            <MetricCard label="Accuracy" value={pct(metrics?.accuracy)} />
                          </div>
                          <div style={{ flexGrow: 1, ...halfItemStyle }}>
                            <MetricCard label="Precision" value={pct(metrics?.precision)} />
                          </div>
                        </div>
                        <div style={rowStyle}>
                          <div style={{ flexGrow: 1, ...halfItemStyle }}>
                            <MetricCard label="Recall" value={pct(metrics?.recall)} />
                          </div>
                          <div style={{ flexGrow: 1, ...halfItemStyle }}>
                            <MetricCard label="Average precision" value={pct(metrics?.averagePrecision)} />
                          </div>
                        </div>
                        <div style={rowStyle}>
                          <div style={{ flexGrow: 1, ...halfItemStyle }}>
                            <MetricCard label="Matched sample" value={int(sample?.n)} />
                          </div>
                          <div style={{ flexGrow: 1, ...halfItemStyle }}>
                            <MetricCard label="True damaged / not damaged" value={`${int(sample?.trueDamaged)} / ${int(sample?.trueNotDamaged)}`} />
                          </div>
                        </div>
                      </div>
                    </div>
                    {sample?.hasBothClasses === false && (
                      <MessageBar intent="warning">
                        <MessageBarBody>
                          The labeled sample contains only one class; metrics may be degenerate.
                        </MessageBarBody>
                      </MessageBar>
                    )}

                    <div>
                      <SectionTitle>Precision-recall curve</SectionTitle>
                      <PrecisionRecallChart
                        precision={report.precisionRecallCurve?.precision}
                        recall={report.precisionRecallCurve?.recall}
                      />
                    </div>

                    {report.labeledMissingFromPredictions > 0 && (
                      <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
                        {report.labeledMissingFromPredictions} sure label
                        {report.labeledMissingFromPredictions === 1 ? "" : "s"} had
                        no matching prediction and were dropped.
                      </Text>
                    )}
                  </>
                )}
              </div>
            )}
          </DialogContent>
          <DialogActions>
            {error && <Button appearance="primary" onClick={fetchReport}>Retry</Button>}
            <Button onClick={onDismiss}>Close</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
};

AssessmentReportModal.propTypes = {
  projectId: PropTypes.string.isRequired,
  imageLayerId: PropTypes.string.isRequired,
  modelId: PropTypes.string.isRequired,
  modelName: PropTypes.string,
  versions: PropTypes.array,
  onDismiss: PropTypes.func.isRequired,
};

export default AssessmentReportModal;
