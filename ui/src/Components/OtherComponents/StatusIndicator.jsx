// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import React, { useEffect, useState } from "react";
import MessageProgressBar from "../OtherComponents/MessageProgressBar";
import StatusIndicatorModal from "./StatusIndicatorModal";
import { validateTimestamp } from "../../util/validation";

import PropTypes from "prop-types";
import { IconButton } from "@fluentui/react";

const StatusIndicator = ({ currentStep, totalSteps, progressPct, status, statusMessage, id, prefix = "Status" }) => {
  StatusIndicator.propTypes = {
    currentStep: PropTypes.number.isRequired,
    totalSteps: PropTypes.number.isRequired,
    progressPct: PropTypes.number.isRequired,
    status: PropTypes.string.isRequired,
    statusMessage: PropTypes.string.isRequired,
    id: PropTypes.string,
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


  const getLastMessageWithTimestamp = () => {
    for (let i = statusMessageList.length - 1; i >= 0; i--) {
      if (statusMessageList[i].timestamp) {
        return statusMessageList[i].message;
      }
    }
    return "";
  }


  // If is an old project, will only show the status message
  if(currentStep===undefined || totalSteps===undefined || progressPct===undefined) {
    return (
      <div className={`modelStatus modelStatus-${status}`}>
      <span className="fw-semibold"></span>
      {prefix}: {status}
    </div>
    );
  }
  

  return (
    <React.Fragment>
      {statusMessageList.length > 0 && (
        <div className="d-flex flex-row align-items-center">
          {status === "Processed" || status === "Failed"  || status === "Cancelled" ? (
            <div className={`modelStatus modelStatus-${status}`}>
              <span className="fw-semibold"></span>
              {status === "Cancelled" ? getLastMessageWithTimestamp(statusMessageList[0]) : `${prefix}: ${status}`}
            </div>
          ) : (
            <MessageProgressBar
              progress={progressPct.toString()}
              message={getLastMessageWithTimestamp(statusMessageList[0])}
              stepText={currentStep + "/" + totalSteps}
            />
          )}

          <IconButton
            id={id}
            iconProps={{ iconName: "Info" }}
            title="Show status messages"
            ariaLabel="Show status messages"
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
          onClose={() => {
            setIsModalVisible(false);
          }}
        />
      )}

    </React.Fragment>
  );
};

export default StatusIndicator;
