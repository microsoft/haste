// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { IconButton, Text, TooltipHost, Link } from "@fluentui/react";

import PropTypes from "prop-types";
import { apiDelete } from "../../util/api";
import { AppContext } from "../../AppContext";
import CreateEditProjectModal from "../CreateEditProjectModal";
import { useNavigate } from "react-router-dom";
import { limitTextLength } from "../../util/conversion";

import React from "react";

const ProjectRow = ({ item, index, setModalComponent, fetchProjects, moreInfoVisibleId, setMoreInfoVisibleId }) => {
  ProjectRow.propTypes = {
    item: PropTypes.object.isRequired,
    index: PropTypes.number.isRequired,
    setModalComponent: PropTypes.func,
    fetchProjects: PropTypes.func.isRequired,
    moreInfoVisibleId: PropTypes.string,
    setMoreInfoVisibleId: PropTypes.func,
  };

  const navigate = useNavigate();
  const { setDialog, setIsLoading } = React.useContext(AppContext);

  const moreMenuOptions = {
    items: [
      {
        key: "info",
        className: "d-block d-lg-none",
        text: moreInfoVisibleId === item.projectId ? "Hide Info" : "View Info",
        iconProps: { iconName: moreInfoVisibleId === item.projectId ? "Cancel" : "Info" },
        onClick: () => {
          if (moreInfoVisibleId === item.projectId) {
            setMoreInfoVisibleId(null);
          } else {
            setMoreInfoVisibleId(item.projectId);
          }
        },
      },
      {
        key: "edit",
        text: "Edit",
        iconProps: { iconName: "Edit" },
        onClick: () => {
          setModalComponent(
            <CreateEditProjectModal
              onClose={() => setModalComponent(null)}
              projectId={item.projectId}
            />
          );
        },
      },
      {
        key: "remove",
        text: "Remove",
        iconProps: { iconName: "Delete" },
        onClick: () => {
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
        },
      }
    ],
  };

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

  return (
    <React.Fragment>
      <tr>
        <td className="custom-text-no-wrap">
          <TooltipHost content={item.name} delay={2}>
            <Text variant="medium" className="pe-4 d-flex flex-column" id={"projectsName" + index}>
              <Link onClick={() => navigate(`/project/${item.projectId}`)}>
                {limitTextLength(item.name, false, 55)}
              </Link>
            </Text>
          </TooltipHost>


          {moreInfoVisibleId == item.projectId && (<>
            <Text variant="small">
              <table className="col-12 dashboard-inner-table p-3 mt-2">
                <tbody>
                  <tr>
                    <td>
                      <div className="pb-2">
                        <Text
                          variant="small"
                          className="me-4 fw-semibold custom-text-color"
                        >
                          Project Info:
                        </Text>
                      </div>
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <span className="fw-semibold">Description:</span>{limitTextLength(item.description, 500, 55)}
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <span className="fw-semibold">Layer Count:</span> {item.imageLayerCount}
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <span className="fw-semibold">Creation Date:</span> {item.creationDate.substring(0, 10) + " " + item.creationDate.substring(11, 19)}
                    </td>
                  </tr>
                </tbody>
              </table>
            </Text>
          </>
          )}


        </td>
        <td className="custom-text-no-wrap d-none d-lg-table-cell">
          <Text
            variant="medium"
            className="pe-4 ellipsis"
            id={"projectsDescription" + index}
          >
            <TooltipHost content={item.description} delay={2}>
              {limitTextLength(item.description, 80, 70)}
            </TooltipHost>
          </Text>
        </td>
        <td className="custom-text-no-wrap d-none d-xl-table-cell">
          <Text
            variant="medium"
            className="pe-4"
            id={"projectsImageLayerCount" + index}
          >
            {item.imageLayerCount}
          </Text>
        </td>
        <td className="custom-text-no-wrap d-none d-xl-table-cell">
          <Text
            variant="medium"
            className="pe-4"
            id={"projectsCreationDate" + index}
          >
            {item.creationDate.substring(0, 10) +
              " " +
              item.creationDate.substring(11, 19)}
          </Text>
        </td>
        <td className="custom-text-no-wrap d-flex align-items-start align-items-md-center justify-content-end">
          <IconButton
            id={"projectsMoreOptions" + index}
            className="no-dropdown-icon"
            menuProps={moreMenuOptions}
            iconProps={{ iconName: "more" }}
            title="Menu"
            ariaLabel="Menu"
          />
        </td>
      </tr>
    </React.Fragment>
  );
};

export default ProjectRow;
