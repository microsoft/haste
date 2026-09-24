// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Class selection and direct map painting, with one standard-model threshold.
import PropTypes from "prop-types";
import {
  Button, Dropdown, Field, MessageBar, MessageBarBody, Option, Slider, Switch, Text, makeStyles, tokens,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
import KeyboardShortcutHelp from "../KeyboardShortcutHelp";
import { PREDICTION_EDIT_SHORTCUTS } from "../keyboardShortcuts";
import { CLASS_LABELS, PREDICTION_CLASSES } from "./predictionClassify.js";
import { canAdjustThresholds } from "./predictionEditing.js";
import { versionLabel } from "./predictionVersions.js";
import { RESULTS_DESKTOP_MIN_WIDTH } from "./visualizerSwipe.js";

const percent = (value) => value == null ? "—" : `${Math.round(value * 100)}%`;
const CLASS_COLORS = {
  Damaged: tokens.colorStatusDangerBackground3,
  NotDamaged: tokens.colorStatusSuccessBackground3,
  Unknown: tokens.colorNeutralForeground3,
};
const REVIEW_CLASSES = { all: "All buildings", ...CLASS_LABELS };
const useStyles = makeStyles({
  panel: {
    position: "absolute", top: "10px", right: "10px", bottom: "10px", zIndex: 1000,
    boxSizing: "border-box", width: "clamp(300px, 25vw, 360px)", maxWidth: "calc(100% - 20px)",
    padding: tokens.spacingHorizontalL, display: "flex", flexDirection: "column",
    color: tokens.colorNeutralForeground1, backgroundColor: tokens.colorNeutralBackground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium, boxShadow: tokens.shadow16,
    "@media (max-width: 700px)": {
      top: "auto", right: "8px", bottom: "8px", left: "8px", width: "auto",
      maxWidth: "none", maxHeight: "min(55%, 520px)", padding: tokens.spacingHorizontalM,
    },
  },
  scroll: {
    flex: 1, minHeight: 0, overflowX: "hidden", overflowY: "auto",
    overscrollBehavior: "contain", scrollbarGutter: "stable", paddingRight: tokens.spacingHorizontalS,
    display: "flex", flexDirection: "column", gap: tokens.spacingVerticalM, touchAction: "pan-y",
    "& > *": { flexShrink: 0 },
  },
  header: {
    flexShrink: 0, paddingBottom: tokens.spacingVerticalS, marginBottom: tokens.spacingVerticalS,
    borderBottom: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
  subtle: { color: tokens.colorNeutralForeground3, fontSize: tokens.fontSizeBase200, lineHeight: tokens.lineHeightBase200 },
  buttonColumn: { display: "flex", flexDirection: "column", gap: tokens.spacingVerticalXS, "& > *": { flexShrink: 0 } },
  classButton: {
    width: "100%", minHeight: "40px", justifyContent: "space-between",
    fontWeight: tokens.fontWeightSemibold,
  },
  reviewButtons: {
    display: "flex", gap: tokens.spacingHorizontalS,
    "& > button": { flex: 1 },
  },
  sliderValue: { display: "flex", justifyContent: "space-between", fontSize: tokens.fontSizeBase200 },
  actions: {
    flexShrink: 0, paddingTop: tokens.spacingVerticalS, marginTop: tokens.spacingVerticalS,
    borderTop: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    display: "flex", flexDirection: "column", gap: tokens.spacingVerticalXS,
  },
  mobileComparison: { [`@media (min-width: ${RESULTS_DESKTOP_MIN_WIDTH}px)`]: { display: "none" } },
});

export default function PredictionEditPanel({ editor, onExit, onReviewClassChange, swipeStateMobile, setSwipeStateMobile, onReloadCurrent }) {
  const styles = useStyles();
  const { state, classification } = editor;
  if (!state || !classification) return null;
  const { attrs, draft, source, activeClass } = state;
  const thresholdEnabled = canAdjustThresholds(source);
  const version = source.predictionVersion ?? 0;
  const reviewCount = editor.rows.length;
  const reviewPosition = editor.rows.indexOf(state.selectedIndex);
  const reviewDisabled = editor.disabled || reviewCount === 0 ||
    ["source_changed", "request_conflict"].includes(editor.errorCode);
  const reviewProgress = reviewCount === 0
    ? "No buildings in this category."
    : reviewPosition >= 0
      ? `Building ${(reviewPosition + 1).toLocaleString()} of ${reviewCount.toLocaleString()}`
      : editor.selectedId !== undefined
        ? `Reclassified · ${reviewCount.toLocaleString()} remaining in this category`
        : `${reviewCount.toLocaleString()} ${reviewCount === 1 ? "building" : "buildings"} in this category`;
  return (
    <section id="predictionEditPanel" aria-label="Edit predictions" className={`${styles.panel} labeling-tool-surface`}>
      <div className={styles.header}>
        <Text size={500} block>Edit predictions</Text>
        <div className={styles.subtle}>{attrs.n.toLocaleString()} buildings · {source.flavor === "inference" ? "standard" : "interactive"} model</div>
        <div className={styles.subtle}>Editing base: {versionLabel(version)}</div>
        <div className={styles.subtle}>{editor.confirmed?.pending
          ? `Saved preview — reload version ${editor.confirmed.result.version} to display its immutable artifacts.`
          : editor.dirty ? "Local preview · unsaved changes" : "Changes are a local preview until saved."}</div>
      </div>
      <div className={styles.scroll}>
        <Field label="Class to apply">
          <div className={styles.buttonColumn} role="group" aria-label="Class to apply">
            {PREDICTION_CLASSES.map((cls, index) => {
              const color = cls === "Unknown" ? tokens.colorNeutralBackground1 : tokens.colorNeutralForegroundOnBrand;
              return (
                <Button key={cls} className={styles.classButton}
                  aria-label={`${CLASS_LABELS[cls]} (${index + 1})`} aria-pressed={activeClass === cls}
                  style={{
                    backgroundColor: CLASS_COLORS[cls], borderColor: CLASS_COLORS[cls], color,
                    boxShadow: activeClass === cls ? `inset 0 0 0 2px ${color}` : "none",
                    opacity: editor.disabled ? 0.5 : 1,
                  }}
                  disabled={editor.disabled} onClick={() => editor.setActiveClass(cls)}>
                  <span>{CLASS_LABELS[cls]} ({index + 1})</span>
                  <span>{classification.counts[cls].toLocaleString()}</span>
                </Button>
              );
            })}
          </div>
        </Field>
        <div className={styles.subtle}>
          Click a building to apply {CLASS_LABELS[activeClass]}, or Ctrl+drag to paint a group.
          Editing works on both sides. Right-click restores the model class.
        </div>
        {thresholdEnabled && (
          <div>
            <Field label={`Damage threshold: ${percent(draft.threshold)}`}>
              <Slider min={0} max={100} step={1} value={Math.round(draft.threshold * 100)} disabled={editor.disabled}
                onChange={(_event, data) => editor.setThreshold(data.value / 100)} />
            </Field>
            <div className={styles.sliderValue}><span>More damaged</span><span>Fewer damaged</span></div>
            <div className={styles.subtle}>Manual assignments stay fixed when the threshold changes.</div>
          </div>
        )}
        <div className={styles.subtle}>{classification.changedFromModel.toLocaleString()} buildings changed from model.</div>
        <Field label="Review">
          <Dropdown selectedOptions={[state.reviewClass]} value={REVIEW_CLASSES[state.reviewClass]}
            disabled={editor.disabled}
            onOptionSelect={(_event, data) => { if (data.optionValue) onReviewClassChange(data.optionValue); }}>
            {Object.entries(REVIEW_CLASSES).map(([value, label]) => <Option key={value} value={value}>{label}</Option>)}
          </Dropdown>
        </Field>
        <Text id="predictionReviewProgress" role="status" aria-live="polite" aria-atomic="true" weight="semibold" block>
          {reviewProgress}
        </Text>
        <div className={styles.reviewButtons}>
          <Button icon={<FluentIcon name="ChevronLeft" />} disabled={reviewDisabled} onClick={() => editor.navigate(-1)}>
            Previous
          </Button>
          <Button icon={<FluentIcon name="ChevronRight" />} iconPosition="after" disabled={reviewDisabled} onClick={() => editor.navigate(1)}>
            Next
          </Button>
        </div>
        <div className={styles.subtle}>
          Use Previous/Next or ←/→ to highlight a building, then 1/2/3 to label it.
          {editor.selectedId !== undefined && <Text block weight="semibold">
            Highlighted: {CLASS_LABELS[classification.classes[state.selectedIndex]]}
          </Text>}
        </div>
        <Switch className={styles.mobileComparison} checked={swipeStateMobile === "post"}
          label={swipeStateMobile === "post" ? "Post-event imagery" : "Pre-event / basemap imagery"}
          onChange={(_event, data) => setSwipeStateMobile(data.checked ? "post" : "pre")} />
        <KeyboardShortcutHelp shortcuts={PREDICTION_EDIT_SHORTCUTS} />
      </div>
      <div className={styles.actions}>
        {editor.error && <MessageBar intent="error"><MessageBarBody>
          {editor.error}
          {editor.errorCode === "source_changed" && <Button onClick={onReloadCurrent}>Reload current predictions</Button>}
        </MessageBarBody></MessageBar>}
        <Button disabled={editor.disabled || !editor.dirty} onClick={editor.discard}>Undo unsaved changes</Button>
        <Button appearance="primary" onClick={editor.save}
          disabled={editor.disabled || !editor.dirty || ["source_changed", "request_conflict"].includes(editor.errorCode)}>
          {editor.busy ? "Saving / loading…" : "Save as new version"}
        </Button>
        <Button icon={<FluentIcon name="cancel" />} disabled={editor.busy} onClick={onExit}>Done editing</Button>
      </div>
    </section>
  );
}
PredictionEditPanel.propTypes = {
  editor: PropTypes.object.isRequired, onExit: PropTypes.func.isRequired,
  onReviewClassChange: PropTypes.func.isRequired,
  swipeStateMobile: PropTypes.string.isRequired, setSwipeStateMobile: PropTypes.func.isRequired,
  onReloadCurrent: PropTypes.func.isRequired,
};
