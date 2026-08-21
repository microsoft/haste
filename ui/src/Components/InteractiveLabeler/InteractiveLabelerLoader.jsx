// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import PropTypes from "prop-types";
import {
  ProgressBar,
  Spinner,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";

const LOAD_STEPS = [
  "Loading imagery configuration",
  "Finding model artifacts",
  "Loading building tiles",
  "Loading model features",
  "Restoring saved labels",
  "Preparing the map",
];

const useStyles = makeStyles({
  overlay: {
    position: "absolute",
    inset: 0,
    zIndex: 2100,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: tokens.spacingHorizontalL,
    backgroundColor: tokens.colorNeutralBackgroundAlpha2,
    backdropFilter: "blur(3px)",
  },
  dialog: {
    boxSizing: "border-box",
    width: "min(440px, calc(100vw - 32px))",
    padding: tokens.spacingHorizontalXXL,
    borderRadius: tokens.borderRadiusLarge,
    color: tokens.colorNeutralForeground1,
    backgroundColor: tokens.colorNeutralBackground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    boxShadow: tokens.shadow64,
  },
  eyebrow: {
    color: tokens.colorBrandForeground1,
    fontSize: tokens.fontSizeBase100,
    fontWeight: tokens.fontWeightSemibold,
    textTransform: "uppercase",
  },
  title: {
    margin: `${tokens.spacingVerticalXS} 0 ${tokens.spacingVerticalXS}`,
    fontSize: tokens.fontSizeBase500,
    lineHeight: tokens.lineHeightBase600,
    fontWeight: tokens.fontWeightSemibold,
  },
  summary: {
    display: "flex",
    justifyContent: "space-between",
    gap: tokens.spacingHorizontalM,
    marginBottom: tokens.spacingVerticalS,
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase200,
  },
  steps: {
    display: "grid",
    gap: tokens.spacingVerticalS,
    margin: `${tokens.spacingVerticalL} 0 0`,
    padding: 0,
    listStyle: "none",
  },
  step: {
    display: "grid",
    gridTemplateColumns: "20px minmax(0, 1fr) auto",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
    minHeight: "24px",
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase200,
  },
  active: {
    color: tokens.colorNeutralForeground1,
    fontWeight: tokens.fontWeightSemibold,
  },
  done: {
    color: tokens.colorNeutralForeground2,
  },
  icon: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    color: tokens.colorBrandForeground1,
  },
  pending: {
    width: "6px",
    height: "6px",
    borderRadius: "50%",
    backgroundColor: tokens.colorNeutralStroke1,
  },
  weight: {
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase100,
    fontWeight: tokens.fontWeightRegular,
    whiteSpace: "nowrap",
  },
});

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  const unitIndex = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length - 1
  );
  const value = bytes / 1024 ** unitIndex;
  const decimalPlaces = unitIndex === 2 ? 1 : unitIndex === 0 || value >= 10 ? 0 : 1;
  return `${value.toFixed(decimalPlaces)} ${units[unitIndex]}`;
}

const InteractiveLabelerLoader = ({ loadState }) => {
  const styles = useStyles();
  if (!loadState) return null;

  const activeStep = Math.min(loadState.step, LOAD_STEPS.length - 1);

  return (
    <div
      className={styles.overlay}
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <div className={styles.dialog}>
        <div className={styles.eyebrow}>Interactive labeler</div>
        <h2 className={styles.title}>Preparing your workspace</h2>
        <div className={styles.summary}>
          <span>{LOAD_STEPS[activeStep]}</span>
          <span>
            Step {activeStep + 1} of {LOAD_STEPS.length}
          </span>
        </div>
        <ProgressBar
          value={activeStep / LOAD_STEPS.length}
          max={1}
          aria-label={`Loading step ${activeStep + 1} of ${LOAD_STEPS.length}`}
        />
        <ol className={styles.steps}>
          {LOAD_STEPS.map((label, index) => {
            const isDone = index < activeStep;
            const isActive = index === activeStep;
            const weight =
              isActive && loadState.loaded
                ? loadState.total
                  ? `${formatBytes(loadState.loaded)} of ${formatBytes(loadState.total)}`
                  : `${formatBytes(loadState.loaded)} loaded`
                : "";
            return (
              <li
                className={`${styles.step} ${
                  isActive ? styles.active : isDone ? styles.done : ""
                }`}
                key={label}
              >
                <span className={styles.icon} aria-hidden="true">
                  {isDone ? (
                    <FluentIcon name="Checkmark" />
                  ) : isActive ? (
                    <Spinner size="extra-tiny" />
                  ) : (
                    <span className={styles.pending} />
                  )}
                </span>
                <span>{label}</span>
                {weight && <span className={styles.weight}>{weight}</span>}
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
};

InteractiveLabelerLoader.propTypes = {
  loadState: PropTypes.shape({
    step: PropTypes.number.isRequired,
    loaded: PropTypes.number,
    total: PropTypes.number,
  }),
};

export default InteractiveLabelerLoader;