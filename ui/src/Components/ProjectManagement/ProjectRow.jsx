// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import {
  Button,
  Tooltip,
  Menu,
  MenuTrigger,
  MenuPopover,
  MenuList,
  MenuItem,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";

import PropTypes from "prop-types";
import { apiDelete } from "../../util/api";
import { AppContext } from "../../AppContext";
import CreateEditProjectModal from "../CreateEditProjectModal";
import { useNavigate } from "react-router-dom";
import { limitTextLength } from "../../util/conversion";
import { formatProjectDate } from "./projectStatus";

import React from "react";

const ProjectRow = ({
  item,
  index,
  columns,
  countryNames,
  setModalComponent,
  fetchProjects,
}) => {
  ProjectRow.propTypes = {
    item: PropTypes.object.isRequired,
    index: PropTypes.number.isRequired,
    columns: PropTypes.arrayOf(
      PropTypes.shape({
        key: PropTypes.string.isRequired,
        label: PropTypes.string,
      })
    ).isRequired,
    countryNames: PropTypes.object,
    setModalComponent: PropTypes.func,
    fetchProjects: PropTypes.func.isRequired,
  };

  const navigate = useNavigate();
  const { setDialog, setIsLoading } = React.useContext(AppContext);

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function handleDeletion() {
    try {
      setDialog();
      setIsLoading(true, "Removing Project...");
      await apiDelete(`DeleteProject?projectId=${item.projectId}`);
      await sleep(4000);
      await fetchProjects();
    } catch (error) {
      setDialog("Error", "Error removing project, Please try again later", [
        {
          type: "primary",
          key: "close",
          text: "Close",
          onClick: () => setDialog(),
        },
      ]);
    }
    setIsLoading(false);
  }

  function confirmRemove() {
    setDialog(
      "Important",
      `Do you want to remove the project "${item.name}"?. This will remove all child Image Layers, Labels and Models.`,
      [
        {
          type: "primary",
          key: "yes",
          text: "Yes",
          onClick: handleDeletion,
        },
        {
          type: "default",
          key: "no",
          text: "No",
          onClick: () => setDialog(),
        },
      ]
    );
  }

  function renderCell(column) {
    const key = column.key;
    const label = column.label || key;
    switch (key) {
      case "name":
        return (
          <td key={key} data-label={label}>
            <div className="pgrid-name-cell">
              <FluentIcon name="FolderHorizontal" className="pgrid-name-icon" />
              <Tooltip content={item.name} relationship="label">
                <span
                  className="pgrid-name-link"
                  id={"projectsName" + index}
                  role="link"
                  tabIndex={0}
                  onClick={() => navigate(`/project/${item.projectId}`)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      navigate(`/project/${item.projectId}`);
                    }
                  }}
                >
                  {limitTextLength(item.name, false, 45)}
                </span>
              </Tooltip>
            </div>
          </td>
        );
      case "description":
        return (
          <td key={key} data-label={label}>
            <Tooltip content={item.description || "—"} relationship="label">
              <div
                className="pgrid-desc-cell"
                id={"projectsDescription" + index}
              >
                {item.description ? (
                  limitTextLength(item.description, 90, 90)
                ) : (
                  <span className="pgrid-muted">—</span>
                )}
              </div>
            </Tooltip>
          </td>
        );
      case "createdBy": {
        const createdBy = item.createdBy || item.userId;
        return (
          <td key={key} data-label={label} id={"projectsCreatedBy" + index}>
            {createdBy ? (
              limitTextLength(createdBy, 40, 40)
            ) : (
              <span className="pgrid-muted">—</span>
            )}
          </td>
        );
      }
      case "affectedCountries": {
        const countries = Array.isArray(item.affectedCountries)
          ? item.affectedCountries
          : [];
        if (countries.length === 0) {
          return (
            <td key={key} data-label={label}>
              <span className="pgrid-muted">—</span>
            </td>
          );
        }
        const shown = countries.slice(0, 2);
        const rest = countries.length - shown.length;
        const countryName = (code) => countryNames?.[code] ?? code;
        return (
          <td key={key} data-label={label} id={"projectsCountries" + index}>
            <div className="pgrid-country-cell">
              {shown.map((country) => (
                <span className="pgrid-country-pill" key={country}>
                  <FluentIcon name="Globe" className="pgrid-country-icon" />
                  {countryName(country)}
                </span>
              ))}
              {rest > 0 && (
                <Tooltip content={countries.map(countryName).join(", ")} relationship="label">
                  <span className="pgrid-country-pill pgrid-country-more">
                    +{rest}
                  </span>
                </Tooltip>
              )}
            </div>
          </td>
        );
      }
      case "imageLayerCount":
        return (
          <td key={key} data-label={label} className="pgrid-td-numeric">
            <span
              className="pgrid-count-badge"
              id={"projectsImageLayerCount" + index}
            >
              {item.imageLayerCount ?? 0}
            </span>
          </td>
        );
      case "modelsCount":
        return (
          <td key={key} data-label={label} className="pgrid-td-numeric">
            <span className="pgrid-count-badge">{item.modelsCount ?? 0}</span>
          </td>
        );
      case "labelsCount":
        return (
          <td key={key} data-label={label} className="pgrid-td-numeric">
            <span className="pgrid-count-badge">{item.labelsCount ?? 0}</span>
          </td>
        );
      case "creationDate":
        return (
          <td key={key} data-label={label} id={"projectsCreationDate" + index}>
            {formatProjectDate(item.creationDate)}
          </td>
        );
      default:
        return <td key={key} data-label={label} />;
    }
  }

  return (
    <tr>
      {columns.map((col) => renderCell(col))}
      <td className="pgrid-td-numeric" data-label="Actions">
        <Menu positioning="below-end">
          <MenuTrigger disableButtonEnhancement>
            <Button
              id={"projectsMoreOptions" + index}
              appearance="subtle"
              className="no-dropdown-icon"
              icon={<FluentIcon name="More" />}
              title="Menu"
              aria-label="Menu"
            />
          </MenuTrigger>
          <MenuPopover>
            <MenuList>
              <MenuItem
                icon={<FluentIcon name="OpenFolderHorizontal" />}
                onClick={() => navigate(`/project/${item.projectId}`)}
              >
                Open
              </MenuItem>
              <MenuItem
                icon={<FluentIcon name="Edit" />}
                onClick={() => {
                  setModalComponent(
                    <CreateEditProjectModal
                      onClose={() => setModalComponent(null)}
                      projectId={item.projectId}
                    />
                  );
                }}
              >
                Edit
              </MenuItem>
              <MenuItem
                icon={<FluentIcon name="Delete" />}
                onClick={confirmRemove}
              >
                Remove
              </MenuItem>
            </MenuList>
          </MenuPopover>
        </Menu>
      </td>
    </tr>
  );
};

export default ProjectRow;
