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
import { apiRefreshSignIn, apiValidateUser } from "./util/api";
import { loadSession } from "./util/sessionStartup";
import { useTheme } from "./util/ThemeContext";
import { getPalette } from "./util/theme";

import { useLocation } from 'react-router-dom';

import GuidedTour from "./Components/GuidedTour";

// Components
import AppBody from "./Components/AppBody";
import AppHeader from "./Components/AppHeader";
import AppSidebar from "./Components/AppSidebar";
import AppFooter from "./Components/AppFooter";
import {
  RouteLoading,
} from "./Components/MapRoute";
import { getRouteLoadingLabel } from "./Components/routeLoading";
import WorkspaceLoader from "./Components/WorkspaceLoader";
import { LABELING_WORKSPACE_STEPS } from "./Components/LabelingTool/labelingToolLoading";

function App() {
  const { appParams, setDialog, setAppParams } =
    useContext(AppContext);
  const { palette, setPalette, mode, setTheme } = useTheme();
  const location = useLocation();
  const isHome = location.pathname === '/' || location.pathname === '/home';

  const [modalComponent, setModalComponent] = useState(null);
  const [sessionError, setSessionError] = useState(null);
  const [pendingCheckInProgress, setPendingCheckInProgress] = useState(false);
  const [navCollapsed, setNavCollapsed] = useState(() => {
    const stored = localStorage.getItem("haste-nav-collapsed");
    return stored === null ? true : stored === "true";
  });

  const isMobileNav = Number(appParams.bootstrapBreakpoint) <= 2;
  const isStandardLabeling = location.pathname.startsWith("/labeling-tool/");

  const toggleNav = () => {
    setNavCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem("haste-nav-collapsed", String(next));
      return next;
    });
  };

  const validateUser = () =>
    loadSession({
      validateUser: apiValidateUser,
      setAppParams,
      setSessionError,
    });

  const checkPendingAccess = async () => {
    if (pendingCheckInProgress) return;
    setPendingCheckInProgress(true);
    try {
      await validateUser();
    } finally {
      setPendingCheckInProgress(false);
    }
  };

  const refreshSignIn = () => {
    // Do not carry query strings through SWA redirects: invitation links can
    // contain bearer tokens. Returning to the current path is sufficient.
    apiRefreshSignIn(location.pathname);
  };

  useEffect(() => {
    validateUser();

    //eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The initial session bootstrap already attempts pending-user reconciliation.
  // Make one delayed retry for invitation/role propagation, then leave retries
  // user-led through the Check access button rather than polling Azure forever.
  useEffect(() => {
    if (appParams.userStatus !== "PendingAcceptance") return undefined;

    const retryTimer = window.setTimeout(() => {
      checkPendingAccess();
    }, 12_000);
    return () => window.clearTimeout(retryTimer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appParams.userStatus]);

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
        {sessionError ? (
          <div
            className="d-flex flex-column justify-content-center align-items-center vh-100 gap-3 px-3 text-center"
            role="alert"
          >
            <h2>
              {sessionError.kind === "unauthorized"
                ? "Sign-in needs refreshing"
                : sessionError.kind === "forbidden"
                  ? "Access unavailable"
                  : "We couldn't connect to HASTE"}
            </h2>
            <p>
              {sessionError.kind === "unauthorized"
                ? "Your sign-in may have expired. Refresh your sign-in or try again."
                : sessionError.kind === "forbidden"
                  ? "Your account could not access HASTE. Contact your administrator if you think this is a mistake."
                  : "Please try again. If the problem continues, refresh your sign-in or contact support."}
            </p>
            <div className="d-flex flex-wrap justify-content-center gap-2">
              <Button appearance="primary" onClick={validateUser}>
                Try again
              </Button>
              {sessionError.kind !== "forbidden" && (
                <Button onClick={refreshSignIn}>Refresh sign-in</Button>
              )}
            </div>
            <small>
              Support reference: {sessionError.reference} · {sessionError.timestamp}
              {sessionError.status ? ` · HTTP ${sessionError.status}` : ""}
            </small>
          </div>
        ) : [
          "Inactive",
          "PendingAcceptance",
          "Deleted",
          "RefreshingAccess",
        ].includes(appParams.userStatus) ? (
          <div className="d-flex flex-column justify-content-center align-items-center vh-100 gap-3 px-3 text-center">
            <h5>
              {appParams.userStatus === "PendingAcceptance"
                ? `${appParams.userId} account is pending invitation completion`
                : appParams.userStatus === "RefreshingAccess"
                  ? "Your HASTE account is registered; sign-in needs refreshing"
                  : appParams.userStatus === "Deleted"
                    ? `${appParams.userId} account has been deleted`
                    : `${appParams.userId} account is inactive`}
            </h5>
            <p>
              {appParams.userStatus === "PendingAcceptance"
                ? "After you accept the invitation, HASTE checks access when you return. " +
                  "If you have not accepted it yet, use the original invitation link. " +
                  "If access is still pending, wait about 10 seconds and select Check access."
                : appParams.userStatus === "RefreshingAccess"
                  ? "Your current SWA session does not include the HASTE role " +
                    "required by your account. Refresh your sign-in; if access " +
                    "is still unavailable afterward, contact the HASTE administrator."
                  : "Please contact the app administrator."}
            </p>
            {appParams.userStatus === "PendingAcceptance" && (
              <Button
                appearance="primary"
                onClick={checkPendingAccess}
                disabled={pendingCheckInProgress}
              >
                {pendingCheckInProgress ? "Checking…" : "Check access"}
              </Button>
            )}
            {appParams.userStatus === "RefreshingAccess" && (
              <Button appearance="primary" onClick={refreshSignIn}>
                Refresh sign-in
              </Button>
            )}
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
            <div className="app-startup-loading">
              {isStandardLabeling ? (
                <WorkspaceLoader
                  eyebrow="Standard labeling tool"
                  title="Preparing your workspace"
                  steps={LABELING_WORKSPACE_STEPS}
                  loadState={{ step: 0, loaded: null, total: null }}
                  error=""
                  errorTitle="Could not load the labeling workspace"
                />
              ) : (
                <RouteLoading
                  label={getRouteLoadingLabel(location.pathname)}
                />
              )}
            </div>
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
