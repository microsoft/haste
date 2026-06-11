// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import PropTypes from "prop-types";
import { DefaultButton, Dropdown, PrimaryButton, Toggle } from "@fluentui/react";

const LABEL_OPTIONS = [
  { value: "Damaged", label: "Damaged (1)", color: "#e74c3c" },
  { value: "NotDamaged", label: "Not Damaged (2)", color: "#27ae60" },
  { value: "Unknown", label: "Unknown (3)", color: "#5a6268" },
];

const FILTER_LABELS = {
  all: "All buildings",
  unlabeled: "Unlabeled only",
  Damaged: "Damaged only",
  NotDamaged: "Not Damaged only",
  Unknown: "Unknown only",
};

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
  filter,
  setFilter,
  filterValues,
  filteredIndices,
  onPrev,
  onNext,
  onSkipToNextUnlabeled,
  showFill,
  setShowFill,
  showPostImagery,
  setShowPostImagery,
  hasPostImagery,
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
    filter: PropTypes.string.isRequired,
    setFilter: PropTypes.func.isRequired,
    filterValues: PropTypes.arrayOf(PropTypes.string).isRequired,
    filteredIndices: PropTypes.arrayOf(PropTypes.number).isRequired,
    onPrev: PropTypes.func.isRequired,
    onNext: PropTypes.func.isRequired,
    onSkipToNextUnlabeled: PropTypes.func.isRequired,
    showFill: PropTypes.bool.isRequired,
    setShowFill: PropTypes.func.isRequired,
    showPostImagery: PropTypes.bool.isRequired,
    setShowPostImagery: PropTypes.func.isRequired,
    hasPostImagery: PropTypes.bool,
  };

  const total = features.length;
  const currentFeature = features[selectedIndex];
  const currentId = currentFeature?.properties?.id;
  const currentLabel = currentId ? labels[currentId]?.label : null;
  const progressPct = total > 0 ? Math.round((labeledCount / total) * 100) : 0;

  // When a filter is active, show position-in-filter; otherwise show the
  // global position. Use indexOf because the selection may briefly fall
  // outside the filtered subset until the filter-change effect catches it.
  const filterPos = filteredIndices.indexOf(selectedIndex);
  const positionLabel =
    filter === "all"
      ? `Building ${selectedIndex + 1} of ${total}`
      : filterPos >= 0
      ? `Building ${filterPos + 1} of ${filteredIndices.length} (filtered)`
      : `(no buildings match filter)`;

  const remainingUnlabeled = total - labeledCount;
  const filterOptions = filterValues.map((v) => ({
    key: v,
    text: FILTER_LABELS[v] || v,
  }));

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

      {/* View toggles */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 2,
          borderTop: "1px solid #eee",
          borderBottom: "1px solid #eee",
          padding: "6px 0",
        }}
      >
        <Toggle
          label="Show building fill"
          checked={showFill}
          onChange={(_e, checked) => setShowFill(!!checked)}
          onText="On"
          offText="Off"
          styles={{
            root: { marginBottom: 0 },
            label: { fontSize: 11, fontWeight: 600, color: "#555" },
            text: { fontSize: 11 },
          }}
        />
        <Toggle
          label="Show post-event imagery"
          checked={showPostImagery}
          onChange={(_e, checked) => setShowPostImagery(!!checked)}
          onText="On"
          offText="Off"
          disabled={!hasPostImagery}
          styles={{
            root: { marginBottom: 0 },
            label: { fontSize: 11, fontWeight: 600, color: "#555" },
            text: { fontSize: 11 },
          }}
        />
      </div>

      {/* Filter */}
      <Dropdown
        label="Show / review"
        selectedKey={filter}
        options={filterOptions}
        onChange={(_e, opt) => opt && setFilter(opt.key)}
        styles={{
          root: { marginTop: 4 },
          label: { fontSize: 11, fontWeight: 600, color: "#555", padding: 0 },
          dropdown: { fontSize: 12 },
          title: { height: 28, lineHeight: "26px", fontSize: 12 },
        }}
      />

      {/* Building info */}
      <div style={{ background: "#f8f9fa", borderRadius: 4, padding: "6px 8px", fontSize: 11 }}>
        <div style={{ fontWeight: 600, marginBottom: 2 }}>{positionLabel}</div>
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
          onClick={onPrev}
          disabled={filteredIndices.length <= 1}
          styles={{ root: { flex: 1 } }}
        />
        <DefaultButton
          text="Next"
          onClick={onNext}
          disabled={filteredIndices.length <= 1}
          styles={{ root: { flex: 1 } }}
        />
      </div>
      <DefaultButton
        text={
          remainingUnlabeled > 0
            ? `Skip to next unlabeled (${remainingUnlabeled} left)`
            : "All buildings labeled"
        }
        onClick={onSkipToNextUnlabeled}
        disabled={remainingUnlabeled === 0}
        styles={{ root: { width: "100%" } }}
      />

      {/* Legend */}
      <div style={{ fontSize: 10, color: "#888", lineHeight: 1.7 }}>
        <div style={{ fontWeight: 600, marginBottom: 2, color: "#555" }}>Legend · Hotkeys: 1 / 2 / 3 · ← →</div>
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
