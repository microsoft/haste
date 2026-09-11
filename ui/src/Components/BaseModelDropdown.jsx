import React from "react";
import PropTypes from "prop-types";
import { Dropdown, Option, Field } from "@fluentui/react-components";
import {
  applyBaseModelSelection,
  normalizeBaseModelOptions,
} from "./BaseModelDropdownHelper";

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

function BaseModelDropdown({
  componentState,
  setComponentState,
}) {
  const { baseModelId, baseModelIdError, cataloguedModels = [] } = componentState;
  const options = React.useMemo(
    () => normalizeBaseModelOptions(cataloguedModels),
    [cataloguedModels]
  );

  const selectedOption = options.find(
    (o) => String(o.key) === String(baseModelId)
  );

  const handleOptionSelect = (_ev, data) => {
    const picked = options.find((o) => String(o.key) === data.optionValue);
    setComponentState((currentState) =>
      applyBaseModelSelection(currentState, picked)
    );
  };

  return (
    <Field label="Base Model" validationMessage={baseModelIdError}>
      <Dropdown
        id="createEditModelTrainingBaseModel"
        placeholder="Select Model"
        selectedOptions={baseModelId ? [String(baseModelId)] : []}
        value={selectedOption ? selectedOption.baseModelName : ""}
        onOptionSelect={handleOptionSelect}
        disabled={options.length === 0}
      >
        {options.map((o) => (
          <Option key={o.key} value={String(o.key)} text={o.baseModelName}>
            {renderOption(o)}
          </Option>
        ))}
      </Dropdown>
    </Field>
  );
}

BaseModelDropdown.propTypes = {
  componentState: PropTypes.shape({
    baseModelId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    baseModelIdError: PropTypes.string,
    cataloguedModels: PropTypes.array,
  }).isRequired,
  setComponentState: PropTypes.func.isRequired,
};

export default BaseModelDropdown;
