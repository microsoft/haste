// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import React, { useMemo, useState } from "react";
import MessageProgressBar from "../OtherComponents/MessageProgressBar";
import StatusIndicatorModal from "./StatusIndicatorModal";
import { validateTimestamp } from "../../util/validation";

import PropTypes from "prop-types";
import { Button } from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
import { statusPresentation } from "./StatusIndicatorHelper";

const labelsToReplace = [
    { original: "trainStartTime:", replacement: "Training start time:" },
    { original: "epoch:", replacement: "Epoch: " },
    { original: "elapsedDurationInMinutes:", replacement: "Minutes Elapsed:" },
    { original: "approxMinutesToComplete:", replacement: "Aprox. minutes to complete: " },
    { original: "completedDate:", replacement: "Completed date:" }
];

const StatusIndicator = ({ currentStep, totalSteps, progressPct, status, statusMessage, id, prefix = "Status", infoMetadata, contextLabel }) => {
  const [isModalVisible, setIsModalVisible] = useState(false);
  const statusMessageList = useMemo(() => {
    if (!statusMessage) return [];
    let formatted = statusMessage;
    labelsToReplace.forEach(label => {
      formatted = formatted.replace(new RegExp(label.original, "g"), label.replacement);
    });
    return formatted.split("\n").map(line => validateTimestamp(line)
      ? {
          message: line.substring(33),
          timestamp: `${line.substring(0, 10)}, ${line.substring(11, 19)} UTC`,
        }
      : { message: line, timestamp: "" }
    );
  }, [statusMessage]);


  const getLastMessageWithTimestamp = () => {
    for (let i = statusMessageList.length - 1; i >= 0; i--) {
      if (statusMessageList[i].timestamp) {
        return statusMessageList[i].message;
      }
    }
    return "";
  }


  const presentation = statusPresentation({ status, currentStep, totalSteps, progressPct });
  const hasDetails = statusMessageList.length > 0 || Boolean(infoMetadata?.length);
  

  return (
    <React.Fragment>
        <div className="d-flex flex-row align-items-center">
          {!presentation.active ? (
            <div className={`modelStatus modelStatus-${presentation.label}`}>
              <span className="fw-semibold"></span>
              {`${prefix}: ${presentation.label}`}
            </div>
          ) : (
            <MessageProgressBar
              progress={presentation.progress?.toString()}
              indeterminate={presentation.indeterminate}
              message={getLastMessageWithTimestamp() || presentation.label}
              stepText={presentation.stepText}
            />
          )}

          {hasDetails && <Button
            id={id}
            appearance="subtle"
            icon={<FluentIcon name="Info" />}
            title="Show status messages"
            aria-label="Show status messages"
            className="ms-1"
            onClick={() => {
              setIsModalVisible(true);
            }}
          />}
        </div>


      {isModalVisible && (
        <StatusIndicatorModal
          statusMessages={statusMessageList}
          infoMetadata={infoMetadata}
          contextLabel={contextLabel}
          onClose={() => {
            setIsModalVisible(false);
          }}
        />
      )}

    </React.Fragment>
  );
};

StatusIndicator.propTypes = {
  currentStep: PropTypes.number,
  totalSteps: PropTypes.number,
  progressPct: PropTypes.number,
  status: PropTypes.string,
  statusMessage: PropTypes.string,
  id: PropTypes.string,
  prefix: PropTypes.string,
  infoMetadata: PropTypes.arrayOf(
    PropTypes.shape({
      label: PropTypes.string.isRequired,
      value: PropTypes.node.isRequired,
    })
  ),
  contextLabel: PropTypes.string,
};

export default StatusIndicator;
