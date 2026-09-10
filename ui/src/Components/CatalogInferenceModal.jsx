// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useEffect, useRef, useState } from "react";
import {
  Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface,
  DialogTitle, Dropdown, Field, Input, MessageBar, MessageBarBody, Option, Spinner, Text,
  makeStyles, tokens,
} from "@fluentui/react-components";
import PropTypes from "prop-types";
import { apiGet, apiPut } from "../util/api";
import { FluentIcon } from "../util/icons";
import { catalogText, readModelCatalog } from "./ModelCatalogHelper";
import {
  buildInferenceCatalogEndpoint, createCatalogInferenceSubmission,
  getCatalogInferenceReadiness, getLayerInferenceReadiness, refreshCatalogInferenceModels,
} from "./CatalogInferenceHelper";

const useStyles = makeStyles({
  surface: { width: "min(600px, calc(100vw - 32px))", maxHeight: "calc(100dvh - 32px)" },
  body: { display: "flex", flexDirection: "column", gap: tokens.spacingVerticalL },
  option: { display: "flex", flexDirection: "column", gap: tokens.spacingVerticalXS },
});

export default function CatalogInferenceModal({ projectId, imageLayer, onClose, fetchProjectDetails }) {
  const styles = useStyles();
  const [catalog, setCatalog] = useState({ status: "loading", models: [], error: "" });
  const [retryCount, setRetryCount] = useState(0);
  const [selection, setSelection] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [accepted, setAccepted] = useState(null);
  const [submission] = useState(() => createCatalogInferenceSubmission());
  const busyRef = useRef(false);
  const layerReadiness = getLayerInferenceReadiness(imageLayer);
  const selected = catalog.models.find((model) => model.baseModelName === selection);
  const canSubmit = catalog.status === "ready" && layerReadiness.ready &&
    !!selected && getCatalogInferenceReadiness(selected).ready;
  const compatibleCount = catalog.models.filter((model) => getCatalogInferenceReadiness(model).ready).length;

  useEffect(() => {
    let active = true;
    async function loadCatalog() {
      try {
        const models = readModelCatalog(await apiGet(
          buildInferenceCatalogEndpoint(projectId, imageLayer.imageLayerId)
        ));
        if (active) setCatalog({ status: "ready", models, error: "" });
      } catch (err) {
        if (active) setCatalog((previous) => ({
          ...previous, status: "error",
          error: `Unable to load the inference catalog. ${err.message || "Please try again."}`,
        }));
      }
    }
    loadCatalog();
    return () => { active = false; };
  }, [projectId, imageLayer.imageLayerId, retryCount]);

  function retryCatalog() {
    setCatalog((previous) => ({ ...previous, status: "loading", error: "" }));
    setRetryCount((value) => value + 1);
  }

  async function refreshModels() {
    // A failed refresh must never become a second queue submission.
    await refreshCatalogInferenceModels(fetchProjectDetails);
    onClose();
  }

  async function submit() {
    if (busyRef.current || (!accepted && !canSubmit)) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    let run = accepted;
    try {
      if (!run) {
        run = await submission.submit({
          projectId, imageLayerId: imageLayer.imageLayerId, baseModelName: selection, name,
        }, apiPut);
        setAccepted(run);
      }
      await refreshModels();
    } catch (err) {
      setError(run
        ? "Inference was accepted, but model rows could not be refreshed. Retry refresh; do not submit another run."
        : `${err.message || "Unable to confirm inference acceptance."} Retry with the same model and name to reuse this request. Changing either, or reopening this dialog, starts a different request.`);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  function close() {
    if (!busyRef.current) onClose();
  }

  return (
    <Dialog
      open={true}
      onOpenChange={(_, data) => { if (!data.open) close(); }}
    >
      <DialogSurface className={styles.surface}>
        <DialogBody>
          <DialogTitle action={
            <Button appearance="subtle" icon={<FluentIcon name="Cancel" />}
              aria-label="Close inference" disabled={busy} onClick={close} />
          }>
            New Catalog Inference
          </DialogTitle>
          <DialogContent className={styles.body}>
            <Text>Run a prepared catalog model on {catalogText(imageLayer.name, "this image layer")}.
              No training labels or fine-tuning are required. Each new run creates a separate model row and preserves previous results.</Text>
            {!layerReadiness.ready && <MessageBar intent="warning"><MessageBarBody>{layerReadiness.detail}</MessageBarBody></MessageBar>}
            {catalog.status === "loading" && <Spinner size="small" label="Loading inference catalog..." />}
            {catalog.status === "error" && (
              <MessageBar intent="error">
                <MessageBarBody>{catalog.error} <Button onClick={retryCatalog} disabled={busy}>Retry catalog</Button></MessageBarBody>
              </MessageBar>
            )}
            {catalog.status === "ready" && catalog.models.length === 0 && (
              <MessageBar><MessageBarBody>No inference models are in the catalog yet.</MessageBarBody></MessageBar>
            )}
            {catalog.status === "ready" && catalog.models.length > 0 && compatibleCount === 0 && (
              <MessageBar intent="warning"><MessageBarBody>No catalog models are compatible with this layer. Review the reasons below.</MessageBarBody></MessageBar>
            )}
            <Field label="Catalog model" required>
              <Dropdown placeholder="Select a compatible model" value={selection}
                selectedOptions={selection ? [selection] : []}
                disabled={catalog.status !== "ready" || busy || !!accepted}
                onOptionSelect={(_, data) => { setSelection(data.optionValue || ""); setError(""); }}>
                {catalog.models.map((model) => {
                  const readiness = getCatalogInferenceReadiness(model);
                  return (
                    <Option key={model.baseModelName} value={model.baseModelName}
                      text={model.baseModelName} disabled={!readiness.ready}>
                      <div className={styles.option}>
                        <Text weight="semibold">{model.baseModelName}</Text>
                        <Text size={200}>{catalogText(model.description, readiness.detail)}</Text>
                        {!readiness.ready && <Text size={200}>Unavailable: {readiness.detail}</Text>}
                      </div>
                    </Option>
                  );
                })}
              </Dropdown>
            </Field>
            {catalog.status === "ready" && catalog.models.filter((model) => !getCatalogInferenceReadiness(model).ready).map((model) => (
              <Text key={model.baseModelName} size={200}>
                <b>{model.baseModelName}</b> — Unavailable: {getCatalogInferenceReadiness(model).detail}
              </Text>
            ))}
            {selected && <Text size={200}>{getCatalogInferenceReadiness(selected).detail}</Text>}
            <Field label="Run name (optional)" hint="Leave blank to use the generated run name.">
              <Input value={name} disabled={busy || !!accepted}
                onChange={(_, data) => { setName(data.value); setError(""); }} />
            </Field>
            {accepted && <MessageBar intent="success"><MessageBarBody>
              Inference accepted: {catalogText(accepted.name, accepted.modelId)}. Track inference progress in the model row; acceptance does not mean processing has completed.
            </MessageBarBody></MessageBar>}
            {error && <MessageBar intent="error"><MessageBarBody>{error}</MessageBarBody></MessageBar>}
            {busy && <Spinner size="small" label={accepted ? "Refreshing model rows..." : "Submitting inference request..."} />}
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={busy || (!accepted && !canSubmit)} onClick={submit}>
              {accepted ? "Retry refresh" : error ? "Retry inference" : "Start inference"}
            </Button>
            <Button disabled={busy} onClick={close}>{accepted ? "Close" : "Cancel"}</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

CatalogInferenceModal.propTypes = {
  projectId: PropTypes.string.isRequired,
  imageLayer: PropTypes.object.isRequired,
  onClose: PropTypes.func.isRequired,
  fetchProjectDetails: PropTypes.func.isRequired,
};
