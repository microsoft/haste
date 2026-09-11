// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import PropTypes from "prop-types";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle } from "@fluentui/react-components";

export default function PredictionDiscardDialog({ blocked, onAnswer }) {
  return (
    <Dialog open onOpenChange={(_event, data) => { if (!data.open) onAnswer(false); }}>
      <DialogSurface><DialogBody>
        <DialogTitle>{blocked ? "Operation in progress" : "Discard unsaved edits?"}</DialogTitle>
        <DialogContent>{blocked
          ? "Wait for the save or version load to finish before leaving."
          : "Your class assignments and threshold changes have not been saved. Leaving or switching versions discards this draft."}</DialogContent>
        <DialogActions>
          <Button onClick={() => onAnswer(false)}>{blocked ? "Close" : "Keep editing"}</Button>
          {!blocked && <Button appearance="primary" onClick={() => onAnswer(true)}>Discard edits</Button>}
        </DialogActions>
      </DialogBody></DialogSurface>
    </Dialog>
  );
}
PredictionDiscardDialog.propTypes = { blocked: PropTypes.bool, onAnswer: PropTypes.func.isRequired };
