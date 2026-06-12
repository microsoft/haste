// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useEffect, useState } from "react";
import { Dialog, DialogType, DialogFooter } from "@fluentui/react/lib/Dialog";
import {
  DefaultButton,
  PrimaryButton,
  Spinner,
  SpinnerSize,
  Text,
  Icon,
  Stack,
  MessageBar,
  MessageBarType,
  mergeStyles,
} from "@fluentui/react";
import PropTypes from "prop-types";
import { apiGet } from "../../util/api";

/* ── Fluent v8 design tokens ─────────────────────────────────── */
const tokens = {
  colorNeutralBackground1: "#ffffff",
  colorNeutralBackground2: "#faf9f8",
  colorNeutralForeground1: "#242424",
  colorNeutralForeground2: "#424242",
  colorNeutralForeground3: "#616161",
  colorNeutralStroke1: "#d1d1d1",
  colorNeutralStroke2: "#e0e0e0",
  colorBrandForeground1: "#0f6cbd",
  colorSuccessForeground1: "#107C10",
  colorDangerForeground1: "#C50F1F",
  spacingS: 4,
  spacingM: 8,
  borderRadius: 4,
};

// ─── Helpers ──────────────────────────────────────────────────────────────

const pct = (v) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);
const int = (v) => (v == null ? "—" : Math.round(v).toLocaleString());
const num = (v, d = 4) => (v == null ? "—" : Number(v).toFixed(d));

/* ── Styles ──────────────────────────────────────────────────── */
const metricCardClass = mergeStyles({
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  padding: "8px 12px",
  borderRadius: tokens.borderRadius,
  background: tokens.colorNeutralBackground2,
  border: `1px solid ${tokens.colorNeutralStroke2}`,
});

const heroCardBase = mergeStyles({
  flex: 1,
  padding: "12px 16px",
  borderRadius: tokens.borderRadius,
  background: tokens.colorNeutralBackground2,
  border: `1px solid ${tokens.colorNeutralStroke2}`,
});

const halfItemStyles = { root: { minWidth: 0, flexBasis: "50%", maxWidth: "50%" } };

/* ── Sub-components ──────────────────────────────────────────── */
const SectionTitle = ({ children }) => (
  <Text variant="medium" styles={{ root: { fontWeight: 600, color: tokens.colorNeutralForeground1, display: "block", marginBottom: tokens.spacingM } }}>
    {children}
  </Text>
);
SectionTitle.propTypes = { children: PropTypes.node.isRequired };

