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
    <Stack tokens={{ childrenGap: tokens.spacingM }}>
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
      <Stack horizontal tokens={{ childrenGap: tokens.spacingL }} horizontalAlign="start">
        <Stack horizontal verticalAlign="center" tokens={{ childrenGap: tokens.spacingS }}>
          <div style={{ width: 10, height: 10, borderRadius: 2, background: tokens.colorSuccessTint30 }} />
          <Text variant="xSmall" styles={{ root: { color: tokens.colorNeutralForeground3 } }}>Correct</Text>
        </Stack>
        <Stack horizontal verticalAlign="center" tokens={{ childrenGap: tokens.spacingS }}>
          <div style={{ width: 10, height: 10, borderRadius: 2, background: tokens.colorDangerTint30 }} />
          <Text variant="xSmall" styles={{ root: { color: tokens.colorNeutralForeground3 } }}>Misclassified</Text>
        </Stack>
      </Stack>
    </Stack>
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

  return (
    <Dialog
      hidden={false}
      onDismiss={onDismiss}
      dialogContentProps={{
        type: DialogType.largeHeader,
        title: (
          <Stack horizontal verticalAlign="center" tokens={{ childrenGap: 8 }}>
            <Icon iconName="ReportDocument" styles={{ root: { fontSize: 20, color: tokens.colorBrandForeground1 } }} />
            <span>{`Validation Report — ${modelName || modelId}`}</span>
          </Stack>
        ),
        subText: loading
          ? undefined
          : error
          ? undefined
          : `${report?.matched} validation labels matched to inference results (Unknown labels excluded)`,
      }}
      modalProps={{ isBlocking: false }}
      minWidth={680}
    >
      {loading && (
        <Stack horizontalAlign="center" styles={{ root: { padding: "32px 0" } }}>
          <Spinner size={SpinnerSize.large} label="Computing report…" />
        </Stack>
      )}

      {!loading && error && (
        <MessageBar
          messageBarType={error.soft ? MessageBarType.warning : MessageBarType.error}
          isMultiline={true}
        >
          {error.message}
        </MessageBar>
      )}

      {!loading && report && !error && (
        <Stack tokens={{ childrenGap: 24 }}>
          {/* Overall Metrics */}
          <div>
            <SectionTitle>Overall Metrics</SectionTitle>
            <Stack horizontal tokens={{ childrenGap: 12 }}>
              <HeroCard label="Accuracy" value={pct(report.accuracy)} color={tokens.colorBrandForeground1} />
              <HeroCard label="Macro F1" value={pct(report.macroF1)} color={tokens.colorSuccessForeground1} />
            </Stack>
          </div>

          {/* Two-column layout */}
          <Stack horizontal tokens={{ childrenGap: 32 }}>
            <Stack.Item grow={1} styles={{ root: { minWidth: 0 } }}>
              <SectionTitle>Label Summary</SectionTitle>
              <Stack tokens={{ childrenGap: tokens.spacingS }}>
                <MetricCard label="Total validation labels" value={report.totalValidationLabels} />
                <MetricCard label="Damaged labels" value={report.labelCounts?.Damaged ?? 0} accent={tokens.colorDangerForeground1} />
                <MetricCard label="Not Damaged labels" value={report.labelCounts?.NotDamaged ?? 0} accent={tokens.colorSuccessForeground1} />
                <MetricCard label="Unknown labels (excluded)" value={report.labelCounts?.Unknown ?? 0} accent={tokens.colorNeutralForeground3} />
                <MetricCard label="Matched to predictions" value={report.matched} />
              </Stack>
            </Stack.Item>

            <Stack.Item grow={1} styles={{ root: { minWidth: 0 } }}>
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
            </Stack.Item>
          </Stack>

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
        </Stack>
      )}

      <DialogFooter>
        {error && <PrimaryButton onClick={fetchReport} text="Retry" />}
        <DefaultButton onClick={onDismiss} text="Close" />
      </DialogFooter>
    </Dialog>
  );
};

export default ValidationReportModal;
