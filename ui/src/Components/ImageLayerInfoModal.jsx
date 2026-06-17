// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useState } from "react";
import { useId } from "@fluentui/react-hooks";
import {
  getTheme,
  mergeStyleSets,
  FontWeights,
  Modal,
  Link,
  FontIcon,
  Text,
  Label
} from "@fluentui/react";
import { safeHref } from "../util/validation";

import { DefaultButton, IconButton } from "@fluentui/react/lib/Button";

import { CopyToClipboard } from "react-copy-to-clipboard";

import proptypes from "prop-types";

const ImageLayerInfoModal = ({ onClose, imageLayer }) => {
  ImageLayerInfoModal.propTypes = {
    onClose: proptypes.func.isRequired,
    imageLayer: proptypes.object.isRequired,
  };

  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    setCopied(true);
    setTimeout(() => setCopied(false), 2000); // Reset copied state after 2 seconds
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
          <FontIcon iconName={"FileImage"} className="me-2 modal-icon" />
          <p className={contentStyles.heading} id={titleId}>
            Image Layer Information
            
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
        <div className="row mb-3">
          <div className="col-12">
            <Label className="m-0 p-0">Layer Name</Label>
            <Text>{imageLayer.imageName}</Text>
          </div>
        </div>
        <div className="row mb-3">
          <div className="col-12">
            <Label className="m-0 p-0">Creator</Label>
            <Text>{imageLayer.creator}</Text>
          </div>
        </div>
        <div className="row mb-3">
          <div className="col-12">
            <Label className="m-0 p-0">Details:</Label>
            <Text>{imageLayer.details}</Text>
          </div>
        </div>
        <div className="row mb-3">
          <div className="col-6">
            <Label className="m-0 p-0">Cloud optimized geotiff</Label>
            <div className="d-flex align-items-center">
              <Text>
                <Link href={safeHref(imageLayer.cloudOptimizedGeotiff)} target="_blank" rel="noopener noreferrer">Link</Link>
              </Text>
              <CopyToClipboard
                text={imageLayer.cloudOptimizedGeotiff}
                onCopy={handleCopy}
              >
                <IconButton
                  iconProps={{ iconName: copied ? "CheckMark" : "Copy" }}
                  title="Copy to clipboard"
                  ariaLabel="Copy to clipboard"
                />
              </CopyToClipboard>
            </div>
          </div>
          <div className="col-6">
            <Label className="m-0 p-0">Format:</Label>
            <Text>{imageLayer.format}</Text>
          </div>

        </div>
        <div className="row mb-3">
          <div className="col-6">
            <Label className="m-0 p-0">Captured Date:</Label>
            <Text>{imageLayer.capturedDate}</Text>
          </div>
          <div className="col-6">
            <Label className="m-0 p-0">Creation Date</Label>
            <Text>{imageLayer.creationDate}</Text>
          </div>
        </div>
        <div className="row mb-3">
          <div className="col-6">
            <Label className="m-0 p-0">Source:</Label>
            <Text>{imageLayer.source}</Text>
          </div>
          <div className="col-6">
            <Label className="m-0 p-0">Normalization factor</Label>
            <Text>{imageLayer.normalizationFactor}</Text>
          </div>
        </div>
        <div className="row mb-4">
          <div className="col-6">
            <Label className="m-0 p-0">Label Count</Label>
            <Text>{imageLayer.labelingCount}</Text>
          </div>
          <div className="col-6">
            <Label className="m-0 p-0">Model Count</Label>
            <Text>{imageLayer.modelTrainingCount}</Text>
          </div>
        </div>                
        <div className="row">
          <div className="col-12 d-flex justify-content-end">
            <DefaultButton onClick={onClose}>Close</DefaultButton>
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

export default ImageLayerInfoModal;
