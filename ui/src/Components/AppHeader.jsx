// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useEffect, useContext } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { AppContext } from "../AppContext";

import { Button, Tooltip, makeStyles } from "@fluentui/react-components";
import SettingsModal from "./SettingsModal";
import PropTypes from "prop-types";
import { limitTextLength } from "../util/conversion";
import { FluentIcon } from "../util/icons";
import { useTheme } from "../util/ThemeContext";

const useHeaderStyles = makeStyles({
  iconButton: {
    color: "white",
    minWidth: "32px",
    ":hover": { backgroundColor: "transparent", color: "white" },
    ":hover:active": { backgroundColor: "transparent", color: "white" },
  },
});

const AppHeader = ({ setModalComponent, onToggleNav }) => {
  AppHeader.propTypes = {
    setModalComponent: PropTypes.func.isRequired,
    onToggleNav: PropTypes.func,
  };

  const { appParams } = useContext(AppContext);
  const location = useLocation();
  const navigate = useNavigate();
  const { isDark, toggle } = useTheme();
  const styles = useHeaderStyles();

  const hideSettingsMenu = location.pathname.includes("/help-docs");
  const hideHamburgerMenu = location.pathname.includes("/help-docs");

  useEffect(() => {
    document.title = appParams.appTitle;
    //eslint-disable-next-line
  }, [location]);

  return (
    <div className="app-header d-flex align-items-center ps-2 pe-3">
      <div className="col flex-grow-1 d-flex align-items-center">
        {!hideHamburgerMenu && (
          <Button
            appearance="subtle"
            aria-label="Toggle navigation"
            title="Toggle navigation"
            onClick={onToggleNav}
            icon={<FluentIcon name="GlobalNavButton" />}
            className={styles.iconButton}
          />
        )}
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
            <Tooltip content={appParams.visualizerTitle} relationship="label">
              <span>{limitTextLength(appParams.visualizerTitle, 50, 90)}</span>
            </Tooltip>
          </div>
        </div>
      )}

      {/* Desktop */}
      <div className="col d-flex justify-content-end align-items-center">

        <Button
          appearance="subtle"
          className={styles.iconButton}
          icon={<FluentIcon name={isDark ? "Sunny" : "ClearNight"} />}
          title={isDark ? "Switch to light mode" : "Switch to dark mode"}
          aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
          onClick={toggle}
        />

        {appParams.appHeaderRightButtons.map((button, index) => (
          <Button
            key={index}
            id={button.id}
            appearance="subtle"
            className={styles.iconButton}
            icon={<FluentIcon name={button.iconName} />}
            title={button.title}
            onClick={button.onClick}
            aria-label={button.title}
          />
        ))}

        {!hideSettingsMenu && (
          <Button
            appearance="subtle"
            className={styles.iconButton}
            icon={<FluentIcon name="settings" />}
            title="Menu"
            aria-label="Menu"
            onClick={() => setModalComponent(<SettingsModal onClose={() => setModalComponent(null)} />)}
          />
        )}
      </div>
    </div>
  );
};

export default AppHeader;
