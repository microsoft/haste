// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// PR136's panel design: counts, thresholds, review, class picker and history.
import PropTypes from "prop-types";
import {
  Badge, Button, Divider, Dropdown, Field, MessageBar, MessageBarBody,
  Option, Slider, Switch, Text, Tooltip, makeStyles, tokens,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
import KeyboardShortcutHelp from "../KeyboardShortcutHelp";
import { PREDICTION_EDIT_SHORTCUTS } from "../keyboardShortcuts";
import { CLASS_LABELS, PREDICTION_CLASSES } from "./predictionClassify.js";
import { canAdjustThresholds } from "./predictionEditing.js";
import { savedClassNote, sortVersionsDescending, versionLabel } from "./predictionVersions.js";
import { RESULTS_DESKTOP_MIN_WIDTH } from "./visualizerSwipe.js";

const percent = (value) => value == null ? "—" : `${Math.round(value * 100)}%`;
const FILTERS = { all: "All buildings", Damaged: "Damaged only", NotDamaged: "Not Damaged only", Unknown: "Unknown only", edited: "Edited only" };
const useStyles = makeStyles({
  panel: {
    position: "absolute", top: "10px", right: "10px", bottom: "10px", zIndex: 1000,
    boxSizing: "border-box", width: "var(--prediction-editor-width)", maxWidth: "calc(100% - 20px)",
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
  countRow: { display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: tokens.spacingHorizontalS },
  countValue: { fontWeight: tokens.fontWeightSemibold },
  swatch: { display: "inline-block", width: "10px", height: "10px", marginRight: tokens.spacingHorizontalXS, borderRadius: tokens.borderRadiusSmall },
  Damaged: { backgroundColor: tokens.colorStatusDangerBackground3 },
  NotDamaged: { backgroundColor: tokens.colorStatusSuccessBackground3 },
  Unknown: { backgroundColor: tokens.colorNeutralForeground3 },
  card: {
    padding: `${tokens.spacingVerticalSNudge} ${tokens.spacingHorizontalS}`,
    borderRadius: tokens.borderRadiusMedium, backgroundColor: tokens.colorNeutralBackground2,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    fontSize: tokens.fontSizeBase200, wordBreak: "break-word",
  },
  buttonColumn: { display: "flex", flexDirection: "column", gap: tokens.spacingVerticalXS, "& > *": { flexShrink: 0 } },
  buttonRow: { display: "flex", gap: tokens.spacingHorizontalS },
  grow: { flexGrow: 1 },
  stackedField: { marginTop: tokens.spacingVerticalS },
  sliderValue: { display: "flex", justifyContent: "space-between", fontSize: tokens.fontSizeBase200 },
  changeReadout: { padding: tokens.spacingHorizontalS, borderRadius: tokens.borderRadiusMedium, backgroundColor: tokens.colorNeutralBackground3 },
  versionList: { display: "flex", flexDirection: "column", gap: tokens.spacingVerticalXS, maxHeight: "160px", overflowY: "auto" },
  versionRow: { padding: tokens.spacingHorizontalS, borderRadius: tokens.borderRadiusMedium, border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`, fontSize: tokens.fontSizeBase100 },
  actions: {
    flexShrink: 0, paddingTop: tokens.spacingVerticalS, marginTop: tokens.spacingVerticalS,
    borderTop: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    display: "flex", flexDirection: "column", gap: tokens.spacingVerticalXS,
  },
  mobileComparison: { [`@media (min-width: ${RESULTS_DESKTOP_MIN_WIDTH}px)`]: { display: "none" } },
});

export default function PredictionEditPanel({ editor, versions, onExit, onDownload, downloadBusy, swipeStateMobile, setSwipeStateMobile, onReloadCurrent }) {
  const styles = useStyles();
  const { state, classification } = editor;
  if (!state || !classification) return null;
  const { attrs, draft, source, selectedIndex, activeClass, filter } = state;
  const selected = selectedIndex >= 0;
  const position = editor.rows.indexOf(selectedIndex);
  const changeCount = classification.classes.filter((cls, i) =>
    draft.overrides[attrs.ids[i]] === undefined && cls !== attrs.classes[i]).length;
  const thresholdEnabled = canAdjustThresholds(source);
  const version = source.predictionVersion ?? 0;
  return (
    <section id="predictionEditPanel" aria-label="Edit predictions" className={`${styles.panel} labeling-tool-surface`}>
      <div className={styles.header}>
        <Text size={500} block>Edit predictions</Text>
        <div className={styles.subtle}>{attrs.n.toLocaleString()} buildings · {source.flavor} model</div>
        <div className={styles.subtle}>Editing base: {versionLabel(version)}</div>
        <div className={styles.subtle}>{editor.confirmed?.pending
          ? `Saved preview — reload version ${editor.confirmed.result.version} to display its immutable artifacts.`
          : editor.dirty ? "Local preview · unsaved changes" : "Changes are a local preview until saved."}</div>
      </div>
      <div className={styles.scroll}>
        <div>
          {PREDICTION_CLASSES.map((cls) => (
            <div className={styles.countRow} key={cls}>
              <span><span className={`${styles.swatch} ${styles[cls]}`} />{CLASS_LABELS[cls]}</span>
              <span className={styles.countValue}>{classification.counts[cls].toLocaleString()}</span>
            </div>
          ))}
          <div className={styles.countRow}><span>Manual assignments</span><span>{classification.editedIds.size}</span></div>
          <div className={styles.countRow}><span>Changed from model</span><span>{classification.changedFromModel}</span></div>
        </div>
        <Divider />
        <div className={styles.subtle}>
          Pre-event or basemap imagery sits left of the divider, post-event imagery right.
          Drag left for more post-event imagery. Editing works on both sides.
        </div>
        <Switch className={styles.mobileComparison} checked={swipeStateMobile === "post"}
          label={swipeStateMobile === "post" ? "Post-event imagery" : "Pre-event / basemap imagery"}
          onChange={(_event, data) => setSwipeStateMobile(data.checked ? "post" : "pre")} />
        <Divider />
        {thresholdEnabled ? (
          <div>
            <Field label={`Damage threshold: ${percent(draft.threshold)}`}>
              <Slider min={0} max={100} step={1} value={Math.round(draft.threshold * 100)} disabled={editor.disabled}
                onChange={(_event, data) => editor.setThreshold("threshold", data.value / 100)} />
            </Field>
            <div className={styles.sliderValue}><span>More damaged</span><span>Fewer damaged</span></div>
            <Field label={`Unknown threshold: ${percent(draft.unknownThreshold)}`} className={styles.stackedField}>
              <Slider min={0} max={100} step={1} value={Math.round(draft.unknownThreshold * 100)} disabled={editor.disabled}
                onChange={(_event, data) => editor.setThreshold("unknownThreshold", data.value / 100)} />
            </Field>
            <div className={styles.changeReadout}>{changeCount.toLocaleString()} buildings would change class from the loaded scores.</div>
          </div>
        ) : <div className={styles.subtle}>{version > 0 ? savedClassNote(version) : "This embedding model has discrete classes, not tunable scores."}</div>}
        <Divider />
        <Field label="Show">
          <Dropdown selectedOptions={[filter]} value={FILTERS[filter]} disabled={editor.disabled}
            onOptionSelect={(_event, data) => { if (data.optionValue) editor.setFilter(data.optionValue); }}>
            {Object.entries(FILTERS).map(([value, label]) => <Option key={value} value={value}>{label}</Option>)}
          </Dropdown>
        </Field>
        <div className={styles.card}>
          <Text weight="semibold" block>{position >= 0 ? `Building ${position + 1} of ${editor.rows.length}` : `${editor.rows.length} buildings match — press Next to start`}</Text>
          {selected ? <>
            <div>ID: {attrs.ids[selectedIndex]}</div>
            <div>Overture: {attrs.overtureIds[selectedIndex]}</div>
            <div>Damage score: {percent(attrs.damage[selectedIndex])} · Unknown: {percent(attrs.unknown[selectedIndex])}</div>
            <div>Class: {CLASS_LABELS[classification.classes[selectedIndex]]}</div>
            {classification.editedIds.has(editor.selectedId) && <Badge appearance="tint">Manual assignment</Badge>}
          </> : <div className={styles.subtle}>Click a footprint, or use Next, to select a building.</div>}
        </div>
        <div className={styles.buttonRow}>
          <Button className={styles.grow} disabled={editor.disabled || !editor.rows.length} onClick={() => editor.navigate(-1)}>Prev</Button>
          <Button className={styles.grow} disabled={editor.disabled || !editor.rows.length} onClick={() => editor.navigate(1)}>Next</Button>
        </div>
        <Field label="Class to apply">
          <div className={styles.buttonColumn}>
            {PREDICTION_CLASSES.map((cls, index) => (
              <Button key={cls} appearance={activeClass === cls ? "primary" : "secondary"} aria-pressed={activeClass === cls}
                disabled={editor.disabled} onClick={() => editor.setActiveClass(cls)}>
                {CLASS_LABELS[cls]} ({index + 1})
              </Button>
            ))}
          </div>
        </Field>
        <div className={styles.subtle}>Click a footprint or Ctrl+drag a box to apply {CLASS_LABELS[activeClass]}. Right-click restores the model class.</div>
        <div className={styles.buttonColumn}>
          <Button disabled={editor.disabled || !selected} onClick={editor.applySelected}>Apply to selected (Enter)</Button>
          <Button disabled={editor.disabled || !selected} onClick={editor.resetSelected}>Reset selected to model class</Button>
          <Button disabled={editor.disabled || editor.manualChangeCount === 0} onClick={editor.undoManual}>
            Undo all {editor.manualChangeCount} manual changes
          </Button>
          <Button disabled={editor.disabled || !editor.dirty} onClick={editor.discard}>Undo unsaved changes</Button>
        </div>
        <Divider />
        <div>
          <Text weight="semibold" block>Saved versions</Text>
          {!versions.length ? <div className={styles.subtle}>No edited versions yet. Saving creates version 1; raw predictions are never overwritten.</div> : (
            <div className={styles.versionList}>
              {sortVersionsDescending(versions).map((entry) => (
                <div key={entry.version} className={styles.versionRow}>
                  <div className={styles.countRow}>
                    <span>Version {entry.version} {entry.version === version && !editor.disabled && <Badge appearance="tint">Editing base</Badge>}</span>
                    <Tooltip content={`Download version ${entry.version}`} relationship="label">
                      <Button size="small" appearance="subtle" icon={<FluentIcon name="download" />}
                        disabled={downloadBusy || !entry.gpkgUrl} onClick={() => onDownload(entry.version, entry.predictionRevision)} />
                    </Tooltip>
                  </div>
                  <div>{entry.createdAt ? new Date(entry.createdAt).toLocaleString() : ""}{entry.createdBy ? ` · ${entry.createdBy}` : ""}</div>
                  <div>Threshold {percent(entry.threshold)} · {entry.editedCount ?? 0} changed from model</div>
                </div>
              ))}
            </div>
          )}
        </div>
        <KeyboardShortcutHelp shortcuts={PREDICTION_EDIT_SHORTCUTS} />
      </div>
      <div className={styles.actions}>
        {editor.error && <MessageBar intent="error"><MessageBarBody>
          {editor.error}
          {editor.errorCode === "source_changed" && <Button onClick={onReloadCurrent}>Reload current predictions</Button>}
        </MessageBarBody></MessageBar>}
        <Button appearance="primary" onClick={editor.save}
          disabled={editor.disabled || ["source_changed", "request_conflict"].includes(editor.errorCode)}>
          {editor.busy ? "Saving / loading…" : "Save as new version"}
        </Button>
        <Button icon={<FluentIcon name="cancel" />} disabled={editor.busy} onClick={onExit}>Done editing</Button>
      </div>
    </section>
  );
}
PredictionEditPanel.propTypes = {
  editor: PropTypes.object.isRequired, versions: PropTypes.array.isRequired,
  onExit: PropTypes.func.isRequired, onDownload: PropTypes.func.isRequired, downloadBusy: PropTypes.bool,
  swipeStateMobile: PropTypes.string.isRequired, setSwipeStateMobile: PropTypes.func.isRequired,
  onReloadCurrent: PropTypes.func.isRequired,
};
