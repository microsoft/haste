// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import PropTypes from "prop-types";
import {
  Button,
  Dropdown,
  Option,
  Switch,
  Field,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import KeyboardShortcutHelp from "../KeyboardShortcutHelp";
import { BUILDING_VALIDATION_SHORTCUTS } from "../keyboardShortcuts";

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

const useStyles = makeStyles({
  panel: {
    position: "absolute",
    top: "10px",
    right: "10px",
    bottom: "10px",
    width: "clamp(280px, 24vw, 340px)",
    maxWidth: "calc(100% - 20px)",
    overflowX: "hidden",
    overflowY: "auto",
    overscrollBehavior: "contain",
    scrollbarGutter: "stable",
    zIndex: 1000,
    boxSizing: "border-box",
    padding: tokens.spacingHorizontalL,
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalM,
    color: tokens.colorNeutralForeground1,
    backgroundColor: tokens.colorNeutralBackground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium,
    boxShadow: tokens.shadow16,
    "& > *": {
      flexShrink: 0,
    },
    "@media (max-width: 700px)": {
      top: "auto",
      right: "8px",
      bottom: "8px",
      left: "8px",
      width: "auto",
      maxWidth: "none",
      maxHeight: "min(55%, 520px)",
      padding: tokens.spacingHorizontalM,
      zIndex: 25,
    },
  },
  header: {
    paddingBottom: tokens.spacingVerticalS,
    borderBottom: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    fontSize: tokens.fontSizeBase400,
    fontWeight: tokens.fontWeightSemibold,
  },
  muted: {
    color: tokens.colorNeutralForeground3,
  },
  dividedSection: {
    borderTop: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    borderBottom: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
  progressTrack: {
    height: "6px",
    overflow: "hidden",
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorNeutralBackground4,
  },
  progressFill: {
    height: "6px",
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorBrandBackground,
    transitionProperty: "width",
    transitionDuration: tokens.durationNormal,
  },
  buildingInfo: {
    padding: `${tokens.spacingVerticalSNudge} ${tokens.spacingHorizontalS}`,
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorNeutralBackground2,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    fontSize: tokens.fontSizeBase100,
  },
  legend: {
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase100,
    lineHeight: tokens.lineHeightBase200,
  },
  legendTitle: {
    marginBottom: tokens.spacingVerticalXXS,
    color: tokens.colorNeutralForeground2,
    fontWeight: tokens.fontWeightSemibold,
  },
  actions: {
    paddingTop: tokens.spacingVerticalS,
    borderTop: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
});

const BuildingValidationRightPanel = ({
  features,
  labels,
  selectedIndex,
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
  hasPreImagery,
  hasPostImagery,
}) => {
  const styles = useStyles();
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
    <div className={styles.panel}>
      {/* Header */}
      <div className={styles.header}>
        Building Validation
      </div>

      {/* Progress */}
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 4 }}>
          <span className={styles.muted}>Progress</span>
          <span style={{ fontWeight: 600 }}>{labeledCount} / {total} ({progressPct}%)</span>
        </div>
        <div className={styles.progressTrack}>
          <div
            className={styles.progressFill}
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      {/* View toggles */}
      <div
        className={styles.dividedSection}
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 2,
          padding: "6px 0",
        }}
      >
        <Switch
          label="Show building fill"
          checked={showFill}
          onChange={(_e, data) => setShowFill(!!data.checked)}
        />
        <Switch
label={
  showPostImagery
    ? hasPostImagery
      ? "Imagery: Post event"
      : "Imagery: Basemap"
    : hasPreImagery
      ? "Imagery: Pre event"
      : "Imagery: Basemap"
}
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
      <div className={styles.buildingInfo}>
        <div style={{ fontWeight: 600, marginBottom: 2 }}>{positionLabel}</div>
        {currentId && (
          <div className={styles.muted} style={{ wordBreak: "break-all" }}>
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
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div className={styles.muted} style={{ fontSize: 11, fontWeight: 600 }}>
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
      <div style={{ display: "flex", gap: 8 }}>
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
      <div className={styles.legend}>
        <div className={styles.legendTitle}>Legend</div>
        <div><span style={{ color: "#BDBDBD" }}>■</span> Unlabeled</div>
        <div><span style={{ color: "#C50F1F" }}>■</span> Damaged</div>
        <div><span style={{ color: "#107C10" }}>■</span> Not Damaged</div>
        <div><span style={{ color: "#4D4D4D" }}>■</span> Unknown</div>
      </div>

      <KeyboardShortcutHelp shortcuts={BUILDING_VALIDATION_SHORTCUTS} />

      {/* Actions */}
      <div className={styles.actions} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
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

BuildingValidationRightPanel.propTypes = {
  features: PropTypes.array.isRequired,
  labels: PropTypes.object.isRequired,
  selectedIndex: PropTypes.number.isRequired,
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
  hasPreImagery: PropTypes.bool,
  hasPostImagery: PropTypes.bool,
};

export default BuildingValidationRightPanel;
