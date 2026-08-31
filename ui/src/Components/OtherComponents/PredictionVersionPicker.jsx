// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Which of a model's saved predictions to read.
//
// A model's predictions are append-only: the raw model output plus a version
// for every set of edits an analyst saved. Reports and downloads used to take
// whatever the server picked, which meant a report could quietly describe
// different data than the file next to it. This control makes the choice
// explicit wherever predictions are read.
//
// It renders nothing when there is only the raw output, so a model nobody has
// edited looks exactly as it did before.
import PropTypes from "prop-types";
import { Dropdown, Field, Option } from "@fluentui/react-components";
import {
  predictionSourceOptions,
  versionLabel,
} from "../Visualizer/predictionVersions";

const PredictionVersionPicker = ({
  versions,
  value,
  onChange,
  label = "Predictions",
  disabled = false,
}) => {
  const options = predictionSourceOptions(versions);
  if (options.length < 2) return null;

  const selected = options.find((option) => option.version === value);

  return (
    <Field label={label}>
      <Dropdown
        disabled={disabled}
        selectedOptions={[String(value)]}
        value={selected ? selected.text : versionLabel(value)}
        onOptionSelect={(_event, data) => {
          if (data.optionValue == null) return;
          onChange(Number(data.optionValue));
        }}
      >
        {options.map((option) => (
          <Option key={option.key} value={String(option.version)}>
            {option.text}
          </Option>
        ))}
      </Dropdown>
    </Field>
  );
};

PredictionVersionPicker.propTypes = {
  versions: PropTypes.array,
  value: PropTypes.number.isRequired,
  onChange: PropTypes.func.isRequired,
  label: PropTypes.string,
  disabled: PropTypes.bool,
};

export default PredictionVersionPicker;
