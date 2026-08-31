// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Asks which predictions to download when a model has more than one set.
//
// The model rows used to download the raw GeoPackage unconditionally, so an
// analyst who had spent an afternoon correcting predictions still got the
// model's uncorrected output, with a filename that gave no hint which one it
// was. When saved versions exist the caller opens this dialog instead; when
// they don't, it never appears and the download happens straight away.
import { useState } from "react";
import PropTypes from "prop-types";
import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Text,
  tokens,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
import PredictionVersionPicker from "./PredictionVersionPicker";
import { defaultPredictionVersion } from "../Visualizer/predictionVersions";

const DownloadPredictionsDialog = ({
  versions,
  modelName,
  onDownload,
  onDismiss,
}) => {
  const [version, setVersion] = useState(() =>
    defaultPredictionVersion(versions)
  );

  return (
    <Dialog
      open={true}
      onOpenChange={(_event, data) => {
        if (!data.open) onDismiss();
      }}
    >
      <DialogSurface style={{ width: "min(460px, 94vw)" }}>
        <DialogBody>
          <DialogTitle>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <FluentIcon
                name="download"
                style={{ fontSize: 20, color: tokens.colorBrandForeground1 }}
              />
              <span>Download predictions</span>
            </div>
          </DialogTitle>
          <DialogContent>
            <Text
              style={{
                display: "block",
                marginBottom: 12,
                color: tokens.colorNeutralForeground2,
              }}
            >
              {modelName
                ? `${modelName} has saved edits. Choose which predictions to download.`
                : "This model has saved edits. Choose which predictions to download."}
            </Text>
            <PredictionVersionPicker
              versions={versions}
              value={version}
              onChange={setVersion}
            />
          </DialogContent>
          <DialogActions>
            <Button appearance="secondary" onClick={onDismiss}>
              Cancel
            </Button>
            <Button
              appearance="primary"
              onClick={() => {
                onDownload(version);
                onDismiss();
              }}
            >
              Download
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
};

DownloadPredictionsDialog.propTypes = {
  versions: PropTypes.array,
  modelName: PropTypes.string,
  onDownload: PropTypes.func.isRequired,
  onDismiss: PropTypes.func.isRequired,
};

export default DownloadPredictionsDialog;
