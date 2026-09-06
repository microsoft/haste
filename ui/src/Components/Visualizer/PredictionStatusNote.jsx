// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// PR136's status-card layout, without job/preparation state or implicit retries.
import PropTypes from "prop-types";
import {
  Button, MessageBar, MessageBarActions, MessageBarBody, MessageBarTitle,
  ProgressBar, makeStyles, tokens,
} from "@fluentui/react-components";
import { describeFootprintStatus, FOOTPRINTS_LOADING } from "./predictionResults.js";

const useStyles = makeStyles({
  root: {
    boxSizing: "border-box", width: "100%", padding: tokens.spacingHorizontalM,
    color: tokens.colorNeutralForeground1, backgroundColor: tokens.colorNeutralBackground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium, boxShadow: tokens.shadow16,
    pointerEvents: "auto",
  },
});

export default function PredictionStatusNote({ status, detail, onRetry }) {
  const styles = useStyles();
  const message = describeFootprintStatus(status, detail);
  if (!message) return null;
  return (
    <div className={styles.root} role="status" aria-live="polite">
      <MessageBar intent={message.intent}>
        <MessageBarBody>
          <MessageBarTitle>{message.title}</MessageBarTitle>
          {message.body}
        </MessageBarBody>
        {status !== FOOTPRINTS_LOADING && onRetry && (
          <MessageBarActions>
            <Button onClick={onRetry}>Retry loading results</Button>
          </MessageBarActions>
        )}
      </MessageBar>
      {status === FOOTPRINTS_LOADING && <ProgressBar aria-label="Loading predicted buildings" />}
    </div>
  );
}
PredictionStatusNote.propTypes = {
  status: PropTypes.string.isRequired,
  detail: PropTypes.string,
  onRetry: PropTypes.func,
};
