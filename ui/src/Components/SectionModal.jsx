// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useContext } from "react";
import {
  Dialog,
  DialogSurface,
  Button,
} from "@fluentui/react-components";

import { FluentIcon } from "../util/icons";
import { setGuidedTourState } from "./GuidedTourHelper";


import { AppContext } from "../AppContext";
import proptypes from "prop-types";

const SectionModal = ({ title, body, onClose, icon, modalCurrentTour }) => {
  SectionModal.propTypes = {
    title: proptypes.string.isRequired,
    body: proptypes.node.isRequired,
    onClose: proptypes.func.isRequired,
    icon: proptypes.string.isRequired,
    modalCurrentTour: proptypes.string,
  };

  const { initCurrentTour, appParams } = useContext(AppContext);

  return (
    <Dialog
      open={true}
      onOpenChange={(_, d) => {
        if (!d.open) onClose();
      }}
    >
      <DialogSurface style={{ padding: 0 }}>
        <div style={headerStyle}>
          <div className="d-flex align-items-center flex-grow-1">
            <FluentIcon name={icon} className="me-2 modal-icon" />
            <p className="m-0" style={headingStyle}>
              {title}
            </p>
          </div>
          <div className="">
            {modalCurrentTour && (
              <Button
                appearance="subtle"
                icon={<FluentIcon name="Help" />}
                aria-label="Help"
                onClick={() => setGuidedTourState(false, initCurrentTour, modalCurrentTour, appParams.guidedTourProperties)}
              />
            )}
            <Button
              appearance="subtle"
              icon={<FluentIcon name="Cancel" />}
              aria-label="Close popup modal"
              onClick={onClose}
            />
          </div>
        </div>
        <div style={bodyStyle}>{body}</div>
      </DialogSurface>
    </Dialog>
  );
};

const headerStyle = {
  flex: "1 1 auto",
  display: "flex",
  alignItems: "center",
  padding: "12px 24px 14px",
};
const headingStyle = { fontWeight: 600, fontSize: "20px", margin: 0 };
const bodyStyle = {
  flex: "4 4 auto",
  padding: "0 24px 24px 24px",
  maxHeight: "75vh",
  overflowY: "auto",
};

export default SectionModal;
