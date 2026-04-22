// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { Text } from "@fluentui/react";
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
      <div>
        <span
          style={{
            position: "absolute",
            minWidth: "250px",
            zIndex: "1",
            textAlign: "center",
            color: "black",
          }}
        >
          <Text variant="medium" className="text-light progress-text">
            {isNaN(progress) ? progress : `${message} : ${stepText}`.length > 31 
              ? `${message} : ${stepText}`.substring(0, 31) + '...' 
              : `${message} : ${stepText}`}
          </Text>
        </span>

        <div
          className="meter p-0"
          style={{
            minWidth: "250px",
            position: "relative",
            borderRadius: "5px",
          }}
        >
          <span
            style={{ width: isNaN(progress) ? "0%" : progress + "%", position: "absolute", top: "0px" }}
          ></span>
        </div>
      </div>
    </React.Fragment>
  );
};

export default MessageProgressBar;
