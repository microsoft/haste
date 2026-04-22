// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import React, { useEffect, useRef } from "react";
import SectionModal from "../SectionModal";
import proptypes from "prop-types";

const StatusIndicatorModal = ({ statusMessages, onClose }) => {
  const modalBodyRef = useRef(null);

  StatusIndicatorModal.propTypes = {
    statusMessages: proptypes.array.isRequired,
    onClose: proptypes.func.isRequired,
  };

  // Scroll to the bottom when statusMessages updates
  useEffect(() => {
    if (modalBodyRef.current) {
      modalBodyRef.current.scrollTop = modalBodyRef.current.scrollHeight;
    }
  }, [statusMessages]);

  if (statusMessages.length === 0) {
    return null;
  }

  return (
    <SectionModal
      title={"Status Messages"}
      body={
        <>
          <div
            className="row mb-2"
            style={{ maxHeight: "300px", overflowY: "auto" }}
            ref={modalBodyRef}
          >
            <div className="col-12 d-flex flex-column">
              <table>
                <thead>
                  <tr key="header">
                    <td>
                      <b>Timestamp</b>
                    </td>
                    <td>
                      <b>Message</b>
                    </td>
                  </tr>
                </thead>
                <tbody>
                  {statusMessages.map((message, index) => {
                    return (
                      <tr key={index}>
                        <td className="pe-3">{message.timestamp}</td>
                        <td>{message.message}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      }
      onClose={onClose}
      icon="Info"
    />
  );
};

export default StatusIndicatorModal;
