// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useCallback, useEffect, useState } from "react";
import PropTypes from "prop-types";
import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  MessageBar,
  MessageBarBody,
  SpinButton,
  Spinner,
  Text,
  tokens,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
import { apiGet, apiPut } from "../../util/api";
import {
  MAX_VALIDATION_SAMPLE,
  MIN_VALIDATION_SAMPLE,
  OUTCOME_NOOP,
  canApplySampleSize,
  resolveSampleSize,
} from "./validationConfig";

/**
 * Settings for one image layer's Building Validation workflow.
 *
 * Currently holds the sample size and the clear-labels action; laid out as a
 * list of settings so more can be added without restructuring.
 */
const ValidationConfigModal = ({
  projectId,
  imageLayerId,
  onClose,
  onSaved,
  onCleared,
}) => {
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmingClear, setConfirmingClear] = useState(false);

  const [storedSize, setStoredSize] = useState(null);
  const [labelCount, setLabelCount] = useState(0);
  const [value, setValue] = useState("");

  // Always read current state on open: the count may have been changed from
  // the other entry point, or labels added, since this page was rendered.
  const refresh = useCallback(async () => {
    const validation = await apiGet(
      `GetBuildingValidation?projectId=${projectId}` +
        `&imageLayerId=${imageLayerId}`
    );
    const size = resolveSampleSize(validation);
    setStoredSize(size);
    setLabelCount(Object.keys(validation?.labels || {}).length);
    return size;
  }, [projectId, imageLayerId]);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const size = await refresh();
        if (!cancelled) setValue(String(size));
      } catch (e) {
        if (cancelled) return;
        console.error("Failed to load validation settings:", e);
        setError(
          "Could not read this layer's validation settings. Close and try" +
            " again."
        );
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  const parsed = /^\d+$/.test(String(value).trim())
    ? Number(String(value).trim())
    : NaN;
  const check = canApplySampleSize(storedSize, parsed, labelCount);

  async function handleSave() {
    if (!check.allowed) return;
    if (check.outcome === OUTCOME_NOOP) {
      onClose();
      return;
    }

    setBusy(true);
    setError("");
    try {
      const result = await apiPut("PutBuildingValidationConfig", {
        projectId,
        imageLayerId,
        sampleSize: parsed,
      });

      // apiPut returns 409 rather than throwing, so a refusal arrives as a
      // value. It only fires in a race — the button is already disabled when
      // this client can see the conflict — so re-read the layer and let the
      // refreshed state explain itself.
      if (result === 409) {
        await refresh();
        setError(
          "This layer's validation labels changed while the settings were" +
            " open, and the new count would drop labeled buildings. Clear" +
            " the labels first, or choose a higher count."
        );
        return;
      }

      onSaved?.(parsed);
      onClose();
    } catch (e) {
      console.error("Failed to save validation settings:", e);
      // The server owns these rules, so surface what it said rather than
      // guessing — the client's own check can be stale if someone else has
      // been labeling this layer.
      setError(
        e?.message ||
          "Could not save the validation settings. Please try again."
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleClear() {
    setBusy(true);
    setError("");
    try {
      // A label save with an empty set. The server preserves sampleSize on
      // this route, so clearing does not reset the count.
      await apiPut("PutBuildingValidation", {
        projectId,
        imageLayerId,
        labels: {},
      });
      setLabelCount(0);
      setConfirmingClear(false);
      setNotice("Validation labels cleared.");
      onCleared?.();
    } catch (e) {
      console.error("Failed to clear validation labels:", e);
      setError("Could not clear the validation labels. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={true}
      modalType="modal"
      onOpenChange={(_event, data) => {
        if (!data.open && !busy) onClose();
      }}
    >
      <DialogSurface style={{ width: "min(520px, 94vw)", maxWidth: "94vw" }}>
        <DialogBody>
          <DialogTitle>Building Validation settings</DialogTitle>
          <DialogContent>
            {loading ? (
              <Spinner label="Loading settings…" />
            ) : (
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: tokens.spacingVerticalL,
                }}
              >
                <Field
                  label="Buildings to validate"
                  hint={
                    `How many building footprints this layer asks you to ` +
                    `label. ${MIN_VALIDATION_SAMPLE}–${MAX_VALIDATION_SAMPLE}.`
                  }
                  validationState={
                    check.allowed || !String(value).trim() ? "none" : "error"
                  }
                  validationMessage={check.allowed ? undefined : check.message}
                >
                  <SpinButton
                    id="validationSampleSize"
                    value={parsed}
                    displayValue={String(value)}
                    min={MIN_VALIDATION_SAMPLE}
                    max={MAX_VALIDATION_SAMPLE}
                    step={50}
                    disabled={busy}
                    onChange={(_e, data) => {
                      if (data.value != null) {
                        setValue(String(data.value));
                      } else if (data.displayValue != null) {
                        setValue(data.displayValue);
                      }
                    }}
                  />
                </Field>

                <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
                  {labelCount > 0
                    ? `${labelCount} building${labelCount === 1 ? "" : "s"}` +
                      " labeled so far. Raising the count keeps them and adds" +
                      " more."
                    : "No buildings labeled yet."}
                </Text>

                {notice && (
                  <MessageBar intent="success">
                    <MessageBarBody>{notice}</MessageBarBody>
                  </MessageBar>
                )}
                {error && (
                  <MessageBar intent="error">
                    <MessageBarBody>{error}</MessageBarBody>
                  </MessageBar>
                )}

                <div
                  style={{
                    borderTop: `1px solid ${tokens.colorNeutralStroke2}`,
                    paddingTop: tokens.spacingVerticalM,
                  }}
                >
                  {confirmingClear ? (
                    <MessageBar intent="warning">
                      <MessageBarBody>
                        <div style={{ marginBottom: 8 }}>
                          Delete all {labelCount} validation label
                          {labelCount === 1 ? "" : "s"} for this layer? This
                          cannot be undone.
                        </div>
                        <div style={{ display: "flex", gap: 8 }}>
                          <Button
                            size="small"
                            appearance="primary"
                            disabled={busy}
                            onClick={handleClear}
                          >
                            Yes, clear them
                          </Button>
                          <Button
                            size="small"
                            disabled={busy}
                            onClick={() => setConfirmingClear(false)}
                          >
                            Cancel
                          </Button>
                        </div>
                      </MessageBarBody>
                    </MessageBar>
                  ) : (
                    <Button
                      id="clearValidationLabels"
                      icon={<FluentIcon name="Delete" />}
                      disabled={busy || labelCount === 0}
                      onClick={() => {
                        setNotice("");
                        setConfirmingClear(true);
                      }}
                    >
                      Clear all validation labels
                    </Button>
                  )}
                </div>
              </div>
            )}
          </DialogContent>
          <DialogActions>
            <Button
              appearance="primary"
              id="saveValidationConfig"
              disabled={loading || busy || !check.allowed}
              onClick={handleSave}
            >
              {busy ? "Saving…" : "Save"}
            </Button>
            <Button disabled={busy} onClick={onClose}>
              Close
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
};

ValidationConfigModal.propTypes = {
  projectId: PropTypes.string.isRequired,
  imageLayerId: PropTypes.string.isRequired,
  onClose: PropTypes.func.isRequired,
  onSaved: PropTypes.func,
  onCleared: PropTypes.func,
};

export default ValidationConfigModal;
