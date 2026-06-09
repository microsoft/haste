// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import PropTypes from "prop-types";
import { DefaultButton, PrimaryButton } from "@fluentui/react";

const LABEL_OPTIONS = [
  { value: "Damaged", label: "Damaged (1)", color: "#e74c3c" },
  { value: "NotDamaged", label: "Not Damaged (2)", color: "#27ae60" },
  { value: "Unknown", label: "Unknown (3)", color: "#5a6268" },
];

const coloredButtonStyles = (color, selected) => ({
  root: {
    backgroundColor: color,
    borderColor: color,
    color: "#fff",
    width: "100%",
    opacity: selected ? 1 : 0.85,
    outline: selected ? `2px solid ${color}` : "none",
    outlineOffset: 2,
  },
  rootHovered: {
    backgroundColor: color,
    borderColor: color,
    color: "#fff",
    opacity: 1,
  },
  rootPressed: {
    backgroundColor: color,
    borderColor: color,
    color: "#fff",
    opacity: 0.9,
  },
  label: { fontWeight: 600 },
});

const BuildingValidationRightPanel = ({
  features,
  labels,
  selectedIndex,
  setSelectedIndex,
  onLabel,
  onSave,
  onDownload,
  isSaving,
  labeledCount,
}) => {
  BuildingValidationRightPanel.propTypes = {
    features: PropTypes.array.isRequired,
    labels: PropTypes.object.isRequired,
    selectedIndex: PropTypes.number.isRequired,
    setSelectedIndex: PropTypes.func.isRequired,
    onLabel: PropTypes.func.isRequired,
    onSave: PropTypes.func.isRequired,
    onDownload: PropTypes.func.isRequired,
    isSaving: PropTypes.bool.isRequired,
    labeledCount: PropTypes.number.isRequired,
  };

  const total = features.length;
  const currentFeature = features[selectedIndex];
  const currentId = currentFeature?.properties?.id;
  const currentLabel = currentId ? labels[currentId]?.label : null;
  const progressPct = total > 0 ? Math.round((labeledCount / total) * 100) : 0;

  return (
    <div
      style={{
        position: "absolute",
        right: 12,
        top: 12,
        width: 240,
        background: "rgba(255, 255, 255, 0.97)",
        borderRadius: 8,
        boxShadow: "0 2px 12px rgba(0,0,0,0.18)",
        zIndex: 1000,
        padding: "14px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      {/* Header */}
      <div style={{ fontWeight: 700, fontSize: 15, borderBottom: "1px solid #eee", paddingBottom: 8 }}>
        Building Validation
      </div>

      {/* Progress */}
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 4 }}>
          <span style={{ color: "#555" }}>Progress</span>
          <span style={{ fontWeight: 600 }}>{labeledCount} / {total} ({progressPct}%)</span>
        </div>
        <div style={{ background: "#e9ecef", borderRadius: 4, height: 6 }}>
          <div
            style={{
              background: "#3498db",
              height: 6,
              borderRadius: 4,
              width: `${progressPct}%`,
              transition: "width 0.3s",
            }}
          />
        </div>
      </div>

      {/* Building info */}
      <div style={{ background: "#f8f9fa", borderRadius: 4, padding: "6px 8px", fontSize: 11 }}>
        <div style={{ fontWeight: 600, marginBottom: 2 }}>
          Building {selectedIndex + 1} of {total}
        </div>
        {currentId && (
          <div style={{ color: "#666", wordBreak: "break-all" }}>
            ID: {currentId.length > 20 ? `...${currentId.slice(-20)}` : currentId}
          </div>
        )}
        {currentLabel && (
          <div style={{ marginTop: 4, fontWeight: 600, color: LABEL_OPTIONS.find(o => o.value === currentLabel)?.color }}>
            {LABEL_OPTIONS.find(o => o.value === currentLabel)?.label}
          </div>
        )}
      </div>

      {/* Label buttons */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: "#555" }}>
          Label this building:
        </div>
        {LABEL_OPTIONS.map((opt) => (
          <PrimaryButton
            key={opt.value}
            text={opt.label}
            onClick={() => onLabel(opt.value)}
            styles={coloredButtonStyles(opt.color, currentLabel === opt.value)}
          />
        ))}
      </div>

      {/* Navigation */}
      <div style={{ display: "flex", gap: 6 }}>
        <DefaultButton
          text="Prev"
          onClick={() => setSelectedIndex((i) => Math.max(0, i - 1))}
          disabled={selectedIndex === 0}
          styles={{ root: { flex: 1 } }}
        />
        <DefaultButton
          text="Next"
          onClick={() => setSelectedIndex((i) => Math.min(total - 1, i + 1))}
          disabled={selectedIndex === total - 1}
          styles={{ root: { flex: 1 } }}
        />
      </div>

      {/* Legend */}
      <div style={{ fontSize: 10, color: "#888", lineHeight: 1.7 }}>
        <div style={{ fontWeight: 600, marginBottom: 2, color: "#555" }}>Legend · Hotkeys: 1 / 2 / 3</div>
        <div><span style={{ color: "#3498db" }}>■</span> Unlabeled</div>
        <div><span style={{ color: "#e74c3c" }}>■</span> Damaged</div>
        <div><span style={{ color: "#27ae60" }}>■</span> Not Damaged</div>
        <div><span style={{ color: "#5a6268" }}>■</span> Unknown</div>
      </div>

      {/* Actions */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6, borderTop: "1px solid #eee", paddingTop: 8 }}>
        <PrimaryButton
          text={isSaving ? "Saving…" : "Save Labels"}
          onClick={onSave}
          disabled={isSaving}
          styles={{ root: { width: "100%" } }}
        />
        <DefaultButton
          text="Download GeoJSON"
          onClick={onDownload}
          styles={{ root: { width: "100%" } }}
        />
      </div>
    </div>
  );
};

export default BuildingValidationRightPanel;
