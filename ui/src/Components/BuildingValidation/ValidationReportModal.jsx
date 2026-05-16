// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useEffect, useState } from "react";
import { Dialog, DialogType, DialogFooter } from "@fluentui/react/lib/Dialog";
import { DefaultButton, Spinner, SpinnerSize, Text } from "@fluentui/react";
import PropTypes from "prop-types";
import { apiGet } from "../../util/api";

const pct = (v) => (v != null ? `${(v * 100).toFixed(1)}%` : "—");

const MetricRow = ({ label, value }) => (
  <tr>
    <td style={{ padding: "4px 12px 4px 0", fontWeight: 500, color: "#444" }}>{label}</td>
    <td style={{ padding: "4px 0", fontFamily: "monospace" }}>{value}</td>
  </tr>
);
MetricRow.propTypes = { label: PropTypes.string.isRequired, value: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired };

const ConfusionMatrix = ({ matrix, labels }) => {
  const cellStyle = (i, j) => ({
    padding: "8px 14px",
    textAlign: "center",
    fontFamily: "monospace",
    fontSize: 14,
    background: i === j ? "#d4edda" : "#f8d7da",
    border: "1px solid #dee2e6",
    fontWeight: i === j ? 700 : 400,
  });
  const headerStyle = {
    padding: "6px 14px",
    textAlign: "center",
    fontSize: 12,
    color: "#666",
    border: "1px solid #dee2e6",
    background: "#f5f5f5",
  };
  return (
    <div style={{ overflowX: "auto", marginTop: 8 }}>
      <table style={{ borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr>
            <th style={{ ...headerStyle, background: "transparent", border: "none" }} />
            <th colSpan={labels.length} style={{ ...headerStyle, background: "#e8f4fd", border: "1px solid #dee2e6" }}>
              Predicted
            </th>
          </tr>
          <tr>
            <th style={{ ...headerStyle, background: "transparent", border: "none" }} />
            {labels.map((l) => (
              <th key={l} style={headerStyle}>{l}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, i) => (
            <tr key={i}>
              {i === 0 && (
                <td
                  rowSpan={matrix.length}
                  style={{
                    ...headerStyle,
                    background: "#e8f4fd",
                    writingMode: "vertical-rl",
                    transform: "rotate(180deg)",
                    textAlign: "center",
                    fontWeight: 600,
                    padding: "8px 4px",
                    border: "1px solid #dee2e6",
                  }}
                >
                  Actual
                </td>
              )}
              <td style={{ ...headerStyle }}>{labels[i]}</td>
              {row.map((val, j) => (
                <td key={j} style={cellStyle(i, j)}>{val}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <Text variant="xSmall" style={{ color: "#888", marginTop: 4, display: "block" }}>
        Green = correct predictions, Red = misclassifications
      </Text>
    </div>
  );
};
ConfusionMatrix.propTypes = {
  matrix: PropTypes.arrayOf(PropTypes.array).isRequired,
  labels: PropTypes.arrayOf(PropTypes.string).isRequired,
};

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

  useEffect(() => {
    apiGet(
      `GetValidationReport?projectId=${projectId}&imageLayerId=${imageLayerId}&modelId=${modelId}`
    )
      .then((data) => {
        if (data.error) setError(data.error);
        else setReport(data);
      })
      .catch(() => setError("Failed to load validation report."))
      .finally(() => setLoading(false));
  }, [projectId, imageLayerId, modelId]);

  return (
    <Dialog
      hidden={false}
      onDismiss={onDismiss}
      dialogContentProps={{
        type: DialogType.largeHeader,
        title: `Validation Report — ${modelName || modelId}`,
        subText: loading
          ? "Loading…"
          : error
          ? error
          : `${report?.matched} validation labels matched to inference results (Unknown labels excluded)`,
      }}
      modalProps={{ isBlocking: false }}
      minWidth={520}
    >
      {loading && (
        <div style={{ padding: "24px 0", textAlign: "center" }}>
          <Spinner size={SpinnerSize.large} label="Computing report…" />
        </div>
      )}

      {!loading && error && (
        <div style={{ padding: "16px 0", color: "#a4000f" }}>
          <Text>{error}</Text>
        </div>
      )}

      {!loading && report && !error && (
        <div style={{ padding: "4px 0 16px" }}>
          {/* Summary counts */}
          <Text variant="mediumPlus" style={{ fontWeight: 600, display: "block", marginBottom: 8 }}>
            Label Summary
          </Text>
          <table style={{ marginBottom: 16 }}>
            <tbody>
              <MetricRow label="Total validation labels" value={report.totalValidationLabels} />
              <MetricRow label="Damaged labels" value={report.labelCounts?.Damaged ?? 0} />
              <MetricRow label="Not Damaged labels" value={report.labelCounts?.NotDamaged ?? 0} />
              <MetricRow label="Unknown labels (excluded)" value={report.labelCounts?.Unknown ?? 0} />
              <MetricRow label="Matched to predictions" value={report.matched} />
            </tbody>
          </table>

          {/* Overall accuracy */}
          <Text variant="mediumPlus" style={{ fontWeight: 600, display: "block", marginBottom: 8 }}>
            Overall Metrics
          </Text>
          <table style={{ marginBottom: 16 }}>
            <tbody>
              <MetricRow label="Accuracy" value={pct(report.accuracy)} />
              <MetricRow label="Macro F1" value={pct(report.macroF1)} />
            </tbody>
          </table>

          {/* Per-class metrics */}
          <Text variant="mediumPlus" style={{ fontWeight: 600, display: "block", marginBottom: 8 }}>
            Per-Class Metrics
          </Text>
          <table style={{ borderCollapse: "collapse", marginBottom: 16, fontSize: 13, width: "100%" }}>
            <thead>
              <tr>
                {["Class", "Precision", "Recall", "F1"].map((h) => (
                  <th
                    key={h}
                    style={{ padding: "4px 12px", textAlign: "center", borderBottom: "2px solid #dee2e6", color: "#555" }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {["Damaged", "NotDamaged"].map((cls) => {
                const m = report.perClass?.[cls];
                return (
                  <tr key={cls}>
                    <td style={{ padding: "4px 12px", fontWeight: 500 }}>{cls === "NotDamaged" ? "Not Damaged" : cls}</td>
                    <td style={{ padding: "4px 12px", textAlign: "center", fontFamily: "monospace" }}>{pct(m?.precision)}</td>
                    <td style={{ padding: "4px 12px", textAlign: "center", fontFamily: "monospace" }}>{pct(m?.recall)}</td>
                    <td style={{ padding: "4px 12px", textAlign: "center", fontFamily: "monospace" }}>{pct(m?.f1)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {/* Confusion matrix */}
          <Text variant="mediumPlus" style={{ fontWeight: 600, display: "block", marginBottom: 8 }}>
            Confusion Matrix
          </Text>
          {report.confusionMatrix && (
            <ConfusionMatrix
              matrix={report.confusionMatrix.matrix}
              labels={report.confusionMatrix.labels}
            />
          )}
        </div>
      )}

      <DialogFooter>
        <DefaultButton onClick={onDismiss} text="Close" />
      </DialogFooter>
    </Dialog>
  );
};

export default ValidationReportModal;
