// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import PropTypes from "prop-types";
import {
  Button,
  Dropdown,
  Option,
  Switch,
  Field,
} from "@fluentui/react-components";

const LABEL_OPTIONS = [
  { value: "Damaged", label: "Damaged (1)", color: "#C50F1F" },
  { value: "NotDamaged", label: "Not Damaged (2)", color: "#107C10" },
  { value: "Unknown", label: "Unknown (3)", color: "#4D4D4D" },
];

const FILTER_LABELS = {
  all: "All buildings",
  unlabeled: "Unlabeled only",
  Damaged: "Damaged only",
  NotDamaged: "Not Damaged only",
  Unknown: "Unknown only",
};

const coloredButtonStyle = (color, selected) => ({
  backgroundColor: color,
  borderColor: color,
  color: "#fff",
  width: "100%",
  opacity: selected ? 1 : 0.85,
  outline: selected ? `2px solid ${color}` : "none",
  outlineOffset: 2,
  fontWeight: 600,
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
              background: "#BDBDBD",
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
        <Switch
          label="Show building fill"
          checked={showFill}
          onChange={(_e, data) => setShowFill(!!data.checked)}
        />
        <Switch
          label="Show post-event imagery"
          checked={showPostImagery}
          onChange={(_e, data) => setShowPostImagery(!!data.checked)}
          disabled={!hasPostImagery}
        />
      </div>

      {/* Filter */}
      <Field label="Show / review" style={{ marginTop: 4 }}>
        <Dropdown
          selectedOptions={[filter]}
          value={FILTER_LABELS[filter] || filter}
          onOptionSelect={(_e, data) =>
            data.optionValue && setFilter(data.optionValue)
          }
        >
          {filterValues.map((v) => (
            <Option key={v} value={v}>
              {FILTER_LABELS[v] || v}
            </Option>
          ))}
        </Dropdown>
      </Field>

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
          <Button
            key={opt.value}
            appearance="primary"
            onClick={() => onLabel(opt.value)}
            style={coloredButtonStyle(opt.color, currentLabel === opt.value)}
          >
            {opt.label}
          </Button>
        ))}
      </div>

      {/* Navigation */}
      <div style={{ display: "flex", gap: 6 }}>
        <Button
          onClick={onPrev}
          disabled={filteredIndices.length <= 1}
          style={{ flex: 1 }}
        >
          Prev
        </Button>
        <Button
          onClick={onNext}
          disabled={filteredIndices.length <= 1}
          style={{ flex: 1 }}
        >
          Next
        </Button>
      </div>
      <Button
        onClick={onSkipToNextUnlabeled}
        disabled={remainingUnlabeled === 0}
        style={{ width: "100%" }}
      >
        {remainingUnlabeled > 0
          ? `Skip to next unlabeled (${remainingUnlabeled} left)`
          : "All buildings labeled"}
      </Button>

      {/* Legend */}
      <div style={{ fontSize: 10, color: "#888", lineHeight: 1.7 }}>
        <div style={{ fontWeight: 600, marginBottom: 2, color: "#555" }}>Legend · Hotkeys: 1 / 2 / 3 · ← →</div>
        <div><span style={{ color: "#BDBDBD" }}>■</span> Unlabeled</div>
        <div><span style={{ color: "#C50F1F" }}>■</span> Damaged</div>
        <div><span style={{ color: "#107C10" }}>■</span> Not Damaged</div>
        <div><span style={{ color: "#4D4D4D" }}>■</span> Unknown</div>
      </div>

      {/* Actions */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6, borderTop: "1px solid #eee", paddingTop: 8 }}>
        <Button
          appearance="primary"
          onClick={onSave}
          disabled={isSaving}
          style={{ width: "100%" }}
        >
          {isSaving ? "Saving…" : "Save Labels"}
        </Button>
        <Button
          onClick={onDownload}
          style={{ width: "100%" }}
        >
          Download GeoJSON
        </Button>
      </div>
    </div>
  );
};

export default BuildingValidationRightPanel;
