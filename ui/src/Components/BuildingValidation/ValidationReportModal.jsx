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
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
import PropTypes from "prop-types";
import { buildUrl } from "../../util/api";

/* ── Fluent v8 design tokens ─────────────────────────────────── */
const tokens = {
  colorNeutralBackground1: "#ffffff",
  colorNeutralBackground2: "#faf9f8",
  colorNeutralBackground3: "#f3f2f1",
  colorNeutralForeground1: "#242424",
  colorNeutralForeground2: "#424242",
  colorNeutralForeground3: "#616161",
  colorNeutralStroke1: "#d1d1d1",
  colorNeutralStroke2: "#e0e0e0",
  colorBrandBackground: "#0f6cbd",
  colorBrandForeground1: "#0f6cbd",
  colorBrandBackground2: "#ebf3fc",
  colorSuccessBackground1: "#f1faf1",
  colorSuccessForeground1: "#107C10",
  colorDangerBackground1: "#fdf3f4",
  colorDangerForeground1: "#C50F1F",
  colorSuccessTint30: "#54B054",
  colorDangerTint30: "#DC626D",
  colorNeutralForegroundInverted: "#ffffff",
  spacingS: 4,
  spacingM: 8,
  spacingL: 16,
  borderRadius: 4,
};

const pct = (v) => (v != null ? `${(v * 100).toFixed(1)}%` : "—");

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

const thStyle = {
  padding: "8px",
  textAlign: "left",
  borderBottom: `2px solid ${tokens.colorNeutralStroke1}`,
  color: tokens.colorNeutralForeground3,
  fontSize: 12,
  fontWeight: 600,
};

const ConfusionMatrix = ({ matrix, labels }) => {
  const total = matrix.flat().reduce((a, b) => a + b, 0);
  const cellStyle = (i, j, val) => {
    const intensity = total > 0 ? Math.min(val / total * 4, 1) : 0;
    const isCorrect = i === j;
    return {
      padding: "10px",
      textAlign: "center",
      fontSize: 14,
      fontWeight: 600,
      background: isCorrect ? tokens.colorSuccessTint30 : val > 0 ? tokens.colorDangerTint30 : tokens.colorNeutralBackground2,
      border: `1px solid ${tokens.colorNeutralStroke2}`,
      color: isCorrect || val > 0 ? tokens.colorNeutralForegroundInverted : tokens.colorNeutralForeground3,
    };
  };
  const hdr = {
    padding: "8px 10px",
    textAlign: "center",
    fontSize: 12,
    fontWeight: 600,
    color: tokens.colorNeutralForeground3,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    background: tokens.colorNeutralBackground2,
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: tokens.spacingM }}>
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr>
              <th style={{ ...hdr, background: "transparent", border: "none" }} />
              <th colSpan={labels.length} style={{ ...hdr, background: tokens.colorBrandBackground2, color: tokens.colorBrandForeground1 }}>
                Predicted
              </th>
            </tr>
            <tr>
              <th style={{ ...hdr, background: "transparent", border: "none" }} />
              {labels.map((l) => <th key={l} style={{ ...hdr, color: tokens.colorNeutralForeground1 }}>{l}</th>)}
            </tr>
          </thead>
          <tbody>
            {matrix.map((row, i) => (
              <tr key={i}>
                {i === 0 && (
                  <td rowSpan={matrix.length} style={{
                    ...hdr, background: tokens.colorBrandBackground2, color: tokens.colorBrandForeground1,
                    writingMode: "vertical-rl", transform: "rotate(180deg)", padding: "8px 4px",
                  }}>
                    Actual
                  </td>
                )}
                <td style={{ ...hdr, color: tokens.colorNeutralForeground1 }}>{labels[i]}</td>
                {row.map((val, j) => <td key={j} style={cellStyle(i, j, val)}>{val}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ display: "flex", gap: tokens.spacingL, justifyContent: "flex-start" }}>
        <div style={{ display: "flex", alignItems: "center", gap: tokens.spacingS }}>
          <div style={{ width: 10, height: 10, borderRadius: 2, background: tokens.colorSuccessTint30 }} />
          <Text size={100} style={{ color: tokens.colorNeutralForeground3 }}>Correct</Text>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: tokens.spacingS }}>
          <div style={{ width: 10, height: 10, borderRadius: 2, background: tokens.colorDangerTint30 }} />
          <Text size={100} style={{ color: tokens.colorNeutralForeground3 }}>Misclassified</Text>
        </div>
      </div>
    </div>
  );
};
ConfusionMatrix.propTypes = {
  matrix: PropTypes.arrayOf(PropTypes.array).isRequired,
  labels: PropTypes.arrayOf(PropTypes.string).isRequired,
};

