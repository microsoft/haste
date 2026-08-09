// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

import { useContext, useEffect, useState } from "react";
import "./assets/css/style.css";
import {
  Button,
  Dialog,
  DialogSurface,
  DialogBody,
  DialogTitle,
  DialogContent,
  DialogActions,
  Toaster,
} from "@fluentui/react-components";
import { AppContext } from "./AppContext";
import { apiValidateUser, apiGet } from "./util/api";
import { useTheme } from "./util/ThemeContext";
import { getPalette } from "./util/theme";

import { useLocation } from 'react-router-dom';

import GuidedTour from "./Components/GuidedTour";

// Components
import AppBody from "./Components/AppBody";
import AppHeader from "./Components/AppHeader";
import AppSidebar from "./Components/AppSidebar";
import AppFooter from "./Components/AppFooter";
import Loading from "./Components/OtherComponents/Loading";

function App() {
  const { appParams, setDialog, setIsLoading, setAppParams } =
    useContext(AppContext);
  const { palette, setPalette, mode, setTheme } = useTheme();
  const location = useLocation();
  const isHome = location.pathname === '/' || location.pathname === '/home';

  const [modalComponent, setModalComponent] = useState(null);
  const [navCollapsed, setNavCollapsed] = useState(() => {
    const stored = localStorage.getItem("haste-nav-collapsed");
    return stored === null ? true : stored === "true";
  });

  const isMobileNav = Number(appParams.bootstrapBreakpoint) <= 2;

  const toggleNav = () => {
    setNavCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem("haste-nav-collapsed", String(next));
      return next;
    });
  };

  useEffect(() => {
    const validateUser = async () => {
      setIsLoading(true);
      await apiValidateUser(setAppParams);
      try {
        const publishing = await apiGet("GetPublishingProviders");
        setAppParams((previous) => ({
          ...previous,
          publishingEnabled: !!publishing.publishingEnabled,
          publishingProviders: publishing.providers || [],
        }));
      } catch (error) {
        console.error("Error loading publishing capabilities:", error);
      }
      setIsLoading(false);
    };

    validateUser();

    //eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Apply the user's saved color palette once preferences load. Falls back to
  // the default palette when the stored key is missing or invalid. The local
  // (localStorage) value applied in main.jsx acts as an anti-flash cache; the
  // backend value wins here.
  useEffect(() => {
    const storedKey = appParams.userSettings?.colorPalette;
    if (!storedKey) return;
    const resolved = getPalette(storedKey).key;
    if (resolved !== palette) {
      setPalette(resolved);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appParams.userSettings?.colorPalette]);

  // Apply the user's saved light/dark theme once preferences load. Anything
  // other than "dark" falls back to light. localStorage (main.jsx) is the
  // anti-flash cache; the backend value wins here.
  useEffect(() => {
    if (!appParams.userSettings) return;
    const resolved =
      appParams.userSettings.theme === "dark" ? "dark" : "light";
    if (resolved !== mode) {
      setTheme(resolved);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appParams.userSettings?.theme, appParams.userSettings]);

  useEffect(() => {
    if (isMobileNav) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setNavCollapsed(true);
    }
  }, [isMobileNav]);

  useEffect(() => {
    const handleResize = () => {

      var bootstrapBreakpoint = "";
      if (window.innerWidth < 576) {
        bootstrapBreakpoint = 0;
      } else if (window.innerWidth < 768) {
        bootstrapBreakpoint = 1;
      } else if (window.innerWidth < 992) {
        bootstrapBreakpoint = 2;
      } else if (window.innerWidth < 1200) {
        bootstrapBreakpoint = 3;
      } else if (window.innerWidth < 1400) {
        bootstrapBreakpoint = 4;
      } else {
        bootstrapBreakpoint = 5;
      }


      setAppParams(prev => ({
        ...prev,
        bootstrapBreakpoint: bootstrapBreakpoint,
      }));
    };

    window.addEventListener('resize', handleResize);

    // Set initial size
    handleResize();

    return () => {
      window.removeEventListener('resize', handleResize);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <div className={`app-container ${isHome ? 'background-color-home' : 'background-color-app'}`}>
        {appParams.userStatus === "Inactive" || appParams.userStatus === "PendingAcceptance" ? (
          <div className="d-flex flex-column justify-content-center align-items-center vh-100">
            <h5>{appParams.userId} {appParams.userStatus === "PendingAcceptance" ? "account is pending acceptance" : "account is inactive"}</h5>
            <p>{appParams.userStatus === "PendingAcceptance" ? "Please accept the invitation, if it has expired please contact the app administrator." : "Please contact the app administrator."}</p>
          </div>
        ) : (
          appParams.userId !== null ? (
            <>
              <AppHeader
                setModalComponent={setModalComponent}
                onToggleNav={toggleNav}
              />
              <div className={`app-main d-flex flex-grow-1${isMobileNav ? " app-main--mobile" : ""}`}>
                <AppSidebar
                  setModalComponent={setModalComponent}
                  collapsed={navCollapsed}
                  mobile={isMobileNav}
                  open={!navCollapsed}
                  onItemSelected={isMobileNav ? () => setNavCollapsed(true) : undefined}
                />
                {isMobileNav && !navCollapsed && (
                  <button
                    type="button"
                    className="app-sidebar-backdrop"
                    aria-label="Close navigation"
                    onClick={() => setNavCollapsed(true)}
                  />
                )}
                <AppBody setModalComponent={setModalComponent} />
              </div>
            </>
          ) : (
            <Loading />
          )
        )}

        {appParams.dialogParams.title && (
          <Dialog
            open={true}
            onOpenChange={(_, data) => {
              if (!data.open) setDialog();
            }}
          >
            <DialogSurface style={{ maxWidth: "450px" }}>
              <DialogBody>
                <DialogTitle>{appParams.dialogParams.title}</DialogTitle>
                <DialogContent>{appParams.dialogParams.subText}</DialogContent>
                <DialogActions>
                  {(appParams.dialogParams.buttons || []).map((button) =>
                    button.type === "primary" ? (
                      <Button
                        key={button.key}
                        appearance="primary"
                        onClick={button.onClick}
                      >
                        {button.text}
                      </Button>
                    ) : (
                      <Button key={button.key} onClick={button.onClick}>
                        {button.text}
                      </Button>
                    )
                  )}
                  {(!appParams.dialogParams.buttons ||
                    appParams.dialogParams.buttons.length === 0) && (
                    <Button onClick={() => setDialog()}>Close</Button>
                  )}
                </DialogActions>
              </DialogBody>
            </DialogSurface>
          </Dialog>
        )}

        {!appParams.isLoading &&
          <GuidedTour />
        }
        {modalComponent}
        <Toaster
          toasterId="job-completion-toaster"
          position="top-end"
          pauseOnWindowBlur
        />
        {appParams.userId !== null && <AppFooter />}
      </div>
    </>
  );
}

export default App;
