// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// PR136's version-choice dialog, with fresh history and visible download errors.
import { useEffect, useRef, useState } from "react";
import PropTypes from "prop-types";
import {
  Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle,
  MessageBar, MessageBarBody, Spinner, Text, makeStyles,
} from "@fluentui/react-components";
import { buildUrl } from "../../util/api";
import PredictionVersionPicker from "./PredictionVersionPicker";
import { buildVersionGpkgUrl, versionLabel } from "../Visualizer/predictionVersions.js";
import { downloadPrediction } from "../Visualizer/predictionDownload.js";
import usePredictionVersionManifest from "../Visualizer/usePredictionVersionManifest";
import useVisualizerResults from "../Visualizer/useVisualizerResults";

const useStyles = makeStyles({ surface: { width: "min(460px, 94vw)" } });
export default function DownloadPredictionsDialog({ projectId, imageLayerId, modelId, modelName, currentRevision, onDismiss }) {
  const styles = useStyles();
  const ids = { projectId, imageLayerId, modelId };
  const routeKey = JSON.stringify(ids);
  const manifest = usePredictionVersionManifest(ids);
  // The model row may predate a re-predict. Resolve the canonical default from
  // a fresh read, not the highest historical version or a stale row revision.
  // This hook reads metadata only; opening this dialog downloads no sidecars.
  const defaults = useVisualizerResults(ids);
  const versions = manifest.data?.versions || [];
  const revision = defaults.results?.currentPredictionRevision ?? defaults.results?.predictionRevision ??
    manifest.data?.currentPredictionRevision ?? currentRevision;
  const [choice, setChoice] = useState(null);
  const selection = choice?.routeKey === routeKey ? choice.version : null;
  const version = selection ?? defaults.results?.predictionVersion ?? 0;
  const [operation, setOperation] = useState(null);
  const downloading = operation?.routeKey === routeKey && operation.loading;
  const error = operation?.routeKey === routeKey ? operation.error : "";
  const controllerRef = useRef(null);
  useEffect(() => () => { controllerRef.current?.abort(); }, [routeKey]);
  const defaultsLoading = !defaults.results && !defaults.error;
  const dismiss = () => { controllerRef.current?.abort(); onDismiss(); };
  const download = async () => {
    const controller = new AbortController();
    controllerRef.current = controller;
    setOperation({ routeKey, loading: true });
    try {
      await downloadPrediction(buildUrl(buildVersionGpkgUrl({
        ...ids, version, predictionRevision: version === 0 ? defaults.results?.predictionRevision : versions.find((entry) => entry.version === version)?.predictionRevision,
      })), version, { signal: controller.signal });
      if (!controller.signal.aborted) { setOperation(null); onDismiss(); }
    } catch (cause) {
      if (!controller.signal.aborted) setOperation({ routeKey, error: cause.message });
    }
  };
  return (
    <Dialog open onOpenChange={(_event, data) => { if (!data.open) dismiss(); }}>
      <DialogSurface className={styles.surface}><DialogBody>
        <DialogTitle>Download predictions</DialogTitle>
        <DialogContent>
          <Text block>{modelName ? `${modelName}: ` : ""}Choose which predictions to download.</Text>
          {manifest.loading ? <Spinner size="tiny" label="Loading prediction versions" /> : (
            <PredictionVersionPicker versions={versions} value={version}
              onChange={(value) => setChoice({ routeKey, version: value })} currentRevision={revision} disabled={downloading} />
          )}
          {!manifest.loading && versions.length === 0 && <Text>{versionLabel(version)}</Text>}
          {(error || manifest.error) && <MessageBar intent="error"><MessageBarBody>{error || manifest.error}</MessageBarBody></MessageBar>}
          {defaults.error && <MessageBar intent="warning"><MessageBarBody>
            Could not resolve the default prediction source. Select a version explicitly, or retry. {defaults.error}
            <Button onClick={defaults.retry}>Retry default</Button>
          </MessageBarBody></MessageBar>}
        </DialogContent>
        <DialogActions>
          {manifest.error && <Button onClick={manifest.retry}>Retry versions</Button>}
          <Button onClick={dismiss}>Cancel</Button>
          <Button appearance="primary" disabled={downloading || manifest.loading || defaultsLoading || !!manifest.error || (!!defaults.error && selection === null)} onClick={download}>
            {downloading ? "Downloading…" : "Download"}
          </Button>
        </DialogActions>
      </DialogBody></DialogSurface>
    </Dialog>
  );
}
DownloadPredictionsDialog.propTypes = {
  projectId: PropTypes.string.isRequired, imageLayerId: PropTypes.string.isRequired, modelId: PropTypes.string.isRequired,
  modelName: PropTypes.string, currentRevision: PropTypes.string, onDismiss: PropTypes.func.isRequired,
};
