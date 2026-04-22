// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { apiGet } from "../util/api";
import staticSettings from "../assets/json/settings.json";

/* AFFECTED COUNTRY FUNCTIONS */
export function addAffectedCountry(setComponentState, componentState, selectedCountry) {
  if (selectedCountry) {
    if (!componentState.affectedCountries.includes(selectedCountry.key)) {
      setComponentState({
        ...componentState,
        affectedCountries: [
          ...componentState.affectedCountries,
          selectedCountry.key,
        ],
      });
    }
  }
}

export function removeAffectedCountry(country, setComponentState, componentState, setSelectedCountry) {
  setComponentState({
    ...componentState,
    affectedCountries: componentState.affectedCountries.filter(
      (c) => c !== country
    ),
  });
  setSelectedCountry(null);
}


/* EVENT TYPES FUNCTIONS */

export function addEventType(setComponentState, componentState, selectedEventType) {
  if (selectedEventType) {
    if (!componentState.eventTypes.includes(selectedEventType.key)) {

      const selectedEventTypePrimaryClasses = [];

      for (const primaryClass of selectedEventType.defaultPrimaryClasses) {
        // Check if any other event type (already selected) has this primary class
        const isPrimaryClassUsed = componentState.eventTypes.some(etKey => {
          const et = staticSettings.eventTypeList.find(e => e.name === etKey);
          return et?.defaultPrimaryClasses?.some(pc => pc.id === primaryClass.id);
        });

        if (!isPrimaryClassUsed) {
          // Find the available primary class object
          const availablePrimaryClass = componentState.primaryClassesList.find(pc => pc.id === primaryClass.id);
          if (availablePrimaryClass) {
            availablePrimaryClass.eventType = staticSettings.eventTypeList
              .filter(et => et.defaultPrimaryClasses?.some(pc => pc.id === availablePrimaryClass.id))
              .map(et => et.name);
            selectedEventTypePrimaryClasses.push(availablePrimaryClass);
          }
        }
      }

      setComponentState({
        ...componentState,
        eventTypes: [selectedEventType.key, ...componentState.eventTypes],
        primaryClasses: [
          ...componentState.primaryClasses,
          ...selectedEventTypePrimaryClasses,
        ],
      });
    }
  }
}

export function getDefaultEventType(defaultEventType, primaryClassesList) {
  if (defaultEventType) {
    const selectedEventTypePrimaryClasses = [];

    for (const primaryClass of defaultEventType.defaultPrimaryClasses) {
      const matchingPrimaryClass = primaryClassesList.find(pc => pc.id === primaryClass.id);
      if (matchingPrimaryClass) {
        // Add eventType property as in addEventType
        const eventTypeNames = staticSettings.eventTypeList
          .filter(et => et.defaultPrimaryClasses?.some(pc => pc.id === matchingPrimaryClass.id))
          .map(et => et.name);
        selectedEventTypePrimaryClasses.push({
          ...matchingPrimaryClass,
          eventType: eventTypeNames
        });
      }
    }
    return selectedEventTypePrimaryClasses;
  }
}


export function removeEventType(eventType, setComponentState, componentState, setSelectedEventType) {
  // Remove the event type
  const updatedEventTypes = componentState.eventTypes.filter(
    (e) => e !== eventType
  );

  // Find all primary class IDs that should remain (from remaining event types)
  const remainingPrimaryClassIds = new Set();
  for (const etKey of updatedEventTypes) {
    const et = staticSettings.eventTypeList.find(e => e.name === etKey);
    if (et && et.defaultPrimaryClasses) {
      et.defaultPrimaryClasses.forEach(pc => remainingPrimaryClassIds.add(pc.id));
    }
  }

  // Filter primaryClasses:
  // - Keep if id is in remainingPrimaryClassIds
  // - OR if it does NOT have eventType property (not related to any eventType)
  const updatedPrimaryClasses = componentState.primaryClasses.filter(
    pc =>
      remainingPrimaryClassIds.has(pc.id) ||
      typeof pc.eventType === "undefined"
  );

  setComponentState({
    ...componentState,
    eventTypes: updatedEventTypes,
    primaryClasses: updatedPrimaryClasses,
  });

  setSelectedEventType(null);
}

export function removePrimaryClass(index, setComponentState, componentState, setDialog) {
  if (componentState.primaryClasses.length > 1) {
    setComponentState({
      ...componentState,
      primaryClasses: componentState.primaryClasses.filter(
        (c, i) => i !== index
      ),
    });
  } else {
    setDialog("Error", "At least one primary class is required", []);
  }
}

export function addPrimaryClass(setComponentState, componentState) {
  const tempPrimaryClass = { name: "", color: "#000000" };
  setComponentState({
    ...componentState,
    primaryClasses: [...componentState.primaryClasses, tempPrimaryClass],
  });
}

export function onChangePrimaryClass(index, key, value, setComponentState, componentState) {
  const tempPrimaryClasses = componentState.primaryClasses;
  tempPrimaryClasses[index][key] = value;
  setComponentState({
    ...componentState,
    primaryClasses: tempPrimaryClasses,
  });
}


export function onFormChange(key, value, setComponentState, componentState) {
  if (key === "eventDate") {
    value = value ? new Date(value) : "";
  }

  setComponentState({ ...componentState, [key]: value });
}


export async function createComponentDefaultState(projectId) {
  var projectToEdit = undefined;
  if (projectId !== undefined) {
    projectToEdit = await apiGet("GetProjectDetails?projectId=" + projectId);
  }
  const settings = await apiGet("GetAdminSettings");
  var countries = [];

  try {

    const response = await fetch(`${window.location.origin}/assets/json/world.geojson`);

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const data = await response.json();
    if (data.type !== "FeatureCollection") {
      throw new Error("Invalid GeoJSON format");
    }
    countries = (
      data.features
        .map((feature) => ({
          key: feature.id,
          text: feature.properties.name,
        }))
        .sort((a, b) => a.text.localeCompare(b.text))
    );
  } catch (error) {
    console.error("Error fetching countries:", error);
  }

  const projectEventTypeList = staticSettings.eventTypeList.map((eventType) => ({
    text: eventType.name,
    key: eventType.name,
    defaultPrimaryClasses: eventType.defaultPrimaryClasses || [],
  }));

  const defaultEventType = [projectEventTypeList[0].key] ?? [];
  const defaultPrimaryClasses = getDefaultEventType(projectEventTypeList[0], staticSettings.primaryClassesList ?? []);


  const tempState = projectToEdit
    ? {
      ...projectToEdit,
      nameError: "",
      eventTypesError: "",
      affectedCountriesError: "",
      primaryClassesError: "",
      countries: countries,
      eventTypes: projectToEdit.eventTypes ?? [],
      eventTypeList: projectEventTypeList,
      primaryClassesList: staticSettings.primaryClassesList ?? [],
    }
    : {
      projectId: "",
      name: "",
      nameError: "",
      description: "",
      eventTypesError: "",
      eventDate: "",
      eventDateError: "",
      affectedCountries: [],
      affectedCountriesError: "",
      primaryClasses: defaultPrimaryClasses,
      primaryClassesError: "",
      countries: countries,
      eventTypes: defaultEventType,
      eventTypeList: projectEventTypeList,
      primaryClassesList: staticSettings.primaryClassesList ?? [],
    };
  return tempState;
}
