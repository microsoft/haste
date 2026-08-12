import { useEffect, useId, useRef, useState } from "react";
import {
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Dropdown,
  Field,
  Input,
  Label,
  MessageBar,
  MessageBarBody,
  Option,
  Spinner,
  Text,
  Textarea,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import PropTypes from "prop-types";
import { v4 as uuidv4 } from "uuid";

import { apiGet, apiPut } from "../util/api";
import { buildAssessmentSummary } from "../util/assessmentSummary";
import { FluentIcon } from "../util/icons";
import { selectSupportedArtifacts } from "../util/publishing";


const ARTIFACT_LABELS = {
  gpkg: "Damage GeoPackage (.gpkg)",
  valid_mask: "Valid-area mask (.geojson)",
  footprints: "Building footprints (.gpkg)",
  processed_cog: "Processed image (COG .tif)",
};

const useStyles = makeStyles({
  surface: {
    width: "min(680px, 94vw)",
    maxWidth: "94vw",
  },
  content: {
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalL,
  },
  title: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
  },
  assets: {
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalXS,
  },
  assetsField: {
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalXS,
  },
  assetsValidation: {
    color: tokens.colorStatusDangerForeground1,
  },
  assetLabel: {
    display: "flex",
    justifyContent: "space-between",
    gap: tokens.spacingHorizontalM,
    width: "100%",
  },
  size: {
    color: tokens.colorNeutralForeground3,
    whiteSpace: "nowrap",
  },
  loading: {
    minHeight: "180px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
});

function formatFileSize(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${Math.round(bytes / 1024)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

const PublishDatasetModal = ({
  projectId,
  imageLayerId,
  modelId,
  onDismiss,
  onStarted,
}) => {
  const styles = useStyles();
  const assetsLabelId = useId();
  const assetsValidationId = useId();
  const descriptionTouched = useRef(false);
  const requestId = useRef(uuidv4());
  const [loading, setLoading] = useState(true);
  const [descriptionLoading, setDescriptionLoading] = useState(true);
  const [options, setOptions] = useState(null);
  const [providers, setProviders] = useState([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [target, setTarget] = useState("");
  const [selectedArtifacts, setSelectedArtifacts] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const query =
      `projectId=${encodeURIComponent(projectId)}` +
      `&imageLayerId=${encodeURIComponent(imageLayerId)}` +
      `&modelId=${encodeURIComponent(modelId)}`;

    Promise.all([
      apiGet(`GetPublishDatasetOptions?${query}`),
      apiGet("GetPublishingProviders"),
    ])
      .then(([optionsResponse, providerResponse]) => {
        if (cancelled) return;
        const resolvedOptions = optionsResponse.publishDatasetOptions;
        const resolvedProviders = providerResponse.providers || [];
        const initialProvider =
          resolvedProviders.find(
            (provider) =>
              provider.id === "local" &&
              provider.isEnabled &&
              provider.isConfigured,
          ) ||
          resolvedProviders.find(
            (provider) => provider.isEnabled && provider.isConfigured,
          );
        setOptions(resolvedOptions);
        setProviders(resolvedProviders);
        setName(resolvedOptions.defaultName || "");
        if (initialProvider) {
          setTarget(initialProvider.id);
          setSelectedArtifacts(
            selectSupportedArtifacts(resolvedOptions, initialProvider),
          );
        }
      })
      .catch((loadError) => {
        if (!cancelled) setError(loadError.message || "Unable to load publishing options.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    apiGet(`GetAssessmentReport?${query}`)
      .then((report) => {
        if (cancelled || descriptionTouched.current) return;
        setDescription(buildAssessmentSummary(report));
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setDescriptionLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectId, imageLayerId, modelId]);

  const selectedProvider = providers.find(
    (provider) => provider.id === target,
  );
  const availableArtifacts = options?.availableArtifacts || [];
  const supportedKinds = new Set(
    selectedProvider?.supportedArtifactKinds || [],
  );
  const effectiveSelectedArtifacts = selectedArtifacts.filter((kind) =>
    supportedKinds.has(kind),
  );
  const canSubmit =
    !loading &&
    !submitting &&
    !!name.trim() &&
    !!selectedProvider?.isEnabled &&
    !!selectedProvider?.isConfigured &&
    effectiveSelectedArtifacts.length > 0;

  function handleTargetChange(_, data) {
    const providerId = data.optionValue || data.selectedOptions?.[0];
    const provider = providers.find((item) => item.id === providerId);
    if (!provider || !provider.isEnabled || !provider.isConfigured) return;
    setTarget(provider.id);
    setSelectedArtifacts(selectSupportedArtifacts(options, provider));
    setError("");
  }

  function handleArtifactChange(kind, checked) {
    setSelectedArtifacts((current) =>
      checked
        ? [...new Set([...current, kind])]
        : current.filter((value) => value !== kind),
    );
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError("");
    try {
      const response = await apiPut("PutPublishDatasetQueueMessage", {
        requestId: requestId.current,
        projectId,
        imageLayerId,
        modelId,
        name: name.trim(),
        description: description.trim(),
        target,
        artifacts: effectiveSelectedArtifacts,
      });
      // apiPut returns the numeric status (409) on conflict instead of throwing;
      // surface it as an error rather than reporting a false success.
      if (response === 409) {
        setError(
          "A dataset with this name is already being published for this project and layer."
        );
        return;
      }
      onStarted?.(response.publishedDataset);
      onDismiss();
    } catch (submitError) {
      setError(submitError.message || "Unable to start publishing.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open onOpenChange={(_, data) => !data.open && onDismiss()}>
      <DialogSurface
        className={styles.surface}
        aria-describedby={undefined}
      >
        <form onSubmit={handleSubmit}>
          <DialogBody>
            <DialogTitle
              action={
                <Button
                  appearance="subtle"
                  aria-label="Close"
                  icon={<FluentIcon name="Cancel" />}
                  onClick={onDismiss}
                />
              }
            >
              <span className={styles.title}>
                <FluentIcon name="Upload" />
                Publish dataset
              </span>
            </DialogTitle>
            <DialogContent className={styles.content}>
              {loading ? (
                <div className={styles.loading}>
                  <Spinner label="Loading publishing options" />
                </div>
              ) : (
                <>
                  {error && (
                    <MessageBar intent="error">
                      <MessageBarBody>{error}</MessageBarBody>
                    </MessageBar>
                  )}
                  <Field label="Dataset name" required>
                    <Input
                      value={name}
                      onChange={(_, data) => setName(data.value)}
                      disabled={submitting}
                    />
                  </Field>
                  <Field
                    label="Description"
                    hint={descriptionLoading ? "Loading assessment summary…" : undefined}
                  >
                    <Textarea
                      value={description}
                      resize="vertical"
                      onChange={(_, data) => {
                        descriptionTouched.current = true;
                        setDescription(data.value);
                      }}
                      disabled={submitting}
                    />
                  </Field>
                  <div className={styles.assetsField}>
                    <Label id={assetsLabelId} required>
                      Assets to publish
                    </Label>
                    <div
                      className={styles.assets}
                      role="group"
                      aria-labelledby={assetsLabelId}
                      aria-describedby={
                        effectiveSelectedArtifacts.length === 0
                          ? assetsValidationId
                          : undefined
                      }
                      aria-invalid={effectiveSelectedArtifacts.length === 0}
                    >
                      {availableArtifacts.map((artifact) => {
                        const supported = supportedKinds.has(artifact.kind);
                        return (
                          <Checkbox
                            key={artifact.kind}
                            checked={
                              supported &&
                              effectiveSelectedArtifacts.includes(artifact.kind)
                            }
                            disabled={!supported || submitting}
                            onChange={(_, data) =>
                              handleArtifactChange(artifact.kind, !!data.checked)
                            }
                            label={
                              <span className={styles.assetLabel}>
                                <span>
                                  {ARTIFACT_LABELS[artifact.kind] || artifact.kind}
                                  {!supported ? " — unavailable for this target" : ""}
                                </span>
                                <Text className={styles.size} size={200}>
                                  {formatFileSize(artifact.sizeBytes)}
                                </Text>
                              </span>
                            }
                          />
                        );
                      })}
                    </div>
                    {effectiveSelectedArtifacts.length === 0 && (
                      <Text
                        id={assetsValidationId}
                        className={styles.assetsValidation}
                        role="alert"
                        size={200}
                      >
                        Select at least one asset to publish
                      </Text>
                    )}
                  </div>
                  <Field label="Target publishing location" required>
                    <Dropdown
                      inlinePopup
                      value={selectedProvider?.displayName || ""}
                      selectedOptions={target ? [target] : []}
                      onOptionSelect={handleTargetChange}
                      disabled={submitting}
                    >
                      {providers.map((provider) => (
                        <Option
                          key={provider.id}
                          value={provider.id}
                          text={provider.displayName}
                          disabled={!provider.isEnabled || !provider.isConfigured}
                        >
                          {provider.displayName}
                          {provider.disabledReason
                            ? ` — ${provider.disabledReason}`
                            : ""}
                        </Option>
                      ))}
                    </Dropdown>
                  </Field>
                </>
              )}
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={onDismiss} disabled={submitting}>
                Cancel
              </Button>
              <Button appearance="primary" type="submit" disabled={!canSubmit}>
                {submitting ? <Spinner size="tiny" /> : "Publish"}
              </Button>
            </DialogActions>
          </DialogBody>
        </form>
      </DialogSurface>
    </Dialog>
  );
};

PublishDatasetModal.propTypes = {
  projectId: PropTypes.string.isRequired,
  imageLayerId: PropTypes.string.isRequired,
  modelId: PropTypes.string.isRequired,
  onDismiss: PropTypes.func.isRequired,
  onStarted: PropTypes.func,
};

export default PublishDatasetModal;