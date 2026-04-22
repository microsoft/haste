// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useId } from "@fluentui/react-hooks";
import {
  getTheme,
  mergeStyleSets,
  FontWeights,
  Modal,
  TextField,
  FontIcon,
} from "@fluentui/react";
import {
  DefaultButton,
  IconButton,
  PrimaryButton,
} from "@fluentui/react/lib/Button";

import proptypes from "prop-types";

const CreateEditBaseModelModal = ({ onClose }) => {
  CreateEditBaseModelModal.propTypes = {
    onClose: proptypes.func.isRequired,
  };

  const titleId = useId("title");

  return (
    <Modal
      titleAriaId={titleId}
      isOpen={true}
      onDismiss={onClose}
      isBlocking={true}
      containerClassName={contentStyles.container}
    >
      <div className={contentStyles.header}>
        <div className="d-flex align-items-center">
          <FontIcon iconName={"UserEvent"} className="me-2 modal-icon" />
          <p className={contentStyles.heading} id={titleId}>
            New Base Model
          </p>
        </div>
        <IconButton
          styles={iconButtonStyles}
          iconProps={cancelIcon}
          ariaLabel="Close popup modal"
          onClick={onClose}
        />
      </div>
      <div className={`${contentStyles.body} modal-form-body`}>
        <div className="row mb-2">
          <div className="col-12">
            <TextField label="Name" required />
          </div>
        </div>
        <div className="row mb-4">
          <div className="col-12">
            <TextField label="Source URL" required />
          </div>
        </div>
        <div className="row">
          <div className="col-12 d-flex justify-content-end">
            <PrimaryButton className="me-2">Submit</PrimaryButton>
            <DefaultButton onClick={onClose}>Cancel</DefaultButton>
          </div>
        </div>
      </div>
    </Modal>
  );
};

const cancelIcon = { iconName: "Cancel" };

const theme = getTheme();
const contentStyles = mergeStyleSets({
  container: {
    display: "flex",
    flexFlow: "column nowrap",
    alignItems: "stretch",
  },
  header: [
    theme.fonts.xLargePlus,
    {
      flex: "1 1 auto",
      borderTop: `4px solid ${theme.palette.themePrimary}`,
      color: theme.palette.neutralPrimary,
      display: "flex",
      alignItems: "center",
      fontWeight: FontWeights.semibold,
      padding: "12px 12px 14px 24px",
    },
  ],
  heading: {
    color: theme.palette.neutralPrimary,
    fontWeight: FontWeights.semibold,
    fontSize: "20px",
    margin: "0",
  },
  body: {
    flex: "4 4 auto",
    padding: "0 24px 24px 24px",
    overflowY: "hidden",
    selectors: {
      p: { margin: "14px 0" },
      "p:first-child": { marginTop: 0 },
      "p:last-child": { marginBottom: 0 },
    },
  },
});

const iconButtonStyles = {
  root: {
    color: theme.palette.neutralPrimary,
    marginLeft: "auto",
    marginTop: "4px",
    marginRight: "2px",
  },
  rootHovered: {
    color: theme.palette.neutralDark,
  },
};

export default CreateEditBaseModelModal;
