// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { Text } from "@fluentui/react";
import React from "react";
import PropTypes from "prop-types";
import "../../assets/css/progress-bar.css";

const ProgressBar = ({ progress }) => {
  ProgressBar.propTypes = {
    progress: PropTypes.string.isRequired,
  };

  

  return (
    <React.Fragment>
      <div>
        <span
          style={{
            position: "absolute",
            width: "150px",
            zIndex: "1",
            textAlign: "center",
            color: "black",
          }}
        >
          <Text variant="medium" className="text-light">
            {isNaN(progress) ? progress : `${progress}%`}
          </Text>
        </span>

        <div
          className="meter p-0"
          style={{
            width: "150px",
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

export default ProgressBar;
