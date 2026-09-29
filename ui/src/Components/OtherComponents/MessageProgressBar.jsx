// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { Text } from "@fluentui/react-components";
import React from "react";
import PropTypes from "prop-types";
import "../../assets/css/progress-bar.css";
import { progressBarPresentation } from "./StatusIndicatorHelper";

const MessageProgressBar = ({ progress, message = "", stepText = "", indeterminate = false }) => {
  const { value, label, attributes } = progressBarPresentation({ progress, message, stepText, indeterminate });

  return (
    <React.Fragment>
      <div className="message-progress">
        <div
          className={`meter p-0 message-progress-meter${indeterminate ? " message-progress-indeterminate" : ""}`}
          {...attributes}
        >
          <span
            style={indeterminate ? undefined : { width: `${value ?? 0}%` }}
          ></span>
        </div>

        <span className="message-progress-text">
          <Text className="text-light progress-text" title={label}>
            {label}
          </Text>
        </span>
      </div>
    </React.Fragment>
  );
};

MessageProgressBar.propTypes = {
  progress: PropTypes.string,
  message: PropTypes.string,
  stepText: PropTypes.string,
  indeterminate: PropTypes.bool,
};

export default MessageProgressBar;
