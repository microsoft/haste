// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Right-hand control panel for the Prediction Editor: class counts, the
// swipe imagery-comparison toggle, the filter + prev/next traversal over the
// filtered set, the threshold sliders (only for models that support them),
// the live "would change class" readout, the save action, and the
// saved-version history.
//
// Layout and interaction mirror BuildingValidationRightPanel so the two
// review screens feel like the same tool. Every colour comes from Fluent
// tokens, so the panel follows the light/dark theme.
import PropTypes from "prop-types";
import {
  Button,
  Divider,
  Dropdown,
  Field,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Option,
  Radio,
  RadioGroup,
  Slider,
  Switch,
  Text,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import KeyboardShortcutHelp from "../KeyboardShortcutHelp";
import { PREDICTION_EDITOR_SHORTCUTS } from "../keyboardShortcuts";
import {
  CLASS_DAMAGED,
  CLASS_LABELS,
  CLASS_NOT_DAMAGED,
  CLASS_UNKNOWN,
  FILTER_ALL,
  FILTER_LABELS,
  FILTER_VALUES,
  sortVersionsDescending,
  toPercentLabel,
} from "./predictionClassify";
import {
  SWIPE_MODE_NONE,
  isSwipeAvailable,
  swipeModeHint,
  swipeToggleLabel,
} from "./predictionSwipe";

const CLASS_ORDER = [CLASS_DAMAGED, CLASS_NOT_DAMAGED, CLASS_UNKNOWN];

// Keyboard hints shown on the class buttons, matching PREDICTION_EDITOR_SHORTCUTS.
const CLASS_HOTKEYS = {
  [CLASS_DAMAGED]: "1",
  [CLASS_NOT_DAMAGED]: "2",
  [CLASS_UNKNOWN]: "3",
};

// Fluent's Slider is integer-friendly; thresholds are fractions in [0, 1], so
// the control works in whole percent and converts on the way in and out.
const toPercent = (fraction) => Math.round((Number(fraction) || 0) * 100);
const fromPercent = (percent) => (Number(percent) || 0) / 100;

function formatDate(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleString();
}

const useStyles = makeStyles({
  panel: {
    position: "absolute",
    top: "10px",
    right: "10px",
    bottom: "10px",
    zIndex: 1000,
    boxSizing: "border-box",
    width: "clamp(300px, 25vw, 360px)",
    maxWidth: "calc(100% - 20px)",
    padding: tokens.spacingHorizontalL,
    display: "flex",
    flexDirection: "column",
    color: tokens.colorNeutralForeground1,
    backgroundColor: tokens.colorNeutralBackground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium,
    boxShadow: tokens.shadow16,
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
  scroll: {
    flex: 1,
    minHeight: 0,
    overflowX: "hidden",
    overflowY: "auto",
    overscrollBehavior: "contain",
    scrollbarGutter: "stable",
    paddingRight: tokens.spacingHorizontalS,
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalM,
    touchAction: "pan-y",
  },
  header: {
    paddingBottom: tokens.spacingVerticalS,
    marginBottom: tokens.spacingVerticalS,
    borderBottom: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
  subtle: {
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase200,
    lineHeight: tokens.lineHeightBase200,
  },
  countRow: {
    display: "flex",
    alignItems: "baseline",
    justifyContent: "space-between",
    fontSize: tokens.fontSizeBase300,
  },
  countValue: {
    fontWeight: tokens.fontWeightSemibold,
  },
  swatch: {
    display: "inline-block",
    width: "10px",
    height: "10px",
    marginRight: tokens.spacingHorizontalXS,
    borderRadius: tokens.borderRadiusSmall,
  },
  damagedSwatch: {
    backgroundColor: tokens.colorStatusDangerBackground3,
  },
  notDamagedSwatch: {
    backgroundColor: tokens.colorStatusSuccessBackground3,
  },
  unknownSwatch: {
    backgroundColor: tokens.colorNeutralForeground3,
  },
  card: {
    padding: `${tokens.spacingVerticalSNudge} ${tokens.spacingHorizontalS}`,
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorNeutralBackground2,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    fontSize: tokens.fontSizeBase200,
    lineHeight: tokens.lineHeightBase200,
    wordBreak: "break-word",
  },
  cardTitle: {
    fontWeight: tokens.fontWeightSemibold,
    marginBottom: tokens.spacingVerticalXXS,
  },
  editedBadge: {
    display: "inline-block",
    marginTop: tokens.spacingVerticalXXS,
    padding: `0 ${tokens.spacingHorizontalXS}`,
    borderRadius: tokens.borderRadiusSmall,
    color: tokens.colorNeutralForegroundOnBrand,
    backgroundColor: tokens.colorBrandBackground,
    fontSize: tokens.fontSizeBase100,
    fontWeight: tokens.fontWeightSemibold,
  },
  buttonColumn: {
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalXS,
  },
  buttonRow: {
    display: "flex",
    gap: tokens.spacingHorizontalS,
  },
  grow: {
    flexGrow: 1,
  },
  stackedField: {
    marginTop: tokens.spacingVerticalS,
  },
  sliderValue: {
    display: "flex",
    justifyContent: "space-between",
    fontSize: tokens.fontSizeBase200,
  },
  changeReadout: {
    padding: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalS}`,
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorNeutralBackground3,
    fontSize: tokens.fontSizeBase200,
    lineHeight: tokens.lineHeightBase200,
  },
  changeHighlight: {
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorBrandForeground1,
  },
  versionList: {
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalXS,
    maxHeight: "160px",
    overflowY: "auto",
  },
  versionRow: {
    padding: `${tokens.spacingVerticalXXS} ${tokens.spacingHorizontalS}`,
    borderRadius: tokens.borderRadiusMedium,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    fontSize: tokens.fontSizeBase100,
    lineHeight: tokens.lineHeightBase200,
  },
  versionTitle: {
    fontWeight: tokens.fontWeightSemibold,
  },
  actions: {
    paddingTop: tokens.spacingVerticalS,
    marginTop: tokens.spacingVerticalS,
    borderTop: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalXS,
  },
});

const PredictionEditorRightPanel = ({
  session,
  counts,
  total,
  editedCount,
  filter,
  setFilter,
  filteredIndices,
  selectedIndex,
  currentBuilding,
  clickAction,
  setClickAction,
  onSetClass,
  onClearOverride,
  onClearAllEdits,
  onPrev,
  onNext,
  threshold,
  setThreshold,
  unknownThreshold,
  setUnknownThreshold,
  baseline,
  changeCount,
  swipeMode = SWIPE_MODE_NONE,
  swipeOn = false,
  onSwipeChange,
  onSave,
  isSaving,
  saveError,
  savedResult,
  versions,
}) => {
  const styles = useStyles();

  const swatchClass = {
    [CLASS_DAMAGED]: styles.damagedSwatch,
    [CLASS_NOT_DAMAGED]: styles.notDamagedSwatch,
    [CLASS_UNKNOWN]: styles.unknownSwatch,
  };

  // Position within the filtered subset, so Prev/Next reads honestly when a
  // filter is narrowing the set.
  const filterPosition = filteredIndices.indexOf(selectedIndex);
  const positionLabel =
    filteredIndices.length === 0
      ? "No buildings match this filter"
      : filterPosition >= 0
        ? `Building ${filterPosition + 1} of ${filteredIndices.length}${
            filter === FILTER_ALL ? "" : " (filtered)"
          }`
        : `${filteredIndices.length} buildings match — press Next to start`;

  const orderedVersions = sortVersionsDescending(versions);
  const swipeAvailable = isSwipeAvailable(swipeMode);
  const thresholdChanged =
    toPercent(threshold) !== toPercent(baseline?.threshold) ||
    toPercent(unknownThreshold) !== toPercent(baseline?.unknownThreshold);

  return (
    <div className={`${styles.panel} labeling-tool-surface`}>
      <div className={styles.header}>
        <Text size={500} block>
          Edit predictions
        </Text>
        <div className={styles.subtle}>
          {total.toLocaleString()} buildings
          {session?.flavor ? ` · ${session.flavor} model` : ""}
        </div>
      </div>

      <div className={styles.scroll}>
        {/* Counts */}
        <div>
          {CLASS_ORDER.map((cls) => (
            <div className={styles.countRow} key={cls}>
              <span>
                <span className={`${styles.swatch} ${swatchClass[cls]}`} />
                {CLASS_LABELS[cls]}
              </span>
              <span className={styles.countValue}>
                {(counts?.[cls] || 0).toLocaleString()}
              </span>
            </div>
          ))}
          <div className={styles.countRow}>
            <span className={styles.subtle}>Edited by hand</span>
            <span className={styles.countValue}>
              {editedCount.toLocaleString()}
            </span>
          </div>
        </div>

        <Divider />

        {/* Imagery comparison. The mode is decided by the layer's imagery, so
            pre-vs-post is simply not on offer when there are no pre-event
            tiles — the label always names the comparison being shown. */}
        <div>
          <Switch
            checked={swipeOn}
            disabled={!swipeAvailable}
            label={swipeToggleLabel(swipeMode)}
            onChange={(_event, data) => onSwipeChange?.(data.checked)}
          />
          <div className={styles.subtle}>{swipeModeHint(swipeMode)}</div>
        </div>

        <Divider />

        {/* Thresholds — only models that expose a score support these. */}
        {session?.supportsThreshold && (
          <div>
            <Field label={`Damage threshold: ${toPercentLabel(threshold)}`}>
              <Slider
                min={0}
                max={100}
                step={1}
                value={toPercent(threshold)}
                onChange={(_event, data) =>
                  setThreshold(fromPercent(data.value))
                }
              />
            </Field>
            <div className={styles.sliderValue}>
              <span className={styles.subtle}>More damaged</span>
              <span className={styles.subtle}>Fewer damaged</span>
            </div>
            <Field
              label={`Unknown threshold: ${toPercentLabel(unknownThreshold)}`}
              className={styles.stackedField}
            >
              <Slider
                min={0}
                max={100}
                step={1}
                value={toPercent(unknownThreshold)}
                onChange={(_event, data) =>
                  setUnknownThreshold(fromPercent(data.value))
                }
              />
            </Field>
            <div className={styles.changeReadout}>
              <span className={styles.changeHighlight}>
                {changeCount.toLocaleString()}
              </span>{" "}
              {changeCount === 1 ? "building would" : "buildings would"} change
              class
              {thresholdChanged
                ? ` versus ${toPercentLabel(baseline?.threshold)} / ${toPercentLabel(
                    baseline?.unknownThreshold
                  )}.`
                : " — thresholds are unchanged."}
            </div>
          </div>
        )}

        {!session?.supportsThreshold && (
          <div className={styles.subtle}>
            This model does not expose a tunable score, so classes come from
            its own decisions plus your edits.
          </div>
        )}

        <Divider />

        {/* Filter + traversal */}
        <Field label="Show">
          <Dropdown
            selectedOptions={[filter]}
            value={FILTER_LABELS[filter] || filter}
            onOptionSelect={(_event, data) =>
              data.optionValue && setFilter(data.optionValue)
            }
          >
            {FILTER_VALUES.map((value) => (
              <Option key={value} value={value}>
                {FILTER_LABELS[value] || value}
              </Option>
            ))}
          </Dropdown>
        </Field>

        <div className={styles.card}>
          <div className={styles.cardTitle}>{positionLabel}</div>
          {currentBuilding ? (
            <>
              <div className={styles.subtle}>ID: {String(currentBuilding.id)}</div>
              {currentBuilding.overtureId && (
                <div className={styles.subtle}>
                  Overture: {String(currentBuilding.overtureId)}
                </div>
              )}
              <div>
                Damage score: {toPercentLabel(currentBuilding.damage, 1)}
                {" · "}
                Unknown: {toPercentLabel(currentBuilding.unknown, 1)}
              </div>
              <div>
                Class:{" "}
                <span className={styles.countValue}>
                  {CLASS_LABELS[currentBuilding.cls] || currentBuilding.cls}
                </span>
              </div>
              {currentBuilding.edited && (
                <span className={styles.editedBadge}>Edited</span>
              )}
            </>
          ) : (
            <div className={styles.subtle}>
              Click a footprint, or use Next, to select a building.
            </div>
          )}
        </div>

        <div className={styles.buttonRow}>
          <Button
            className={styles.grow}
            onClick={onPrev}
            disabled={filteredIndices.length === 0}
          >
            Prev
          </Button>
          <Button
            className={styles.grow}
            onClick={onNext}
            disabled={filteredIndices.length === 0}
          >
            Next
          </Button>
        </div>

        {/* Editing */}
        <div className={styles.buttonColumn}>
          <div className={styles.subtle}>Set the selected building to:</div>
          {CLASS_ORDER.map((cls) => (
            <Button
              key={cls}
              appearance={currentBuilding?.cls === cls ? "primary" : "secondary"}
              disabled={!currentBuilding}
              onClick={() => onSetClass(cls)}
            >
              {`${CLASS_LABELS[cls]} (${CLASS_HOTKEYS[cls]})`}
            </Button>
          ))}
          <Button
            disabled={!currentBuilding?.edited}
            onClick={onClearOverride}
          >
            Undo this edit
          </Button>
        </div>

        <Field label="Clicking a footprint">
          <RadioGroup
            value={clickAction}
            onChange={(_event, data) => setClickAction(data.value)}
          >
            <Radio value="cycle" label="Cycles its class" />
            {CLASS_ORDER.map((cls) => (
              <Radio
                key={cls}
                value={cls}
                label={`Sets ${CLASS_LABELS[cls]}`}
              />
            ))}
          </RadioGroup>
        </Field>

        <Button disabled={editedCount === 0} onClick={onClearAllEdits}>
          {editedCount === 0
            ? "No manual edits"
            : `Undo all ${editedCount.toLocaleString()} edits`}
        </Button>

        <Divider />

        {/* Saved versions */}
        <div>
          <div className={styles.cardTitle}>Saved versions</div>
          {orderedVersions.length === 0 ? (
            <div className={styles.subtle}>
              No edited versions yet. Saving creates version 1 — the model&rsquo;s
              own predictions are never overwritten.
            </div>
          ) : (
            <div className={styles.versionList}>
              {orderedVersions.map((version) => (
                <div className={styles.versionRow} key={version.version}>
                  <div className={styles.versionTitle}>
                    Version {version.version}
                  </div>
                  <div className={styles.subtle}>
                    {formatDate(version.createdAt)}
                    {version.createdBy ? ` · ${version.createdBy}` : ""}
                  </div>
                  <div className={styles.subtle}>
                    Threshold {toPercentLabel(version.threshold)} ·{" "}
                    {(version.editedCount || 0).toLocaleString()} edited
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <KeyboardShortcutHelp shortcuts={PREDICTION_EDITOR_SHORTCUTS} />
      </div>

      <div className={styles.actions}>
        {saveError && (
          <MessageBar intent="error">
            <MessageBarBody>
              <MessageBarTitle>Save failed</MessageBarTitle>
              {saveError}
            </MessageBarBody>
          </MessageBar>
        )}
        {!saveError && savedResult && (
          <MessageBar intent="success">
            <MessageBarBody>
              <MessageBarTitle>Version {savedResult.version} saved</MessageBarTitle>
              {(savedResult.editedCount || 0).toLocaleString()} edited buildings.
            </MessageBarBody>
          </MessageBar>
        )}
        <Button appearance="primary" onClick={onSave} disabled={isSaving}>
          {isSaving ? "Saving…" : "Save as new version"}
        </Button>
      </div>
    </div>
  );
};

PredictionEditorRightPanel.propTypes = {
  session: PropTypes.shape({
    flavor: PropTypes.string,
    supportsThreshold: PropTypes.bool,
    buildingCount: PropTypes.number,
  }),
  counts: PropTypes.object.isRequired,
  total: PropTypes.number.isRequired,
  editedCount: PropTypes.number.isRequired,
  filter: PropTypes.string.isRequired,
  setFilter: PropTypes.func.isRequired,
  filteredIndices: PropTypes.arrayOf(PropTypes.number).isRequired,
  selectedIndex: PropTypes.number.isRequired,
  currentBuilding: PropTypes.shape({
    id: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
    overtureId: PropTypes.string,
    damage: PropTypes.number,
    unknown: PropTypes.number,
    cls: PropTypes.string,
    edited: PropTypes.bool,
  }),
  clickAction: PropTypes.string.isRequired,
  setClickAction: PropTypes.func.isRequired,
  onSetClass: PropTypes.func.isRequired,
  onClearOverride: PropTypes.func.isRequired,
  onClearAllEdits: PropTypes.func.isRequired,
  onPrev: PropTypes.func.isRequired,
  onNext: PropTypes.func.isRequired,
  threshold: PropTypes.number.isRequired,
  setThreshold: PropTypes.func.isRequired,
  unknownThreshold: PropTypes.number.isRequired,
  setUnknownThreshold: PropTypes.func.isRequired,
  baseline: PropTypes.shape({
    threshold: PropTypes.number,
    unknownThreshold: PropTypes.number,
  }).isRequired,
  changeCount: PropTypes.number.isRequired,
  swipeMode: PropTypes.string,
  swipeOn: PropTypes.bool,
  onSwipeChange: PropTypes.func,
  onSave: PropTypes.func.isRequired,
  isSaving: PropTypes.bool.isRequired,
  saveError: PropTypes.string,
  savedResult: PropTypes.shape({
    version: PropTypes.number,
    gpkgUrl: PropTypes.string,
    editedCount: PropTypes.number,
  }),
  versions: PropTypes.array.isRequired,
};

export default PredictionEditorRightPanel;
