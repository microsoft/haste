// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useContext } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { FluentIcon } from "../util/icons";
import CreateEditProjectModal from "./CreateEditProjectModal";
import { AppContext } from "../AppContext";
import PropTypes from "prop-types";

const AppSidebar = ({
  setModalComponent,
  collapsed,
  mobile,
  open,
  onItemSelected,
}) => {
  AppSidebar.propTypes = {
    setModalComponent: PropTypes.func.isRequired,
    collapsed: PropTypes.bool,
    mobile: PropTypes.bool,
    open: PropTypes.bool,
    onItemSelected: PropTypes.func,
  };

  const { appParams } = useContext(AppContext);
  const navigate = useNavigate();
  const location = useLocation();

  const handleCreateNewProject = () => {
    setModalComponent(
      <CreateEditProjectModal onClose={() => setModalComponent(null)} />
    );
    if (onItemSelected) {
      onItemSelected();
    }
  };

  const handleNavigate = (path, newTab = false) => {
    if (newTab) {
      window.open(path, "_blank", "noopener,noreferrer");
    } else {
      navigate(path);
    }
    if (onItemSelected) {
      onItemSelected();
    }
  };

  const pathname = location.pathname;
  const isAdmin = appParams.userRoles?.includes("administrators");

  const sections = [
    {
      key: "main",
      items: [
        {
          key: "home",
          label: "Home",
          icon: "Home",
          onClick: () => handleNavigate("/"),
          active: pathname === "/",
        },
      ],
    },
    {
      key: "projects",
      title: "Projects",
      items: [
        {
          key: "start-project",
          label: "Start a Project",
          icon: "FabricNewFolder",
          onClick: handleCreateNewProject,
          active: false,
        },
        {
          key: "projects",
          label: "Projects",
          icon: "FolderHorizontal",
          onClick: () => handleNavigate("/projects"),
          active:
            pathname.startsWith("/projects") ||
            pathname.startsWith("/project/"),
        },
      ],
    },
    ...(isAdmin
      ? [
          {
            key: "admin",
            title: "Administration",
            items: [
              {
                key: "users",
                label: "Users",
                icon: "GroupList",
                onClick: () => handleNavigate("/admin-users"),
                active: pathname.startsWith("/admin-users"),
              },
              {
                key: "model-catalog",
                label: "Model Catalog",
                icon: "ProductCatalog",
                onClick: () => handleNavigate("/model-catalog"),
                active: pathname.startsWith("/model-catalog"),
              },
            ],
          },
        ]
      : []),
    {
      key: "help",
      title: "Help",
      items: [
        {
          key: "documentation",
          label: "Documentation",
          icon: "ReportDocument",
          onClick: () => handleNavigate("/help-docs", true),
          active: false,
        },
      ],
    },
  ];

  const sidebarClasses = ["app-sidebar"];
  if (!mobile && collapsed) {
    sidebarClasses.push("app-sidebar--collapsed");
  }
  if (mobile) {
    sidebarClasses.push("app-sidebar--mobile");
    if (open) {
      sidebarClasses.push("app-sidebar--open");
    }
  }

  return (
    <nav className={sidebarClasses.join(" ")} aria-label="Main navigation">
      <div className="app-sidebar-scroll">
        {sections.map((section) => (
          <div className="app-sidebar-section" key={section.key}>
            {section.title && (
              <div className="app-sidebar-section-title">{section.title}</div>
            )}
            {section.items.map((item) => (
              <button
                type="button"
                key={item.key}
                className={`app-sidebar-item${
                  item.active ? " app-sidebar-item--active" : ""
                }`}
                onClick={item.onClick}
                title={item.label}
                aria-label={item.label}
              >
                <FluentIcon
                  name={item.icon}
                  className="app-sidebar-item-icon"
                />
                <span className="app-sidebar-item-label">{item.label}</span>
              </button>
            ))}
          </div>
        ))}
      </div>
    </nav>
  );
};

export default AppSidebar;
