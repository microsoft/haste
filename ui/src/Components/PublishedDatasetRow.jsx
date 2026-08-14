import {
  Badge,
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Divider,
  Field,
  Input,
  Link,
  Menu,
  MenuItem,
  MenuList,
  MenuPopover,
  MenuTrigger,
  MessageBar,
  MessageBarBody,
  Text,
  Textarea,
  Tooltip,
} from "@fluentui/react-components";
import PropTypes from "prop-types";
import { useContext, useState } from "react";
import { useNavigate } from "react-router-dom";

import { AppContext } from "../AppContext";
import { apiDelete, apiGet, apiPut } from "../util/api";
import { toBrowserStorageUrl } from "../util/blobUrl";
import { limitTextLength } from "../util/conversion";
import { fileDownload } from "../util/file";
import { FluentIcon } from "../util/icons";
import { getPublishingStatusDisplay } from "../util/publishing";

const PublishedDatasetRow = ({ item, index, onRefresh }) => {
  const { appParams, setDialog, setIsLoading } = useContext(AppContext);
  const navigate = useNavigate();
  const [showDetails, setShowDetails] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editViewer, setEditViewer] = useState("");
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState("");
  const preds = item.assessmentSummary?.predictions;
  const status = getPublishingStatusDisplay(item.status);

  // Navigate to the source project, expanding the layer that produced this
  // dataset. Route "/project/:projectId/:imageLayerId" opens the project view
  // with that layer expanded (falls back to the project when no layer id).
  const sourceHref = item.projectId
    ? item.imageLayerId
      ? `/project/${item.projectId}/${item.imageLayerId}`
      : `/project/${item.projectId}`
    : null;
  const openSource = (e) => {
    if (!sourceHref) return;
    e.preventDefault();
    navigate(sourceHref);
  };
  const isAdmin = appParams.userRoles?.includes("administrators");
  const isOwner =
    String(item.publishedByUser).toLowerCase() ===
    String(appParams.identityId || appParams.userId).toLowerCase();
  const canManage = isAdmin || isOwner;

  // Prefer a human-readable publisher: the name captured at publish time, else
  // the current user's own name for their datasets, else a shortened id so the
  // column doesn't show a long opaque identifier.
  // Show the publisher the same way the project/layer views show the creator:
  // the user's login/email captured at publish time (publishedByName), falling
  // back to the current user's login for their own datasets.
  const publishedBy =
    item.publishedByName ||
    (isOwner ? appParams.userId || appParams.userDetails : "") ||
    item.publishedByUser ||
    null;

  async function handleDownload(kind) {
    setIsLoading(true, "Preparing download...");
    try {
      const detail = await apiGet(
        `GetPublishedDataset?projectId=${encodeURIComponent(item.projectId)}` +
          `&datasetId=${encodeURIComponent(item.datasetId)}`,
      );
      const url = detail.downloadUrls?.[kind];
      fileDownload(toBrowserStorageUrl(url) || url, setDialog);
    } catch (error) {
      setDialog("Download failed", error.message);
    } finally {
      setIsLoading(false);
    }
  }

  function openMetadata(edit) {
    setEditName(item.name || "");
    setEditDescription(item.description || "");
    setEditViewer(item.interactiveViewerUrl || "");
    setEditError("");
    setEditing(!!edit);
    setShowDetails(true);
  }

  async function saveMetadata() {
    setSaving(true);
    setEditError("");
    try {
      await apiPut("PutUpdatePublishedDataset", {
        projectId: item.projectId,
        datasetId: item.datasetId,
        name: editName.trim(),
        description: editDescription.trim(),
        interactiveViewerUrl: editViewer.trim() || null,
      });
      setEditing(false);
      setShowDetails(false);
      await onRefresh();
    } catch (error) {
      setEditError(error.message || "Unable to save changes.");
    } finally {
      setSaving(false);
    }
  }

  async function handleRetry() {
    setIsLoading(true, "Retrying publishing operation...");
    try {
      await apiPut("PutRetryPublishedDatasetQueueMessage", {
        projectId: item.projectId,
        datasetId: item.datasetId,
      });
      await onRefresh();
    } catch (error) {
      setDialog("Retry failed", error.message);
    } finally {
      setIsLoading(false);
    }
  }

  async function handleUnpublish() {
    setDialog();
    setIsLoading(true, "Starting dataset cleanup...");
    try {
      await apiDelete(
        `DeletePublishedDataset?projectId=${encodeURIComponent(item.projectId)}` +
          `&datasetId=${encodeURIComponent(item.datasetId)}`,
      );
      await onRefresh();
    } catch (error) {
      setDialog("Unpublish failed", error.message);
    } finally {
      setIsLoading(false);
    }
  }

  function confirmUnpublish() {
    setDialog(
      "Unpublish dataset",
      `Remove “${item.name}” and its published copies?`,
      [
        {
          type: "primary",
          key: "unpublish",
          text: "Unpublish",
          onClick: handleUnpublish,
        },
        {
          type: "default",
          key: "cancel",
          text: "Cancel",
          onClick: () => setDialog(),
        },
      ],
    );
  }

  const menuItems = [];
  menuItems.push({
    key: "details",
    text: "View details",
    icon: "Info",
    onClick: () => openMetadata(false),
  });
  if (canManage) {
    menuItems.push({
      key: "edit",
      text: "Edit metadata",
      icon: "Edit",
      onClick: () => openMetadata(true),
    });
  }
  if (item.status === "PUBLISHED" && item.target === "local") {
    for (const artifact of item.artifacts || []) {
      menuItems.push({
        key: `download-${artifact.kind}`,
        text: `Download ${artifactLabel(artifact.kind)}`,
        icon: "Download",
        onClick: () => handleDownload(artifact.kind),
      });
    }
  }
  if (item.status === "PUBLISHED" && item.target === "planetary_computer") {
    if (item.links?.explorer) {
      menuItems.push({
        key: "explorer",
        text: "Open in Explorer",
        icon: "Globe",
        onClick: () => window.open(item.links.explorer, "_blank", "noopener,noreferrer"),
      });
    }
    if (item.links?.stac_collection) {
      menuItems.push({
        key: "copy-stac",
        text: "Copy STAC collection link",
        icon: "Copy",
        onClick: () => navigator.clipboard.writeText(item.links.stac_collection),
      });
    }
  }
  if (canManage && ["FAILED", "UNPUBLISH_FAILED"].includes(item.status)) {
    menuItems.push({
      key: "retry",
      text: "Retry",
      icon: "Redo",
      onClick: handleRetry,
    });
  }
  if (
    canManage &&
    ["PUBLISHED", "FAILED", "UNPUBLISH_FAILED"].includes(item.status)
  ) {
    menuItems.push({
      key: "unpublish",
      text: "Unpublish",
      icon: "Delete",
      onClick: confirmUnpublish,
    });
  }

  return (
    <tr>
      <td data-label="Name">
        <Tooltip content={item.name} relationship="label">
          <Text
            id={`publishedDatasetName${index}`}
            className="published-dataset-value"
          >
            {item.name}
          </Text>
        </Tooltip>
      </td>
      <td data-label="Project / Layer">
        {sourceHref ? (
          <Tooltip
            content="Open the source project and layer"
            relationship="label"
          >
            <Link
              className="published-dataset-value"
              href={sourceHref}
              onClick={openSource}
            >
              {item.projectName || item.projectId}
            </Link>
          </Tooltip>
        ) : (
          <Text>{item.projectName || item.projectId}</Text>
        )}
        <div className="pgrid-muted published-dataset-value">
          {sourceHref ? (
            <Link
              className="published-dataset-value"
              href={sourceHref}
              onClick={openSource}
              appearance="subtle"
            >
              {item.imageLayerName || item.imageLayerId}
            </Link>
          ) : (
            item.imageLayerName || item.imageLayerId
          )}
        </div>
      </td>
      <td data-label="Target">
        <span className="published-dataset-value">
          {item.target === "local" ? "Local" : "Planetary Computer"}
        </span>
      </td>
      <td data-label="Status">
        <Tooltip content={item.statusMessage || status.label} relationship="description">
          <Badge appearance="tint" color={status.color}>
            {status.label}
          </Badge>
        </Tooltip>
      </td>
      <td data-label="Published by">
        <Tooltip content={publishedBy || ""} relationship="label">
          <Text className="published-dataset-value">
            {publishedBy ? limitTextLength(publishedBy, false, 30) : "User"}
          </Text>
        </Tooltip>
      </td>
      <td data-label="Published date">
        <span className="published-dataset-value">
          {formatDate(item.publishedDate || item.createdDate)}
        </span>
      </td>
      <td className="pgrid-td-numeric" data-label="Actions">
        <Menu positioning="below-end">
          <MenuTrigger disableButtonEnhancement>
            <Button
              appearance="subtle"
              className="no-dropdown-icon"
              icon={<FluentIcon name="More" />}
              title="Menu"
              aria-label={`Menu for ${item.name}`}
              disabled={menuItems.length === 0}
            />
          </MenuTrigger>
          <MenuPopover>
            <MenuList>
              {menuItems.map((menuItem) => (
                <MenuItem
                  key={menuItem.key}
                  icon={<FluentIcon name={menuItem.icon} />}
                  onClick={menuItem.onClick}
                >
                  {menuItem.text}
                </MenuItem>
              ))}
            </MenuList>
          </MenuPopover>
        </Menu>
        {showDetails && (
          <Dialog
            open
            onOpenChange={(_, data) => {
              if (!data.open) {
                setShowDetails(false);
                setEditing(false);
              }
            }}
          >
            <DialogSurface aria-describedby={undefined}>
              <DialogBody>
                <DialogTitle>
                  {editing ? "Edit metadata" : item.name}
                </DialogTitle>
                <DialogContent>
                  {editing ? (
                    <div
                      style={{
                        display: "flex",
                        flexDirection: "column",
                        gap: 12,
                        margin: "4px 0 12px",
                      }}
                    >
                      {editError && (
                        <MessageBar intent="error">
                          <MessageBarBody>{editError}</MessageBarBody>
                        </MessageBar>
                      )}
                      <Field label="Dataset name" required>
                        <Input
                          value={editName}
                          onChange={(_, d) => setEditName(d.value)}
                          disabled={saving}
                        />
                      </Field>
                      <Field label="Description">
                        <Textarea
                          value={editDescription}
                          resize="vertical"
                          onChange={(_, d) => setEditDescription(d.value)}
                          disabled={saving}
                        />
                      </Field>
                      <Field
                        label="Interactive viewer URL"
                        hint="Optional https link shown as a preview."
                      >
                        <Input
                          type="url"
                          placeholder="https://…"
                          value={editViewer}
                          onChange={(_, d) => setEditViewer(d.value)}
                          disabled={saving}
                        />
                      </Field>
                    </div>
                  ) : (
                    <>
                      {item.description && (
                        <p
                          style={{
                            marginTop: 0,
                            whiteSpace: "pre-wrap",
                            lineHeight: 1.4,
                          }}
                        >
                          {item.description}
                        </p>
                      )}
                      {item.interactiveViewerUrl && (
                        <p style={{ marginTop: 0 }}>
                          <Link
                            href={item.interactiveViewerUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            Open interactive viewer
                          </Link>
                        </p>
                      )}
                    </>
                  )}
                  <Divider />
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "auto 1fr",
                      rowGap: 6,
                      columnGap: 16,
                      alignItems: "baseline",
                      margin: "12px 0",
                    }}
                  >
                    <Text weight="semibold">Project / Layer</Text>
                    <div>
                      {sourceHref ? (
                        <Link href={sourceHref} onClick={openSource}>
                          {item.projectName} — {item.imageLayerName}
                        </Link>
                      ) : (
                        `${item.projectName || item.projectId} — ${
                          item.imageLayerName || item.imageLayerId
                        }`
                      )}
                    </div>
                    <Text weight="semibold">Model</Text>
                    <div>{item.modelName || item.modelId || "—"}</div>
                    <Text weight="semibold">Target</Text>
                    <div>
                      {item.target === "local"
                        ? "Local (In App storage)"
                        : "Planetary Computer"}
                    </div>
                    <Text weight="semibold">Status</Text>
                    <div>
                      {status.label}
                      {item.statusMessage ? ` — ${item.statusMessage}` : ""}
                    </div>
                    <Text weight="semibold">Published by</Text>
                    <div>{publishedBy || "—"}</div>
                    <Text weight="semibold">Published</Text>
                    <div>{formatDate(item.publishedDate || item.createdDate)}</div>
                  </div>
                  {preds && (
                    <>
                      <Divider />
                      <div style={{ margin: "12px 0" }}>
                        <Text weight="semibold">Assessment</Text>
                        <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                          <li>{int(preds.total)} buildings assessed</li>
                          {preds.cloudy > 0 && (
                            <li>{int(preds.cloudy)} obscured by clouds</li>
                          )}
                          <li>
                            {int(preds.predictedDamaged)} predicted damaged
                            {preds.predictedDamagedPctOfKnown != null &&
                              ` (${preds.predictedDamagedPctOfKnown}% of assessed)`}
                          </li>
                        </ul>
                      </div>
                    </>
                  )}
                  {(item.artifacts || []).length > 0 && (
                    <>
                      <Divider />
                      <div style={{ margin: "12px 0 0" }}>
                        <Text weight="semibold">Published assets</Text>
                        <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                          {item.artifacts.map((a) => (
                            <li key={a.kind}>
                              {artifactLabel(a.kind)}
                              {a.sizeBytes ? ` — ${formatBytes(a.sizeBytes)}` : ""}
                            </li>
                          ))}
                        </ul>
                      </div>
                    </>
                  )}
                </DialogContent>
                <DialogActions>
                  {editing ? (
                    <>
                      <Button
                        appearance="secondary"
                        onClick={() => setEditing(false)}
                        disabled={saving}
                      >
                        Cancel
                      </Button>
                      <Button
                        appearance="primary"
                        onClick={saveMetadata}
                        disabled={saving || !editName.trim()}
                      >
                        {saving ? "Saving…" : "Save"}
                      </Button>
                    </>
                  ) : (
                    <>
                      {canManage && (
                        <Button
                          appearance="secondary"
                          onClick={() => openMetadata(true)}
                        >
                          Edit
                        </Button>
                      )}
                      <Button
                        appearance="secondary"
                        onClick={() => setShowDetails(false)}
                      >
                        Close
                      </Button>
                    </>
                  )}
                </DialogActions>
              </DialogBody>
            </DialogSurface>
          </Dialog>
        )}
      </td>
    </tr>
  );
};

PublishedDatasetRow.propTypes = {
  item: PropTypes.object.isRequired,
  index: PropTypes.number.isRequired,
  onRefresh: PropTypes.func.isRequired,
};

function int(value) {
  return value == null ? "—" : Math.round(value).toLocaleString();
}

function formatBytes(bytes) {
  if (!bytes || bytes < 0) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let n = bytes;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${n.toFixed(n < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function artifactLabel(kind) {
  return {
    gpkg: "damage GeoPackage",
    valid_mask: "valid-area mask",
    footprints: "building footprints",
    processed_cog: "processed image",
  }[kind] || kind;
}

export default PublishedDatasetRow;