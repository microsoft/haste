// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useEffect, useContext } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { AppContext } from "../AppContext";

import { IconButton } from "@fluentui/react/lib/Button";
import AppPanel from "./AppPanel";
import SettingsModal from "./SettingsModal";
import PropTypes from "prop-types";
import { limitTextLength } from "../util/conversion";
import { TooltipHost } from "@fluentui/react";


const AppHeader = ({ setModalComponent }) => {
  AppHeader.propTypes = {
    setModalComponent: PropTypes.func.isRequired,
  };

  const { appParams } = useContext(AppContext);
  const location = useLocation();
  const navigate = useNavigate();

  const hideSettingsMenu = location.pathname.includes("/help-docs");
  const hideHamburgerMenu = location.pathname.includes("/help-docs");

  useEffect(() => {
    document.title = appParams.appTitle;
    //eslint-disable-next-line
  }, [location]);

  return (
    <div className="app-header d-flex align-items-center ps-2 pe-3">
      <div className="col flex-grow-1 d-flex align-items-center">
        <AppPanel setModalComponent={setModalComponent} hideHamburgerMenu={hideHamburgerMenu} />
        <div className="app-title fw-semibold pe-3">
          <a
            onClick={() => navigate("/")}
            className="text-white text-decoration-none"
          >
            {appParams.appTitle}
          </a>
        </div>
      </div>

      {appParams.bootstrapBreakpoint >= 3 && appParams.visualizerTitle !== "" && (
        <div className="col position-absolute text-center flex-grow-1 d-flex align-items-center justify-content-center visualizer-title">
          <div className="app-title fw-semibold pe-3">
            <TooltipHost
              content={appParams.visualizerTitle}

            >
              {limitTextLength(appParams.visualizerTitle, 50, 90)}
            </TooltipHost>
          </div>
        </div>
      )}

      {/* Desktop */}
      <div className="col d-flex justify-content-end align-items-center">

        {appParams.appHeaderRightButtons.map((button, index) => (
          <IconButton
            key={index}
            id={button.id}
            className="d-flex no-dropdown-icon"
            iconProps={{ iconName: button.iconName }}
            title={button.title}
            onClick={button.onClick}
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
            ariaLabel={button.title}
          />
        ))}

        {!hideSettingsMenu && (
          <IconButton
            className="d-flex no-dropdown-icon"
            iconProps={{ iconName: "settings" }}
            title="Menu"
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
            ariaLabel="Menu"
            onClick={() => setModalComponent(<SettingsModal onClose={() => setModalComponent(null)} />)}
          />
        )}
      </div>
    </div>
  );
};

export default AppHeader;
