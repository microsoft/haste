// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
  export function validateIsGuidedTourDisabled(cookieName) {
    const sessionStorageValue = sessionStorage.getItem(cookieName + "Disabled");
    if (sessionStorageValue === "false") {
        return false;
    }else if (sessionStorageValue === null  || sessionStorageValue === "true") {
        return true;
    }

    return false;
  }

  export function initGuidedTourState(currentTour, guidedTourProperties, value = true ) {
    const cookieName = guidedTourProperties.find((tour) => tour.name === currentTour)?.cookieName || "tourGuide";
    sessionStorage.setItem(cookieName + "Disabled", value);
  }


  export function setGuidedTourState(isGuidedTourDisabled, initCurrentTour, currentTour, guidedTourProperties ) {
    const cookieName = guidedTourProperties.find((tour) => tour.name === currentTour)?.cookieName || "tourGuide";
    sessionStorage.setItem(cookieName + "Disabled", isGuidedTourDisabled);
    if (isGuidedTourDisabled) {
      initCurrentTour(null);
    } else {
      initCurrentTour(currentTour);
    }
  }