/* ── Main component ──────────────────────────────────────────── */
const ValidationReportModal = ({ projectId, imageLayerId, modelId, modelName, onDismiss }) => {
  ValidationReportModal.propTypes = {
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
    // Fetch directly (not via apiGet) so we can read the JSON body on a 404.
    // GetValidationReport returns { error } with a 404 when a prerequisite is
    // missing — no inference results, no saved validation labels, or no
    // building footprints — and with a 200 when nothing matched. Surface that
    // specific message as a soft notice; only an opaque/unparseable response
    // is a hard error.
    fetch(
      buildUrl(
        `GetValidationReport?projectId=${projectId}&imageLayerId=${imageLayerId}&modelId=${modelId}`
      )
    )
      .then(async (response) => {
        let data = null;
        try {
          data = await response.json();
        } catch {
          data = null;
        }
        if (data && data.error) {
          setError({ message: data.error, soft: true });
        } else if (!response.ok || !data) {
          setError({ message: "Failed to load validation report.", soft: false });
        } else {
          setReport(data);
        }
      })
      .catch(() =>
        setError({ message: "Failed to load validation report.", soft: false })
      )
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchReport();
  }, [projectId, imageLayerId, modelId]);

  const subText = loading
    ? undefined
    : error
    ? undefined
    : `${report?.matched} validation labels matched to inference results (Unknown labels excluded)`;

  return (
    <Dialog
      open={true}
      onOpenChange={(_, d) => {
        if (!d.open) onDismiss();
      }}
    >
      <DialogSurface style={{ minWidth: 680, maxWidth: 760 }}>
        <DialogBody>
          <DialogTitle>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <FluentIcon name="ReportDocument" style={{ fontSize: 20, color: tokens.colorBrandForeground1 }} />
              <span>{`Validation Report — ${modelName || modelId}`}</span>
            </div>
          </DialogTitle>
          <DialogContent>
            {subText && (
              <Text style={{ display: "block", color: tokens.colorNeutralForeground2, marginBottom: 16 }}>
                {subText}
              </Text>
            )}

            {loading && (
              <div style={{ display: "flex", justifyContent: "center", padding: "32px 0" }}>
                <Spinner size="large" label="Computing report…" />
              </div>
            )}

            {!loading && error && (
              <MessageBar intent={error.soft ? "warning" : "error"}>
                <MessageBarBody>{error.message}</MessageBarBody>
              </MessageBar>
            )}

            {!loading && report && !error && (
              <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
                {/* Overall Metrics */}
                <div>
                  <SectionTitle>Overall Metrics</SectionTitle>
                  <div style={{ display: "flex", gap: 12 }}>
                    <HeroCard label="Accuracy" value={pct(report.accuracy)} color={tokens.colorBrandForeground1} />
                    <HeroCard label="Macro F1" value={pct(report.macroF1)} color={tokens.colorSuccessForeground1} />
                  </div>
                </div>

                {/* Two-column layout */}
                <div style={{ display: "flex", gap: 32 }}>
                  <div style={{ flexGrow: 1, minWidth: 0 }}>
                    <SectionTitle>Label Summary</SectionTitle>
                    <div style={{ display: "flex", flexDirection: "column", gap: tokens.spacingS }}>
                      <MetricCard label="Total validation labels" value={report.totalValidationLabels} />
                      <MetricCard label="Damaged labels" value={report.labelCounts?.Damaged ?? 0} accent={tokens.colorDangerForeground1} />
                      <MetricCard label="Not Damaged labels" value={report.labelCounts?.NotDamaged ?? 0} accent={tokens.colorSuccessForeground1} />
                      <MetricCard label="Unknown labels (excluded)" value={report.labelCounts?.Unknown ?? 0} accent={tokens.colorNeutralForeground3} />
                      <MetricCard label="Matched to predictions" value={report.matched} />
                    </div>
                  </div>

                  <div style={{ flexGrow: 1, minWidth: 0 }}>
                    <SectionTitle>Per-Class Metrics</SectionTitle>
                    <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 13 }}>
                      <thead>
                        <tr>
                          {["Class", "Precision", "Recall", "F1"].map((h) => (
                            <th key={h} style={thStyle}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {["Damaged", "NotDamaged"].map((cls, idx) => {
                          const m = report.perClass?.[cls];
                          return (
                            <tr key={cls} style={{ background: idx % 2 === 0 ? tokens.colorNeutralBackground2 : tokens.colorNeutralBackground1 }}>
                              <td style={{ padding: 8, fontWeight: 600, color: tokens.colorNeutralForeground1 }}>
                                {cls === "NotDamaged" ? "Not Damaged" : cls}
                              </td>
                              <td style={{ padding: 8, textAlign: "left", fontWeight: 600 }}>{pct(m?.precision)}</td>
                              <td style={{ padding: 8, textAlign: "left", fontWeight: 600 }}>{pct(m?.recall)}</td>
                              <td style={{ padding: 8, textAlign: "left", fontWeight: 600 }}>{pct(m?.f1)}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Confusion matrix full width */}
                <div>
                  <SectionTitle>Confusion Matrix</SectionTitle>
                  {report.confusionMatrix && (
                    <ConfusionMatrix
                      matrix={report.confusionMatrix.matrix}
                      labels={report.confusionMatrix.labels}
                    />
                  )}
                </div>
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

export default ValidationReportModal;
