// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useState, useContext } from "react";
import {
  Panel,
  PanelType,
  IconButton,
  Link,
  ActionButton,
} from "@fluentui/react";
import CreateEditProjectModal from "./CreateEditProjectModal";
import { useNavigate } from "react-router-dom";
import { AppContext } from "../AppContext";
import PropTypes from "prop-types";

const AppPanel = ({ setModalComponent, hideHamburgerMenu }) => {
  AppPanel.propTypes = {
    setModalComponent: PropTypes.func.isRequired,
    modalComponent: PropTypes.element,
  };

  const { appParams } = useContext(AppContext);
  const navigate = useNavigate();

  /* Modal Properties */

  const [isOpen, setIsOpen] = useState(false);
  const openPanel = () => setIsOpen(true);
  const dismissPanel = () => setIsOpen(false);

  const handleCreateNewProject = () => {
    dismissPanel();

    setModalComponent(
      <CreateEditProjectModal onClose={() => setModalComponent(null)} />
    );
  };

  function handleNavigate(path, newTab = false) {
    if (newTab) {
      dismissPanel();
      window.open(path, "_blank", "noopener,noreferrer");
    } else {
      navigate(path);
      dismissPanel();
    }
  }

  return (
    <>
      <div>
        {!hideHamburgerMenu && (
          <IconButton
            aria-label="menu"
            onClick={openPanel}
            iconProps={{ iconName: "GlobalNavButton" }}
            style={{ zIndex: "1000" }}
            styles={{
              root: {
                color: "white",
              },
              rootHovered: {
                backgroundColor: "transparent!important",
                color: "white",
              },
              rootExpanded: {
                backgroundColor: "transparent!important",
                color: "white",
              },
            }}
          />
        )}
        <Panel
          isOpen={isOpen}
          type={PanelType.smallFixedNear}
          onDismiss={dismissPanel}
          closeButtonAriaLabel="Close"
          isLightDismiss={true}
          className="p-0"
        >
          <div className="d-flex flex-column">
            <ActionButton
              iconProps={{ iconName: "Home" }}
              onClick={() => handleNavigate("/")}
              className="d-flex justify-content-start"
            >
              Home
            </ActionButton>

            <div
              className="mt-2 d-flex flex-column pt-2 pb-2"
              style={{ borderTop: "1px solid #999999" }}
            >
              <Link
                className="p-2 m-0 pt-1 pb-1"
                onClick={handleCreateNewProject}
              >
                Start a Project
              </Link>
              <Link
                className="p-2 m-0 pt-1 pb-1"
                onClick={() => handleNavigate("/projects")} 
              >
                Projects
              </Link>
            </div>

            {appParams.userRoles.includes("administrators") && (
              <div
                className="d-flex flex-column pt-2 pb-2"
                style={{ borderTop: "1px solid #999999" }}
              >
                <Link
                  className="p-2 m-0 pt-1 pb-1"
                  onClick={() => handleNavigate("/admin-users")}
                >
                  Users
                </Link>
                <Link
                  className="p-2 m-0 pt-1 pb-1"
                  onClick={() => handleNavigate("/model-catalog")}
                >
                  Model Catalog
                </Link>
                <Link
                  className="p-2 m-0 pt-1 pb-1 d-none"
                  onClick={() => handleNavigate("/admin-source-types")}
                >
                  Source types
                </Link>
                <Link
                  className="p-2 m-0 pt-1 pb-1 d-none"
                  onClick={() => handleNavigate("/admin-labeling-tool")}
                >
                  Labeling tool
                </Link>
              </div>
            )}

            <div
              className="mt-2 d-flex flex-column pt-2 pb-2"
              style={{ borderTop: "1px solid #999999" }}
            >
              <Link
                className="p-2 m-0 pt-1 pb-1"
                onClick={() => handleNavigate("/help-docs", true)}
              >
                Documentation
              </Link>
            </div>
          </div>
        </Panel>
      </div>
    </>
  );
};

export default AppPanel;
