// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

// Per-tour "Don't show again" state is persisted to localStorage so it
// survives reloads, new tabs, and browser restarts (sessionStorage was a
// per-tab kludge that lost the dismissal as soon as the user closed the
// window). The values written here form a deliberately small alphabet:
//
//   missing/null     — user has never decided; treat as "not disabled"
//                      so first-time visitors still see the tour
//   "true"           — user clicked "Don't show again"; tour stays hidden
//   "false"          — user clicked Help (or otherwise explicitly
//                      re-enabled); tour is shown again
const STORAGE_KEY_SUFFIX = "Disabled";

function _storageKey(cookieName) {
  return cookieName + STORAGE_KEY_SUFFIX;
}

function _resolveCookieName(currentTour, guidedTourProperties) {
  return (
    guidedTourProperties.find((tour) => tour.name === currentTour)
      ?.cookieName || "tourGuide"
  );
}

export function validateIsGuidedTourDisabled(cookieName) {
  // Treat only the explicit "true" sentinel as disabled. A missing or
  // null entry means the user has not dismissed this tour yet, so we
  // want to show it.
  return localStorage.getItem(_storageKey(cookieName)) === "true";
}

export function initGuidedTourState(
  currentTour,
  guidedTourProperties,
  value = false,
) {
  // Initialize the storage entry only if it doesn't already exist. This
  // used to unconditionally overwrite whatever the user had previously
  // chosen, which is why "Don't show again" appeared not to persist.
  const key = _storageKey(_resolveCookieName(currentTour, guidedTourProperties));
  if (localStorage.getItem(key) === null) {
    localStorage.setItem(key, value);
  }
}

export function setGuidedTourState(
  isGuidedTourDisabled,
  initCurrentTour,
  currentTour,
  guidedTourProperties,
) {
  const cookieName = _resolveCookieName(currentTour, guidedTourProperties);
  localStorage.setItem(_storageKey(cookieName), isGuidedTourDisabled);
  if (isGuidedTourDisabled) {
    initCurrentTour(null);
  } else {
    initCurrentTour(currentTour);
  }
}
