// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { Text } from "@fluentui/react-components";
import React from "react";
import PropTypes from "prop-types";
import "../../assets/css/progress-bar.css";

const MessageProgressBar = ({ progress, message = "", stepText = "", indeterminate = false }) => {
  const numeric = typeof progress === "string" && progress.trim() !== "" && Number.isFinite(Number(progress));
  const value = numeric ? Math.min(100, Math.max(0, Number(progress))) : undefined;
  const label = !indeterminate && !numeric && progress
    ? progress
    : [message, stepText].filter(Boolean).join(" : ");

  return (
    <React.Fragment>
      <div className="message-progress">
        <div
          className={`meter p-0 message-progress-meter${indeterminate ? " message-progress-indeterminate" : ""}`}
          role="progressbar"
          aria-label={message || "Job progress"}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={indeterminate ? undefined : value}
          aria-valuetext={label}
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
