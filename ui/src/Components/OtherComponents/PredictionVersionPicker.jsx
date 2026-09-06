// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import PropTypes from "prop-types";
import { Dropdown, Field, Option } from "@fluentui/react-components";
import { predictionSourceOptions, versionLabel } from "../Visualizer/predictionVersions.js";

export default function PredictionVersionPicker({ versions, value, onChange, disabled = false, currentRevision, label = "Predictions" }) {
  const options = predictionSourceOptions(versions, currentRevision);
  if (options.length < 2) return null;
  return (
    <Field label={label}>
      <Dropdown disabled={disabled} selectedOptions={[String(value)]} value={versionLabel(value)}
        onOptionSelect={(_event, data) => { if (data.optionValue != null) onChange(Number(data.optionValue)); }}>
        {options.map((option) => <Option key={option.version} value={String(option.version)}>{option.text}</Option>)}
      </Dropdown>
    </Field>
  );
}
PredictionVersionPicker.propTypes = {
  versions: PropTypes.array.isRequired, value: PropTypes.number.isRequired,
  onChange: PropTypes.func.isRequired, disabled: PropTypes.bool, currentRevision: PropTypes.string, label: PropTypes.string,
};