const MetricCard = ({ label, value, accent }) => (
  <div className={metricCardClass}>
    <Text variant="small" styles={{ root: { color: tokens.colorNeutralForeground3 } }}>{label}</Text>
    <Text variant="medium" styles={{ root: { fontWeight: 600, color: accent || tokens.colorNeutralForeground1 } }}>
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
  <div className={heroCardBase}>
    <Text variant="small" styles={{ root: { color: tokens.colorNeutralForeground3, display: "block", marginBottom: 10 } }}>
      {label}
    </Text>
    <Text variant="xxLarge" styles={{ root: { fontWeight: 600, color, lineHeight: 1 } }}>
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

  const fetchReport = () => {
    setLoading(true);
    setError(null);
    setReport(null);
    apiGet(
      `GetAssessmentReport?projectId=${projectId}&imageLayerId=${imageLayerId}&modelId=${modelId}`
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
    fetchReport();
  }, [projectId, imageLayerId, modelId]);

  const preds = report?.predictions;
  const pop = report?.populationEstimate;
  const metrics = report?.metrics;
  const sample = report?.evaluationSample;
  const hasLabels = (report?.matched ?? 0) > 0;

  function buildSummarySentence() {
    if (!report || !preds) return "";
    let s =
      `Out of a total of ${int(preds.total)} building footprints in the study area, ` +
      `${int(preds.cloudy)} were obscured by clouds; of the remaining ` +
      `${int(preds.knownNonCloudy)} non-cloudy footprints, the model ` +
      `predicted that ${int(preds.predictedDamaged)} ` +
      `(${preds.predictedDamagedPctOfKnown ?? 0}%) were damaged to some extent.`;
    if (!hasLabels) {
      return (
        s +
        " No human validation labels are available for this image layer yet — " +
        "labeling some via the Building Validation tool will populate the " +
        "metrics and population estimate."
      );
    }
    s +=
      ` We independently labeled ${int(report.totalLabels)} footprints; ` +
      `${int(report.sureLabels)} were sure-labeled. Estimated recall ` +
      `${pct(metrics?.recall)} and precision ${pct(metrics?.precision)}.`;
    if (pop && pop.N > 0) {
      s +=
        ` Extrapolating to all ${int(pop.N)} buildings with area > ` +
        `${pop.minAreaM2.toFixed(0)} m², we estimate ` +
        `${int(pop.estimatedDamaged)} damaged buildings ` +
        `(${pct(pop.pHat)}) with a 95% CI of ` +
        `[${int(pop.ciLower)}, ${int(pop.ciUpper)}].`;
    }
    return s;
  }
  const summarySentence = buildSummarySentence();

  return (
    <Dialog
      hidden={false}
      onDismiss={onDismiss}
      dialogContentProps={{
        type: DialogType.largeHeader,
        title: (
          <Stack horizontal verticalAlign="center" tokens={{ childrenGap: 8 }}>
            <Icon iconName="AnalyticsReport" styles={{ root: { fontSize: 20, color: tokens.colorBrandForeground1 } }} />
            <span>{`Assessment Report — ${modelName || modelId}`}</span>
          </Stack>
        ),
        subText: loading ? undefined : error ? undefined : summarySentence,
      }}
      modalProps={{ isBlocking: false }}
      minWidth={860}
    >
      {loading && (
        <Stack horizontalAlign="center" styles={{ root: { padding: "32px 0" } }}>
          <Spinner size={SpinnerSize.large} label="Computing assessment…" />
        </Stack>
      )}

      {!loading && error && (
        <MessageBar messageBarType={MessageBarType.error} isMultiline={false}>
          {error}
        </MessageBar>
      )}

      {!loading && report && !error && (
        <Stack tokens={{ childrenGap: 24 }}>
          {/* Predictions — 2 columns, 2 per row */}
          <div>
            <SectionTitle>Predictions</SectionTitle>
            <Stack tokens={{ childrenGap: tokens.spacingS }}>
              <Stack horizontal tokens={{ childrenGap: tokens.spacingS }}>
                <Stack.Item grow={1} styles={halfItemStyles}>
                  <MetricCard label="Buildings with a prediction" value={int(preds?.total)} />
                </Stack.Item>
                <Stack.Item grow={1} styles={halfItemStyles}>
                  <MetricCard label="Non-cloudy" value={int(preds?.knownNonCloudy)} />
                </Stack.Item>
              </Stack>
              <Stack horizontal tokens={{ childrenGap: tokens.spacingS }}>
                <Stack.Item grow={1} styles={halfItemStyles}>
                  <MetricCard label="Cloud-covered (excluded)" value={int(preds?.cloudy)} />
                </Stack.Item>
                <Stack.Item grow={1} styles={halfItemStyles}>
                  <MetricCard label={`Predicted damaged (> ${report.threshold})`} value={`${int(preds?.predictedDamaged)} (${preds?.predictedDamagedPctOfKnown ?? 0}% of non-cloudy)`} accent={tokens.colorDangerForeground1} />
                </Stack.Item>
              </Stack>
            </Stack>
          </div>

          {/* Population estimate — 2 columns, 2 per row */}
          <div>
            <SectionTitle>Damaged-building population estimate</SectionTitle>
            <Stack tokens={{ childrenGap: tokens.spacingS }}>
              <Stack horizontal tokens={{ childrenGap: tokens.spacingS }}>
                <Stack.Item grow={1} styles={halfItemStyles}>
                  <MetricCard label={`N (buildings with area > ${pop?.minAreaM2?.toFixed(0)} m²)`} value={int(pop?.N)} />
                </Stack.Item>
                <Stack.Item grow={1} styles={halfItemStyles}>
                  <MetricCard label="Sample size (n)" value={int(pop?.n)} />
                </Stack.Item>
              </Stack>
              <Stack horizontal tokens={{ childrenGap: tokens.spacingS }}>
                <Stack.Item grow={1} styles={halfItemStyles}>
                  <MetricCard label="Damaged in sample (x)" value={int(pop?.x)} />
                </Stack.Item>
                <Stack.Item grow={1} styles={halfItemStyles}>
                  <MetricCard label="Sample damage rate (p̂)" value={pct(pop?.pHat)} accent={tokens.colorDangerForeground1} />
                </Stack.Item>
              </Stack>
              <Stack horizontal tokens={{ childrenGap: tokens.spacingS }}>
                <Stack.Item grow={1} styles={halfItemStyles}>
                  <MetricCard label="Sampling fraction (n/N)" value={num(pop?.samplingFraction, 6)} />
                </Stack.Item>
                <Stack.Item grow={1} styles={halfItemStyles}>
                  <MetricCard label="Std. error of p̂" value={num(pop?.sePHat, 6)} />
                </Stack.Item>
              </Stack>
              <Stack horizontal tokens={{ childrenGap: tokens.spacingS }}>
                <Stack.Item grow={1} styles={halfItemStyles}>
                  <MetricCard label="Estimated damaged buildings (Ŷ)" value={int(pop?.estimatedDamaged)} accent={tokens.colorDangerForeground1} />
                </Stack.Item>
                <Stack.Item grow={1} styles={halfItemStyles}>
                  <MetricCard label="95% CI" value={pop?.ciLower != null && pop?.ciUpper != null ? `[${int(pop.ciLower)}, ${int(pop.ciUpper)}]` : "—"} />
                </Stack.Item>
              </Stack>
            </Stack>
          </div>

          {/* Metrics & PR curve — only when labels exist */}
          {hasLabels && (
            <>
              {/* Binary metrics — 2 columns, 2 per row */}
              <div>
                <SectionTitle>Binary metrics (positive class = Damaged)</SectionTitle>
                <Stack tokens={{ childrenGap: tokens.spacingS }}>
                  <Stack horizontal tokens={{ childrenGap: tokens.spacingS }}>
                    <Stack.Item grow={1} styles={halfItemStyles}>
                      <MetricCard label="Accuracy" value={pct(metrics?.accuracy)} />
                    </Stack.Item>
                    <Stack.Item grow={1} styles={halfItemStyles}>
                      <MetricCard label="Precision" value={pct(metrics?.precision)} />
                    </Stack.Item>
                  </Stack>
                  <Stack horizontal tokens={{ childrenGap: tokens.spacingS }}>
                    <Stack.Item grow={1} styles={halfItemStyles}>
                      <MetricCard label="Recall" value={pct(metrics?.recall)} />
                    </Stack.Item>
                    <Stack.Item grow={1} styles={halfItemStyles}>
                      <MetricCard label="Average precision" value={pct(metrics?.averagePrecision)} />
                    </Stack.Item>
                  </Stack>
                  <Stack horizontal tokens={{ childrenGap: tokens.spacingS }}>
                    <Stack.Item grow={1} styles={halfItemStyles}>
                      <MetricCard label="Matched sample" value={int(sample?.n)} />
                    </Stack.Item>
                    <Stack.Item grow={1} styles={halfItemStyles}>
                      <MetricCard label="True damaged / not damaged" value={`${int(sample?.trueDamaged)} / ${int(sample?.trueNotDamaged)}`} />
                    </Stack.Item>
                  </Stack>
                </Stack>
              </div>
              {sample?.hasBothClasses === false && (
                <MessageBar messageBarType={MessageBarType.warning} isMultiline={false}>
                  The labeled sample contains only one class; metrics may be degenerate.
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
                <Text variant="small" styles={{ root: { color: tokens.colorNeutralForeground3 } }}>
                  {report.labeledMissingFromPredictions} sure label
                  {report.labeledMissingFromPredictions === 1 ? "" : "s"} had
                  no matching prediction and were dropped.
                </Text>
              )}
            </>
          )}
        </Stack>
      )}

      <DialogFooter>
        {error && <PrimaryButton onClick={fetchReport} text="Retry" />}
        <DefaultButton onClick={onDismiss} text="Close" />
      </DialogFooter>
    </Dialog>
  );
};

export default AssessmentReportModal;
