// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useContext, useEffect, useState } from "react";
import { AppContext } from "../AppContext.jsx";
import {
  Text,
  Button,
  Checkbox,
} from "@fluentui/react-components";
import { FluentIcon } from "../util/icons";
import parse from "html-react-parser";
import {
  setGuidedTourState,
  validateIsGuidedTourDisabled,
} from "./GuidedTourHelper.js";

/** True only when the element exists AND is actually rendered/visible.
 *  Guards against targets that are in the DOM but hidden (e.g. tables
 *  hidden on mobile), so their tour step is skipped instead of hanging. */
function isElementVisible(el) {
  if (!el) return false;
  const style = window.getComputedStyle(el);
  if (
    style.display === "none" ||
    style.visibility === "hidden" ||
    style.opacity === "0"
  ) {
    return false;
  }
  const rect = el.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

const GuidedTour = () => {
  const { initCurrentTour, setCurrentTourStep, appParams } = useContext(AppContext);
  const [filteedTourSteps, setFilteredTourSteps] = useState([]);
  const [isVisible, setIsVisible] = useState(false);
  // Bounding rect of the currently highlighted target (spotlight).
  const [spot, setSpot] = useState(null);

  

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
        }
        // Skip steps whose target isn't visible (missing or hidden, e.g.
        // a table that isn't rendered on mobile) so they don't hang.
        return isElementVisible(document.querySelector(step.target));
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

  const closeTour = () => {
    initCurrentTour(null);
    setFilteredTourSteps([]);
    setSpot(null);
  };

  // Track the highlighted target's position so the spotlight stays glued to
  // it while the user scrolls or resizes the window.
  useEffect(() => {
    const step = filteedTourSteps[appParams.currentTourStep - 1];
    const isBubble = step && step.type === "teachingBubble" && isVisible;
    if (!isBubble) {
      setSpot(null);
      return undefined;
    }
    const anchor = document.querySelector(step.target);
    if (!isElementVisible(anchor)) {
      setSpot(null);
      return undefined;
    }
    const update = () => {
      const r = anchor.getBoundingClientRect();
      setSpot({ top: r.top, left: r.left, width: r.width, height: r.height });
    };
    anchor.scrollIntoView({ block: "center", behavior: "smooth" });
    update();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appParams.currentTourStep, filteedTourSteps, isVisible]);

  const renderTeachingBubble = () => {
    const step = filteedTourSteps[appParams.currentTourStep - 1];
    if (!step || !spot) {
      return null;
    }

    const pad = 8;
    const holeTop = spot.top - pad;
    const holeLeft = spot.left - pad;
    const holeW = spot.width + pad * 2;
    const holeH = spot.height + pad * 2;

    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const cardW = Math.min(340, vw - 32);
    const placeBelow = spot.top + spot.height + 12 + 220 < vh;

    const cardStyle = {
      position: "fixed",
      width: cardW,
      left: Math.max(16, Math.min(holeLeft, vw - cardW - 16)),
    };
    if (placeBelow) {
      cardStyle.top = spot.top + spot.height + 14;
    } else {
      cardStyle.bottom = vh - spot.top + 14;
    }

    const totalSteps = filteedTourSteps.length;

    return (
      <div className="tour-overlay">
        <div
          className="tour-hole"
          style={{ top: holeTop, left: holeLeft, width: holeW, height: holeH }}
        />
        <div className="tour-card" style={cardStyle}>
          <div className="tour-card-head">
            <span className="tour-eyebrow">Quick tour</span>
            <Button
              appearance="subtle"
              icon={<FluentIcon name="Cancel" />}
              aria-label="Close"
              onClick={closeTour}
            />
          </div>
          <Text className="tour-card-title">{step.title}</Text>
          <div className="tour-card-body">
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
          </div>

          <Checkbox
            label="Don’t show again. Click “?” at the top to re-enable."
            className="mt-3 mb-2"
            onChange={(ev, data) => {
              setGuidedTourState(
                data.checked,
                initCurrentTour,
                appParams.currentTour.name,
                appParams.guidedTourProperties
              );
            }}
          />

          <div className="tour-card-footer">
            <Text className="tour-step">
              {`Step ${appParams.currentTourStep} of ${totalSteps}`}
            </Text>
            <div>
              {appParams.currentTourStep > 1 && (
                <Button className="me-2" onClick={() => handleStepChange(-1)}>
                  Back
                </Button>
              )}
              {appParams.currentTourStep < totalSteps ? (
                <Button appearance="primary" onClick={() => handleStepChange(1)}>
                  Next
                </Button>
              ) : (
                <Button appearance="primary" onClick={closeTour}>
                  Done
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  };

  const renderFixedCard = () => {
    const step = filteedTourSteps[appParams.currentTourStep - 1];
    if (!step) {
      return null;
    }

    const totalSteps = filteedTourSteps.length;

    return (
      <div className="tour-overlay tour-overlay-fixed">
        <div className="tour-card tour-card-fixed">
          <div className="tour-card-head">
            <span className="tour-eyebrow">Quick tour</span>
            <Button
              appearance="subtle"
              icon={<FluentIcon name="Cancel" />}
              aria-label="Close"
              onClick={closeTour}
            />
          </div>
          <Text className="tour-card-title">{step.title}</Text>
          <div className="tour-card-body">{parse(step.content)}</div>

          <Checkbox
            label="Don’t show again. Click “?” at the top to re-enable."
            className="mt-3 mb-2"
            onChange={(ev, data) => {
              setGuidedTourState(
                data.checked,
                initCurrentTour,
                appParams.currentTour.name,
                appParams.guidedTourProperties
              );
            }}
          />

          <div className="tour-card-footer">
            <Text className="tour-step">
              {`Step ${appParams.currentTourStep} of ${totalSteps}`}
            </Text>
            <div>
              <Button className="me-2" onClick={() => handleStepChange(-1)}>
                Back
              </Button>
              {appParams.currentTourStep < totalSteps ? (
                <Button appearance="primary" onClick={() => handleStepChange(1)}>
                  Next
                </Button>
              ) : (
                <Button appearance="primary" onClick={closeTour}>
                  Done
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  };

  return (
    <>
      {appParams.currentTour && isVisible &&
        filteedTourSteps &&
        appParams.currentTourStep <= filteedTourSteps.length &&
        filteedTourSteps[appParams.currentTourStep - 1].type ===
          "fixed" && renderFixedCard()}

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
