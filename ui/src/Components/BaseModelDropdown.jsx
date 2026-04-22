import React from "react";
import { Dropdown } from "@fluentui/react";

const styles = {
  container: {
    display: "flex",
    flexDirection: "column",
    width: "100%",
    overflow: "hidden",
  },
  title: {
    paddingTop: "10px",
    fontSize: 14,
    fontWeight: 500,
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  selectedTitle: {
    fontSize: 14,
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  subtitle: {
    fontSize: 11,
    color: "#616161",
    marginTop: 2,
    lineHeight: "14px",
    paddingBottom: "10px",
    borderBottom: "1px solid #dadada",
  },
};

// Renders each item in the open menu
const renderOption = (option) => {
  if (!option) return null;
  const { baseModelName, description, eventTypes, imagerySource } = option;
  return (
    <div style={styles.container}>
      <div style={styles.title}>{baseModelName}</div>
      <div style={styles.subtitle}>
        {description !== "" &&
          <div style={{ paddingTop: '2px', paddingBottom: '2px' }}>{description}</div>
        }
        {imagerySource !== "" &&
          <div style={{ paddingTop: '2px', paddingBottom: '2px' }}><b>Imagery Source:</b> {imagerySource}</div>
        }
        {eventTypes && eventTypes.length > 0 && (
          <div style={{ paddingTop: '2px', paddingBottom: '2px' }}><b>Event Types:</b> {eventTypes.join(", ")}</div>
        )}
      </div>
    </div>
  );
};

// Renders the selected value (collapsed field)
const renderTitle = (selectedOptions) => {
  const selected = selectedOptions && selectedOptions[0];
  if (!selected) return null;
  const { baseModelName } = selected;

  return (
    <div style={styles.container}>
      <span style={styles.selectedTitle}>{baseModelName}</span>
    </div>
  );
};

function BaseModelDropdown({
  componentState,
  setComponentState,
  onFormChange,

}) {
  const { baseModelId, baseModelIdError, cataloguedModels = [] } = componentState;
  const options = React.useMemo(() => {
    return cataloguedModels.map((m) => ({
      key: m.key || "none",
      baseModelName: m.value.baseModelName || "",
      description: m.value.description.substring(0, 30) + "..." || "",
      checkpointFilePath: m.value.checkpointFilePath || "",
      eventTypes: m.value.eventTypes || [],
      imagerySource: m.value.imagerySource || ""
    }));
  }, [cataloguedModels]);

  const handleChange = (_ev, item) => {
    onFormChange(item.checkpointFilePath, "initialWeightsUrl", setComponentState, componentState);
  };

  return (
    <Dropdown
      id="createEditModelTrainingBaseModel"
      label="Base Model"
      placeholder="Select Model"
      options={options}
      selectedKey={baseModelId}
      onChange={handleChange}
      onRenderOption={renderOption}
      disabled={options.length === 0}
      onRenderTitle={renderTitle}
      errorMessage={baseModelIdError}
      styles={{
        dropdownItem: { height: "auto", minHeight: 42 },
        dropdownItemSelected: { height: "auto", minHeight: 42 },
      }}
    />
  );
}

export default BaseModelDropdown;