// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Edit-mode control panel for the results page: class counts, the filter +
// prev/next traversal over the filtered set, the threshold sliders (only for
// models that support them), the live "would change class" readout, the save
// action, and the saved-version history.
//
// The history is append-only and every entry is downloadable: the GeoPackage
// for a version is written when it is saved, so it can be exported even when
// its per-building sidecar has not been backfilled yet and the map therefore
// cannot draw it. Downloads go through GetModelArtifact like everything else
// on this page, never a blob SAS URL.
//
// This is the overlay the pencil affordance opens over the results view. It
// was the standalone Prediction Editor's right panel and is deliberately
// unchanged in look: the same review controls, now on the map the analyst was
// already looking at. The swipe toggle is gone because the results page
// always has the swipe map up; the hint under the header names the divider
// instead. Layout and interaction mirror BuildingValidationRightPanel so the
// review screens feel like one tool, and every colour comes from Fluent
// tokens, so the panel follows the light/dark theme.
import PropTypes from "prop-types";
import {
  Button,
  Divider,
  Dropdown,
  Field,
  Badge,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Option,
  Slider,
  Text,
  Tooltip,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
import KeyboardShortcutHelp from "../KeyboardShortcutHelp";
import { PREDICTION_EDIT_SHORTCUTS } from "../keyboardShortcuts";
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
import { describeServedVersion } from "./predictionResults";
import { describeVersionDownload } from "./predictionVersions";

const CLASS_ORDER = [CLASS_DAMAGED, CLASS_NOT_DAMAGED, CLASS_UNKNOWN];

// Keyboard hints shown on the class buttons, matching PREDICTION_EDIT_SHORTCUTS.
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
    // A column flex item shrinks to fit by default, so once the panel's
    // content is taller than the panel every block in here gets squeezed —
    // buttons lose the top and bottom of their own label rather than the
    // column simply scrolling. Nothing in this panel should ever be shorter
    // than its content.
    "& > *": {
      flexShrink: 0,
    },
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
    // Same reason as `scroll`: these stacks hold buttons, and a squeezed
    // button clips its label instead of getting a scrollbar.
    "& > *": {
      flexShrink: 0,
    },
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
  // The version the map is drawing right now, so the history never leaves the
  // analyst guessing which one they are editing on top of.
  servedVersionRow: {
    borderColor: tokens.colorBrandStroke1,
    backgroundColor: tokens.colorNeutralBackground1Selected,
  },
  versionHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: tokens.spacingHorizontalXS,
  },
  // Badge + download sit together on the right of a version row.
  versionActions: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalXS,
  },
  versionNote: {
    marginBottom: tokens.spacingVerticalXS,
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

const PredictionEditPanel = ({
  flavor = "",
  supportsThreshold = true,
  counts,
  total,
  editedCount,
  filter,
  setFilter,
  filteredIndices,
  selectedIndex,
  currentBuilding,
  activeClass,
  setActiveClass,
  onApplyToSelected,
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
  swipeHint = "",
  onExit,
  onSave,
  isSaving,
  saveError,
  savedResult,
  versions,
  activeVersion = null,
  onDownloadVersion,
  reportDivergence = null,
  thresholdNote = "",
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
          {flavor ? ` · ${flavor} model` : ""}
        </div>
        <div className={styles.subtle}>
          {describeServedVersion(activeVersion)}
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

        {/* The results page always has the swipe map up, so there is nothing
            to switch on here — only the divider's directions to explain. */}
        {swipeHint ? <div className={styles.subtle}>{swipeHint}</div> : null}

        {swipeHint ? <Divider /> : null}

        {/* Thresholds — only models that expose a real score support these. */}
        {supportsThreshold && (
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

        {!supportsThreshold && (
          <div className={styles.subtle}>
            {thresholdNote ||
              "This model does not expose a tunable score, so classes come from its own decisions plus your edits."}
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

        {/* Editing — one picker decides what every gesture applies. */}
        <Field label="Class to apply">
          <div className={styles.buttonColumn}>
            {CLASS_ORDER.map((cls) => (
              <Button
                key={cls}
                appearance={activeClass === cls ? "primary" : "secondary"}
                onClick={() => setActiveClass(cls)}
              >
                {`${CLASS_LABELS[cls]} (${CLASS_HOTKEYS[cls]})`}
              </Button>
            ))}
          </div>
        </Field>
        <div className={styles.subtle}>
          Click a footprint — or Ctrl+drag to box-select several — to set it to{" "}
          {CLASS_LABELS[activeClass] || activeClass}. Right-click undoes an
          edit.
        </div>

        <div className={styles.buttonColumn}>
          <Button disabled={!currentBuilding} onClick={onApplyToSelected}>
            Apply to selected (Enter)
          </Button>
          <Button
            disabled={!currentBuilding?.edited}
            onClick={onClearOverride}
          >
            Undo this edit
          </Button>
        </div>

        <Button disabled={editedCount === 0} onClick={onClearAllEdits}>
          {editedCount === 0
            ? "No manual edits"
            : `Undo all ${editedCount.toLocaleString()} edits`}
        </Button>

        <Divider />

        {/* Saved versions */}
        <div>
          <div className={styles.cardTitle}>Saved versions</div>
          {reportDivergence && (
            <MessageBar intent="warning" className={styles.versionNote}>
              <MessageBarBody>
                <MessageBarTitle>{reportDivergence.title}</MessageBarTitle>
                {reportDivergence.body}
              </MessageBarBody>
            </MessageBar>
          )}
          {orderedVersions.length === 0 ? (
            <div className={styles.subtle}>
              No edited versions yet. Saving creates version 1 — the model&rsquo;s
              own predictions are never overwritten.
            </div>
          ) : (
            <div className={styles.versionList}>
              {orderedVersions.map((version) => (
                <div
                  className={`${styles.versionRow} ${
                    version.version === activeVersion
                      ? styles.servedVersionRow
                      : ""
                  }`}
                  key={version.version}
                >
                  <div className={styles.versionHeader}>
                    <span className={styles.versionTitle}>
                      Version {version.version}
                    </span>
                    <span className={styles.versionActions}>
                      {version.version === activeVersion && (
                        <Badge appearance="tint" color="brand">
                          On the map
                        </Badge>
                      )}
                      {/* Every saved version is downloadable, including the
                          ones whose sidecar has not been backfilled yet: the
                          GeoPackage is written at save time, so it exists
                          even when the map cannot draw that version. */}
                      {typeof onDownloadVersion === "function" && (
                        <Tooltip
                          content={describeVersionDownload(version.version)}
                          relationship="label"
                        >
                          <Button
                            appearance="subtle"
                            size="small"
                            icon={<FluentIcon name="download" />}
                            onClick={() => onDownloadVersion(version.version)}
                          />
                        </Tooltip>
                      )}
                    </span>
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

        <KeyboardShortcutHelp shortcuts={PREDICTION_EDIT_SHORTCUTS} />
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
        <Button
          icon={<FluentIcon name="cancel" />}
          onClick={onExit}
          disabled={isSaving}
        >
          Done editing
        </Button>
      </div>
    </div>
  );
};

PredictionEditPanel.propTypes = {
  flavor: PropTypes.string,
  supportsThreshold: PropTypes.bool,
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
  activeClass: PropTypes.string.isRequired,
  setActiveClass: PropTypes.func.isRequired,
  onApplyToSelected: PropTypes.func.isRequired,
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
  swipeHint: PropTypes.string,
  onExit: PropTypes.func.isRequired,
  onSave: PropTypes.func.isRequired,
  isSaving: PropTypes.bool.isRequired,
  saveError: PropTypes.string,
  savedResult: PropTypes.shape({
    version: PropTypes.number,
    gpkgUrl: PropTypes.string,
    predictionAttrsUrl: PropTypes.string,
    editedCount: PropTypes.number,
    buildingCount: PropTypes.number,
  }),
  versions: PropTypes.array.isRequired,
  activeVersion: PropTypes.number,
  onDownloadVersion: PropTypes.func,
  reportDivergence: PropTypes.shape({
    title: PropTypes.string,
    body: PropTypes.string,
  }),
  thresholdNote: PropTypes.string,
};

export default PredictionEditPanel;
