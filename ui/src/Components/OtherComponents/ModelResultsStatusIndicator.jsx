// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import React, { useEffect, useState } from "react";
import StatusIndicatorModal from "./StatusIndicatorModal";
import { validateTimestamp } from "../../util/validation";

import PropTypes from "prop-types";
import { Button } from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";

const ModelResultsStatusIndicator = ({ statusMessage, contextLabel }) => {
  ModelResultsStatusIndicator.propTypes = {
    statusMessage: PropTypes.string.isRequired,
    // Optional label identifying the model these result messages belong to.
    contextLabel: PropTypes.string,
  };
  
  const [statusMessageList, setStatusMessageList] = React.useState([]);

  const labelsToReplace = [
    { original: "trainStartTime:", replacement: "Training start time:" },
    { original: "epoch:", replacement: "Epoch: " },
    { original: "elapsedDurationInMinutes:", replacement: "Minutes Elapsed:" },
    { original: "approxMinutesToComplete:", replacement: "Aprox. minutes to complete: " },
    { original: "completedDate:", replacement: "Completed date:" }
  ];

  const [isModalVisible, setIsModalVisible] = useState(false);

  useEffect(() => {
    if (statusMessage) {

      var tempStatusMessages = statusMessage;

      labelsToReplace.forEach(label => {
        tempStatusMessages = tempStatusMessages.replace(new RegExp(label.original, 'g'), label.replacement);
      });
      
      tempStatusMessages = tempStatusMessages.split("\n");
      var newStatusMessages = [];
      if (tempStatusMessages.length > 0) {
        for (let i = 0; i < tempStatusMessages.length; i++) {
          if (validateTimestamp(tempStatusMessages[i])) {
            newStatusMessages.push({
              message: tempStatusMessages[i].substring(33),
              timestamp:
                tempStatusMessages[i].substring(0, 10) +
                ", " +
                tempStatusMessages[i].substring(11, 19) +
                " UTC",
            });
          } else {
            newStatusMessages.push({
              message: tempStatusMessages[i],
              timestamp: "",
            });
          }
        }
        setStatusMessageList(newStatusMessages);
      } else {
        setStatusMessageList([]);
      }
    }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusMessage]);




  return (
    <React.Fragment>
      {statusMessageList.length > 0 && (
        <div className="d-flex flex-row align-items-center">
          <Button
            appearance="subtle"
            icon={<FluentIcon name="Info" />}
            title="Show status messages"
            aria-label="Show status messages"
            className="ms-1"
            onClick={() => {
              setIsModalVisible(true);
            }}
          />
        </div>
      )}


      {isModalVisible && (
        <StatusIndicatorModal
          statusMessages={statusMessageList}
          contextLabel={contextLabel}
          onClose={() => {
            setIsModalVisible(false);
          }}
        />
      )}

    </React.Fragment>
  );
};

export default ModelResultsStatusIndicator;
