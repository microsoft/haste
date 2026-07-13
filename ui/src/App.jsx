// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

import { useMemo, useContext, useEffect, useState } from "react";
import "./assets/css/style.css";
import { DefaultButton, PrimaryButton } from "@fluentui/react/lib/Button";
import { Dialog, DialogFooter, DialogType } from "@fluentui/react/lib/Dialog";
import { AppContext } from "./AppContext";
import { apiValidateUser, apiLogout, apiGet } from "./util/api";
import { upsertUser } from "./AppHelper";

import { useLocation } from 'react-router-dom';

import GuidedTour from "./Components/GuidedTour";

// Components
import AppBody from "./Components/AppBody";
import AppHeader from "./Components/AppHeader";
import AppFooter from "./Components/AppFooter";
import Loading from "./Components/OtherComponents/Loading";
import { initializeIcons } from "@fluentui/react";

initializeIcons();

function App() {
  const { appParams, setDialog, setIsLoading, setAppParams } =
    useContext(AppContext);
  const location = useLocation();
  const isHome = location.pathname === '/' || location.pathname === '/home';

  const [modalComponent, setModalComponent] = useState(null);

  useEffect(() => {
    const validateUser = async () => {
      setIsLoading(true);
      await apiValidateUser(setAppParams);
      setIsLoading(false);
    };

    validateUser();

    //eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  const modalPropsStyles = { main: { maxWidth: "450px" } };
  const modalProps = useMemo(
    () => ({
      isBlocking: true,
      styles: modalPropsStyles,
    }),

    //eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  const dialogContentProps = {
    title: appParams.dialogParams.title,
    subText: appParams.dialogParams.subText,
    type: DialogType.largeHeader,
  };

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
              <AppHeader setModalComponent={setModalComponent} />
              <AppBody setModalComponent={setModalComponent} />
            </>
          ) : (
            <Loading />
          )
        )}

        {appParams.dialogParams.title && (
          <Dialog
            onDismiss={() => setDialog()}
            hidden={false}
            dialogContentProps={dialogContentProps}
            modalProps={modalProps}
          >
            <DialogFooter>
              {(appParams.dialogParams.buttons || []).map((button) =>
                button.type === "primary" ? (
                  <PrimaryButton key={button.key} onClick={button.onClick}>
                    {button.text}
                  </PrimaryButton>
                ) : (
                  <DefaultButton key={button.key} onClick={button.onClick}>
                    {button.text}
                  </DefaultButton>
                )
              )}
              {(!appParams.dialogParams.buttons || appParams.dialogParams.buttons.length === 0) && (
                <DefaultButton onClick={() => setDialog()}>Close</DefaultButton>
              )}
            </DialogFooter>
          </Dialog>
        )}

        {!appParams.isLoading &&
          <GuidedTour />
        }
        {modalComponent}
        {appParams.userId !== null && <AppFooter />}
      </div>
    </>
  );
}

export default App;
