// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// The results page's note about its predicted-building layer.
//
// An empty map is the worst possible answer to "where are the predictions?",
// and it is the answer an embedding model gives by default: it ships no
// raster at all, so if the footprint tiles are not built yet there is
// literally nothing on screen. This card says which of those it is —
// loading, still being prepared by the tiling job, nothing to show, or
// broken — and, when the job has given up, offers to queue it again.
//
// All copy comes from predictionResults.js / predictionPrep.js so the wording
// is decided in pure, unit-tested code rather than in JSX.
import PropTypes from "prop-types";
import {
  Button,
  MessageBar,
  MessageBarActions,
  MessageBarBody,
  MessageBarTitle,
  ProgressBar,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
import {
  FOOTPRINTS_LOADING,
  FOOTPRINTS_PREPARING,
  describeFootprintStatus,
} from "./predictionResults.js";
import {
  PREP_PHASE_FAILED,
  PREP_PHASE_TIMED_OUT,
  describeOutstandingArtifacts,
  prepStatusLabel,
} from "./predictionPrep.js";

const useStyles = makeStyles({
  // Centred under the app header, clear of the pre/post imagery blocks in the
  // corners and below the edit panel's stacking level.
  root: {
    position: "absolute",
    top: "66px",
    left: "50%",
    transform: "translateX(-50%)",
    zIndex: 900,
    boxSizing: "border-box",
    width: "min(560px, calc(100% - 32px))",
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalXS,
    padding: tokens.spacingHorizontalM,
    color: tokens.colorNeutralForeground1,
    backgroundColor: tokens.colorNeutralBackground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium,
    boxShadow: tokens.shadow16,
  },
  detail: {
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase200,
    lineHeight: tokens.lineHeightBase200,
  },
  statusRow: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: tokens.spacingHorizontalXS,
    color: tokens.colorNeutralForeground2,
    fontSize: tokens.fontSizeBase200,
  },
  statusValue: {
    padding: `${tokens.spacingVerticalXXS} ${tokens.spacingHorizontalS}`,
    borderRadius: tokens.borderRadiusCircular,
    color: tokens.colorNeutralForeground1,
    backgroundColor: tokens.colorNeutralBackground4,
    fontWeight: tokens.fontWeightSemibold,
  },
});

const PredictionStatusNote = ({
  status,
  prepState = null,
  session = null,
  error = "",
  detail = "",
  onRetry,
  onDismiss,
}) => {
  const styles = useStyles();
  // A load failure carries its own reason; otherwise the tiling job's own
  // status message, then the server's readiness explanation, beat our generic
  // copy — they know which workflow the model came from.
  const message = describeFootprintStatus(status, {
    detail: error || prepState?.statusMessage || detail,
  });
  if (!message) return null;

  const isPreparing = status === FOOTPRINTS_PREPARING;
  const isWaiting =
    isPreparing &&
    prepState?.phase !== PREP_PHASE_FAILED &&
    prepState?.phase !== PREP_PHASE_TIMED_OUT;
  const canRetry =
    typeof onRetry === "function" &&
    (prepState?.phase === PREP_PHASE_FAILED ||
      prepState?.phase === PREP_PHASE_TIMED_OUT);
  const outstanding = isPreparing ? describeOutstandingArtifacts(session) : "";

  return (
    <div className={styles.root} role="status" aria-live="polite">
      <MessageBar intent={canRetry ? "warning" : message.intent}>
        <MessageBarBody>
          <MessageBarTitle>{message.title}</MessageBarTitle>
          {message.body}
        </MessageBarBody>
        {(canRetry || typeof onDismiss === "function") && (
          <MessageBarActions
            containerAction={
              typeof onDismiss === "function" ? (
                <Button
                  appearance="transparent"
                  aria-label="Dismiss"
                  icon={<FluentIcon name="cancel" />}
                  onClick={onDismiss}
                />
              ) : undefined
            }
          >
            {canRetry && (
              <Button onClick={() => onRetry(true)}>Try again</Button>
            )}
          </MessageBarActions>
        )}
      </MessageBar>

      {(isWaiting || status === FOOTPRINTS_LOADING) && (
        <ProgressBar aria-label="Preparing predicted buildings" />
      )}

      {isPreparing && (
        <div className={styles.statusRow}>
          <span>Status</span>
          <span className={styles.statusValue}>
            {prepStatusLabel(prepState?.status)}
          </span>
          {outstanding ? <span>{outstanding}</span> : null}
        </div>
      )}

      {prepState?.error ? (
        <div className={styles.detail}>{prepState.error}</div>
      ) : null}
    </div>
  );
};

PredictionStatusNote.propTypes = {
  status: PropTypes.string.isRequired,
  prepState: PropTypes.shape({
    phase: PropTypes.string,
    status: PropTypes.string,
    statusMessage: PropTypes.string,
    attempt: PropTypes.number,
    error: PropTypes.string,
  }),
  session: PropTypes.object,
  error: PropTypes.string,
  detail: PropTypes.string,
  onRetry: PropTypes.func,
  onDismiss: PropTypes.func,
};

export default PredictionStatusNote;
