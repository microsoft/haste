// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { Text } from "@fluentui/react-components";
import React from "react";
import PropTypes from "prop-types";
import "../../assets/css/progress-bar.css";

const MessageProgressBar = ({ progress, message, stepText }) => {
    MessageProgressBar.propTypes = {
    progress: PropTypes.string.isRequired,
    message: PropTypes.string,
    stepText: PropTypes.string,
  };
  

  return (
    <React.Fragment>
      <div className="message-progress">
        <div className="meter p-0 message-progress-meter">
          <span
            style={{ width: isNaN(progress) ? "0%" : progress + "%" }}
          ></span>
        </div>

        <span className="message-progress-text">
          <Text className="text-light progress-text">
            {isNaN(progress) ? progress : `${message} : ${stepText}`.length > 31 
              ? `${message} : ${stepText}`.substring(0, 31) + '...' 
              : `${message} : ${stepText}`}
          </Text>
        </span>
      </div>
    </React.Fragment>
  );
};

export default MessageProgressBar;
