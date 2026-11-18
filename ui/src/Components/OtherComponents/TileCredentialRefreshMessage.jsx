// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import {
  Button,
  MessageBar,
  MessageBarBody,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import PropTypes from "prop-types";

const useStyles = makeStyles({
  root: {
    position: "absolute",
    top: tokens.spacingVerticalM,
    left: "50%",
    zIndex: 1200,
    width: "min(560px, calc(100% - 32px))",
    transform: "translateX(-50%)",
    boxShadow: tokens.shadow8,
  },
});

const TileCredentialRefreshMessage = ({ visible, onRetry }) => {
  const styles = useStyles();
  if (!visible) return null;

  return (
    <MessageBar className={styles.root} intent="error" role="alert">
      <MessageBarBody>
        Imagery access could not be refreshed. Existing imagery is retained.
      </MessageBarBody>
      <Button size="small" onClick={onRetry}>
        Retry
      </Button>
      <Button size="small" onClick={() => window.location.reload()}>
        Reload
      </Button>
    </MessageBar>
  );
};

TileCredentialRefreshMessage.propTypes = {
  visible: PropTypes.bool.isRequired,
  onRetry: PropTypes.func.isRequired,
};

export default TileCredentialRefreshMessage;
