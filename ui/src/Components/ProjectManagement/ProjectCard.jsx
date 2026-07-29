// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
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
import React from "react";
import { apiDelete } from "../../util/api";
import { AppContext } from "../../AppContext";
import CreateEditProjectModal from "../CreateEditProjectModal";
import { useNavigate } from "react-router-dom";
import { limitTextLength } from "../../util/conversion";
import { formatProjectDate } from "./projectStatus";

const ProjectCard = ({
  item,
  index,
  countryNames,
  setModalComponent,
  fetchProjects,
}) => {
  ProjectCard.propTypes = {
    item: PropTypes.object.isRequired,
    index: PropTypes.number.isRequired,
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

  const openProject = () => navigate(`/project/${item.projectId}`);
  const countries = Array.isArray(item.affectedCountries)
    ? item.affectedCountries
    : [];
  const countryName = (code) => countryNames?.[code] ?? code;
  const shownCountries = countries.slice(0, 3);
  const restCountries = countries.length - shownCountries.length;

  return (
    <div className="pcard" id={"projectsCard" + index}>
      <div className="pcard-top">
        <div
          className="pcard-title"
          role="link"
          tabIndex={0}
          onClick={openProject}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") openProject();
          }}
        >
          <FluentIcon name="FolderHorizontal" className="pcard-icon" />
          <Tooltip content={item.name} relationship="label">
            <span className="pcard-name">
              {limitTextLength(item.name, false, 40)}
            </span>
          </Tooltip>
        </div>
        <div className="pcard-top-right">
          <Menu positioning="below-end">
            <MenuTrigger disableButtonEnhancement>
              <Button
                id={"projectsCardMore" + index}
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
                  onClick={openProject}
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
        </div>
      </div>

      <div className="pcard-desc">
        {item.description ? (
          limitTextLength(item.description, 120, 120)
        ) : (
          <span className="pgrid-muted">No description</span>
        )}
      </div>

      <div className="pcard-countries">
        {countries.length === 0 ? (
          <span className="pgrid-muted">No countries</span>
        ) : (
          <>
            {shownCountries.map((c) => (
              <span className="pgrid-country-pill" key={c}>
                <FluentIcon name="Globe" className="pgrid-country-icon" />
                {countryName(c)}
              </span>
            ))}
            {restCountries > 0 && (
              <Tooltip
                content={countries.map(countryName).join(", ")}
                relationship="label"
              >
                <span className="pgrid-country-pill pgrid-country-more">
                  +{restCountries}
                </span>
              </Tooltip>
            )}
          </>
        )}
      </div>

      <div className="pcard-stats">
        <div className="pcard-stat" title="Image Layers">
          <FluentIcon name="FileImage" className="pcard-stat-icon" />
          <span>{item.imageLayerCount ?? 0}</span>
        </div>
        <div className="pcard-stat" title="Models">
          <FluentIcon name="ModelingView" className="pcard-stat-icon" />
          <span>{item.modelsCount ?? 0}</span>
        </div>
        <div className="pcard-stat" title="Labels">
          <FluentIcon name="BulletedList" className="pcard-stat-icon" />
          <span>{item.labelsCount ?? 0}</span>
        </div>
      </div>

      <div className="pcard-footer">
        <span className="pcard-footer-item" title={item.createdBy || item.userId}>
          <FluentIcon name="UserEvent" className="pcard-stat-icon" />
          {item.createdBy || item.userId ? (
            limitTextLength(item.createdBy || item.userId, 24, 24)
          ) : (
            <span className="pgrid-muted">—</span>
          )}
        </span>
        <span className="pcard-footer-item">
          <FluentIcon name="Calendar" className="pcard-stat-icon" />
          {formatProjectDate(item.creationDate)}
        </span>
      </div>
    </div>
  );
};

export default ProjectCard;
