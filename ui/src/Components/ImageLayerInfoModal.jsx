// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useState } from "react";
import {
  Dialog,
  DialogSurface,
  Button,
  Link,
  Text,
  Label,
  tokens,
} from "@fluentui/react-components";
import { FluentIcon } from "../util/icons";
import { safeHref } from "../util/validation";

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
            <FluentIcon name="FileImage" className="me-2 modal-icon" />
            <p style={headingStyle}>
              Image Layer Information

            </p>
          </div>
          <Button
            appearance="subtle"
            icon={<FluentIcon name="Cancel" />}
            aria-label="Close popup modal"
            onClick={onClose}
          />
        </div>
        <div style={bodyStyle} className="modal-form-body">
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
                <Button
                  appearance="subtle"
                  icon={<FluentIcon name={copied ? "CheckMark" : "Copy"} />}
                  title="Copy to clipboard"
                  aria-label="Copy to clipboard"
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
            <Button onClick={onClose}>Close</Button>
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

export default ImageLayerInfoModal;
