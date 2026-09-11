import PropTypes from "prop-types";
import {
  Button,
  ProgressBar,
  Spinner,
  makeStyles,
  tokens,
} from "@fluentui/react-components";

import { FluentIcon } from "../util/icons";
import {
  formatBytes,
  getLoadProgress,
} from "./InteractiveLabeler/interactiveLabelerLoading";

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
  errorIcon: {
    color: tokens.colorPaletteRedForeground1,
  },
  message: {
    margin: `${tokens.spacingVerticalS} 0 0`,
    color: tokens.colorNeutralForeground2,
    fontSize: tokens.fontSizeBase300,
    lineHeight: tokens.lineHeightBase400,
    overflowWrap: "anywhere",
  },
  actions: {
    display: "flex",
    justifyContent: "flex-end",
    gap: tokens.spacingHorizontalS,
    marginTop: tokens.spacingVerticalL,
  },
});

const WorkspaceLoader = ({
  eyebrow,
  title,
  steps,
  loadState,
  error,
  errorTitle,
  onRetry,
  onGoBack,
}) => {
  const styles = useStyles();
  if (!loadState && !error) return null;

  if (error) {
    return (
      <div
        className={styles.overlay}
        role="alert"
        aria-live="assertive"
        data-route-loading="true"
      >
        <div className={styles.dialog}>
          <div className={`${styles.eyebrow} ${styles.errorIcon}`}>
            {eyebrow}
          </div>
          <h2 className={styles.title}>{errorTitle}</h2>
          <p className={styles.message}>{error}</p>
          <div className={styles.actions}>
            {onGoBack && <Button onClick={onGoBack}>Go back</Button>}
            {onRetry && (
              <Button appearance="primary" onClick={onRetry}>
                Retry
              </Button>
            )}
          </div>
        </div>
      </div>
    );
  }

  const activeStep = Math.min(loadState.step, steps.length - 1);
  return (
    <div
      className={styles.overlay}
      role="status"
      aria-live="polite"
      aria-busy="true"
      data-route-loading="true"
    >
      <div className={styles.dialog}>
        <div className={styles.eyebrow}>{eyebrow}</div>
        <h2 className={styles.title}>{title}</h2>
        <div className={styles.summary}>
          <span>{steps[activeStep]}</span>
          <span>
            Step {activeStep + 1} of {steps.length}
          </span>
        </div>
        <ProgressBar
          value={getLoadProgress(activeStep, steps.length)}
          max={1}
          aria-label={`Loading step ${activeStep + 1} of ${steps.length}`}
        />
        <ol className={styles.steps}>
          {steps.map((label, index) => {
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

WorkspaceLoader.propTypes = {
  eyebrow: PropTypes.string.isRequired,
  title: PropTypes.string.isRequired,
  steps: PropTypes.arrayOf(PropTypes.string).isRequired,
  loadState: PropTypes.shape({
    step: PropTypes.number.isRequired,
    loaded: PropTypes.number,
    total: PropTypes.number,
  }),
  error: PropTypes.string,
  errorTitle: PropTypes.string.isRequired,
  onRetry: PropTypes.func,
  onGoBack: PropTypes.func,
};

export default WorkspaceLoader;
