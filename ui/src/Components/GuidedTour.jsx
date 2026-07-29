// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useContext, useEffect, useState } from "react";
import { AppContext } from "../AppContext.jsx";
import {
  Text,
  Button,
  Checkbox,
  Popover,
  PopoverSurface,
} from "@fluentui/react-components";
import { FluentIcon } from "../util/icons";
import parse from "html-react-parser";
import {
  setGuidedTourState,
  validateIsGuidedTourDisabled,
} from "./GuidedTourHelper.js";

const GuidedTour = () => {
  const { initCurrentTour, setCurrentTourStep, appParams } = useContext(AppContext);
  const [filteedTourSteps, setFilteredTourSteps] = useState([]);
  const [isVisible, setIsVisible] = useState(false);

  

  useEffect(() => {
    if (appParams.currentTour) {
      const shouldShow =
        !appParams.userSettings.disableGuidedTour &&
        !validateIsGuidedTourDisabled(appParams.currentTour.cookieName);
      // Explicitly reset rather than only flipping to true; otherwise a
      // previously-shown tour leaves isVisible=true and a freshly-started
      // tour that should be hidden ("Don't show again" already clicked)
      // would briefly render before being dismissed.
      setIsVisible(shouldShow);

      const filteredSteps = appParams.currentTour.steps.filter((step) => {
        if (step.type !== "teachingBubble") {
          return true;
        }else if(step.type === "teachingBubble") {
          const targetElement = document.querySelector(step.target);
          return targetElement !== null;
        }

        return false;
      });
      setFilteredTourSteps(filteredSteps);
    }
  }, [appParams]);


  const handleStepChange = (stepChange) => {
    const newStep = appParams.currentTourStep + stepChange;
    if (newStep >= 1 && newStep < appParams.currentTour.steps.length + 1) {
      setCurrentTourStep(newStep);
    }
  };

  const renderTeachingBubble = () => {
    const step = filteedTourSteps[appParams.currentTourStep - 1];
    const anchor = document.querySelector(step.target);
    if (!anchor) {
      return null;
    }

    return (
      <Popover open positioning={{ target: anchor }}>
        <PopoverSurface>
          <div className="d-flex flex-column" style={{ maxWidth: "320px" }}>
            <div className="d-flex mb-2 justify-content-between align-items-center">
              <Text className="fw-semibold">{step.title}</Text>
              <Button
                appearance="subtle"
                icon={<FluentIcon name="Cancel" />}
                aria-label="Close"
                onClick={() => {
                  initCurrentTour(null);
                  setFilteredTourSteps([]);
                }}
              />
            </div>
            <Text>
              {/*
                SECURITY: parse() renders HTML from tour-step `content`. This
                is safe ONLY because tour definitions are static,
                maintainer-authored config bundled with the app (see
                GuidedTourHelper / guidedTourProperties) — never user input or
                API-sourced data. If tour content ever becomes user-editable or
                fetched at runtime, this becomes an XSS sink: switch to a safe
                renderer (e.g. react-markdown) or sanitize before parsing.
              */}
              {parse(step.content)}
            </Text>

            <Checkbox
              label="Don’t show again. Click “?” at the top to re-enable."
              className="mt-4 mb-4"
              onChange={(ev, data) => {
                setGuidedTourState(
                  data.checked,
                  initCurrentTour,
                  appParams.currentTour.name,
                  appParams.guidedTourProperties
                );
              }}
            />

            <div className="d-flex justify-content-between align-items-center">
              <Text>{`${appParams.currentTourStep} of ${filteedTourSteps.length}`}</Text>
              <div>
                {appParams.currentTourStep > 1 && (
                  <Button className="me-2" onClick={() => handleStepChange(-1)}>
                    Previous
                  </Button>
                )}
                {appParams.currentTourStep < filteedTourSteps.length && (
                  <Button
                    appearance="primary"
                    onClick={() => handleStepChange(1)}
                  >
                    Next
                  </Button>
                )}
              </div>
            </div>
          </div>
        </PopoverSurface>
      </Popover>
    );
  };

  return (
    <>
      {appParams.currentTour && isVisible &&
        filteedTourSteps &&
        appParams.currentTourStep <= filteedTourSteps.length &&
        filteedTourSteps[appParams.currentTourStep - 1].type ===
          "fixed" && (
          <div
            className={`fixed-guided-tour fixed-guided-tour-${
              filteedTourSteps[appParams.currentTourStep - 1].target
            }`}
          >
            <div className="d-flex flex-column" style={{ padding: "15px" }}>
              <div className="d-flex mb-2 justify-content-between align-items-center">
                <Text className="fw-semibold text-light">
                  {
                    filteedTourSteps[appParams.currentTourStep - 1]
                      .title
                  }
                </Text>
                <Button
                  appearance="subtle"
                  style={{ color: "#FFFFFF" }}
                  icon={<FluentIcon name="Cancel" />}
                  aria-label="Close"
                  onClick={() => {initCurrentTour(null); setFilteredTourSteps([]);}}
                />
              </div>
              <Text className="text-light">
                {/*
                  SECURITY: parse() renders HTML from tour-step `content`. This
                  is safe ONLY because tour definitions are static,
                  maintainer-authored config bundled with the app (see
                  GuidedTourHelper / guidedTourProperties) — never user input or
                  API-sourced data. If tour content ever becomes user-editable or
                  fetched at runtime, this becomes an XSS sink: switch to a safe
                  renderer (e.g. react-markdown) or sanitize before parsing.
                */}
                {parse(
                  filteedTourSteps[appParams.currentTourStep - 1]
                    .content
                )}
              </Text>

              <Checkbox
                label="Don’t show again. Click “?” at the top to re-enable."
                className="mt-4 mb-4"
                onChange={(ev, data) => {
                  setGuidedTourState(
                    data.checked,
                    initCurrentTour,
                    appParams.currentTour.name,
                    appParams.guidedTourProperties
                  );
                }}
              />

              <div className="d-flex justify-content-between">
                <div>
                  <Text className="text-light">{`${appParams.currentTourStep} of ${filteedTourSteps.length}`}</Text>
                </div>
                <div>
                  <Button
                    style={{ border: "1px solid", color: "var(--primary-color)" }}
                    className="me-2"
                    onClick={() => {
                      handleStepChange(-1);
                    }}
                  >
                    Previous
                  </Button>
                  <Button
                    appearance="primary"
                    style={{ border: "1px solid #FFFFFF" }}
                    onClick={() => {
                      handleStepChange(1);
                    }}
                  >
                    Next
                  </Button>
                </div>
              </div>
            </div>
          </div>
        )}

      {appParams.currentTour &&
        filteedTourSteps &&
        appParams.currentTourStep <= filteedTourSteps.length &&
        filteedTourSteps[appParams.currentTourStep - 1].type ===
          "teachingBubble" && isVisible &&
        renderTeachingBubble()}
    </>
  );
};

export default GuidedTour;
