import {
  Badge,
  Button,
  Menu,
  MenuItem,
  MenuList,
  MenuPopover,
  MenuTrigger,
  Text,
  Tooltip,
} from "@fluentui/react-components";
import PropTypes from "prop-types";
import { useContext } from "react";

import { AppContext } from "../AppContext";
import { apiDelete, apiGet, apiPut } from "../util/api";
import { toBrowserStorageUrl } from "../util/blobUrl";
import { fileDownload } from "../util/file";
import { FluentIcon } from "../util/icons";
import {
  getPublishingStatusDisplay,
  isPublishingStatusActive,
} from "../util/publishing";

const PublishedDatasetRow = ({ item, index, onRefresh }) => {
  const { appParams, setDialog, setIsLoading } = useContext(AppContext);
  const status = getPublishingStatusDisplay(item.status);
  const isAdmin = appParams.userRoles?.includes("administrators");
  const isOwner =
    String(item.publishedByUser).toLowerCase() ===
    String(appParams.identityId || appParams.userId).toLowerCase();
  const canManage = isAdmin || isOwner;

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
          <Text id={`publishedDatasetName${index}`}>{item.name}</Text>
        </Tooltip>
      </td>
      <td data-label="Project / Layer">
        <Text>{item.projectName || item.projectId}</Text>
        <div className="pgrid-muted">{item.imageLayerName || item.imageLayerId}</div>
      </td>
      <td data-label="Target">
        {item.target === "local" ? "Local" : "Planetary Computer"}
      </td>
      <td data-label="Status">
        <Tooltip content={item.statusMessage || status.label} relationship="description">
          <Badge appearance="tint" color={status.color}>
            {status.label}
          </Badge>
        </Tooltip>
      </td>
      <td data-label="Published by">{item.publishedByUser}</td>
      <td data-label="Published date">
        {formatDate(item.publishedDate || item.createdDate)}
      </td>
      <td data-label="Actions">
        <Menu positioning="below-end">
          <MenuTrigger disableButtonEnhancement>
            <Button
              appearance="subtle"
              className="no-dropdown-icon"
              icon={<FluentIcon name="More" />}
              aria-label={`Actions for ${item.name}`}
              disabled={menuItems.length === 0 || isPublishingStatusActive(item.status)}
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
      </td>
    </tr>
  );
};

PublishedDatasetRow.propTypes = {
  item: PropTypes.object.isRequired,
  index: PropTypes.number.isRequired,
  onRefresh: PropTypes.func.isRequired,
};

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