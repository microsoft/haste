// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import {
  Dialog,
  DialogSurface,
  Button,
  Field,
  Input,
  tokens,
} from "@fluentui/react-components";
import { FluentIcon } from "../util/icons";

import proptypes from "prop-types";

const CreateEditSourceTypeModal = ({ onClose }) => {
  CreateEditSourceTypeModal.propTypes = {
    onClose: proptypes.func.isRequired,
  };

  return (
    <Dialog
      open={true}
      onOpenChange={(_, d) => {
        if (!d.open) onClose();
      }}
    >
      <DialogSurface style={{ padding: 0 }}>
        <div style={headerStyle}>
          <div className="d-flex align-items-center">
            <FluentIcon name="UserEvent" className="me-2 modal-icon" />
            <p style={headingStyle}>New Source Type</p>
          </div>
          <Button
            appearance="subtle"
            icon={<FluentIcon name="Cancel" />}
            aria-label="Close popup modal"
            onClick={onClose}
          />
        </div>
        <div style={bodyStyle} className="modal-form-body">
          <div className="row mb-2">
            <div className="col-12">
              <Field label="Name" required>
                <Input />
              </Field>
            </div>
          </div>
          <div className="row mb-4">
            <div className="col-12">
              <Field label="Base URL" required>
                <Input />
              </Field>
            </div>
          </div>
          <div className="row">
            <div className="col-12 d-flex justify-content-end">
              <Button appearance="primary" className="me-2">
                Submit
              </Button>
              <Button onClick={onClose}>Cancel</Button>
            </div>
          </div>
        </div>
      </DialogSurface>
    </Dialog>
  );
};

const headerStyle = {
  flex: "1 1 auto",
  borderTop: `4px solid ${tokens.colorBrandBackground}`,
  display: "flex",
  alignItems: "center",
  padding: "12px 12px 14px 24px",
};
const headingStyle = { fontWeight: 600, fontSize: "20px", margin: 0 };
const bodyStyle = {
  flex: "4 4 auto",
  padding: "0 24px 24px 24px",
  maxHeight: "75vh",
  overflowY: "auto",
};

export default CreateEditSourceTypeModal;
