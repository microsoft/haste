// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useEffect, useRef } from "react";
import {
  OverlayDrawer,
  DrawerHeader,
  DrawerHeaderTitle,
  DrawerBody,
  Button,
  tokens,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
import { useDrawerAnimation } from "../../util/useDrawerAnimation";
import proptypes from "prop-types";

const StatusIndicatorModal = ({
  statusMessages,
  infoMetadata,
  contextLabel,
  onClose,
}) => {
  const modalBodyRef = useRef(null);
  const { open, requestClose } = useDrawerAnimation(onClose);

  StatusIndicatorModal.propTypes = {
    statusMessages: proptypes.array.isRequired,
    // Optional run-parameter rows rendered above the status-message table.
    // Each item is {label, value}; consumers (e.g. EmbeddingModelRow) build
    // this from the saved Model record.
    infoMetadata: proptypes.arrayOf(
      proptypes.shape({
        label: proptypes.string.isRequired,
        value: proptypes.node.isRequired,
      })
    ),
    // Optional label identifying the element these messages belong to
    // (e.g. "Image Layer: Pre-event" or "Model: Damage v2"). Shown as a
    // subtitle under the panel title so users know what they're viewing.
    contextLabel: proptypes.string,
    onClose: proptypes.func.isRequired,
  };

  // Scroll to the bottom when statusMessages updates
  useEffect(() => {
    if (modalBodyRef.current) {
      modalBodyRef.current.scrollTop = modalBodyRef.current.scrollHeight;
    }
  }, [statusMessages]);

  if (statusMessages.length === 0 && (!infoMetadata || infoMetadata.length === 0)) {
    return null;
  }

  return (
    <OverlayDrawer
      position="end"
      open={open}
      onOpenChange={(_, d) => {
        if (!d.open) requestClose();
      }}
      className="section-panel-drawer"
      style={{ "--fui-Drawer--size": "560px", maxWidth: "95vw" }}
    >
      <DrawerHeader className="section-panel-header">
        <DrawerHeaderTitle
          action={
            <Button
              appearance="subtle"
              icon={<FluentIcon name="Cancel" />}
              aria-label="Close status messages panel"
              onClick={requestClose}
            />
          }
        >
          <span className="section-panel-title">
            <FluentIcon name="Info" className="modal-icon" />
            Status Messages
          </span>
          {contextLabel && (
            <div
              className="section-panel-subtitle"
              style={{
                fontSize: "0.85em",
                fontWeight: 400,
                color: tokens.colorNeutralForeground3,
                marginTop: "2px",
              }}
            >
              {contextLabel}
            </div>
          )}
        </DrawerHeaderTitle>
      </DrawerHeader>
      <DrawerBody ref={modalBodyRef}>
        {infoMetadata && infoMetadata.length > 0 && (
          <div className="mb-3">
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <tbody>
                {infoMetadata.map((item, index) => (
                  <tr key={`meta-${index}`}>
                    <td
                      style={{
                        whiteSpace: "nowrap",
                        verticalAlign: "top",
                        padding: "6px 16px 6px 0",
                        fontWeight: 600,
                      }}
                    >
                      {item.label}
                    </td>
                    <td style={{ verticalAlign: "top", padding: "6px 0" }}>
                      {item.value}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="mb-2">
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr key="header">
                <td
                  style={{
                    whiteSpace: "nowrap",
                    verticalAlign: "top",
                    padding: "6px 16px 6px 0",
                    fontWeight: 600,
                  }}
                >
                  Timestamp
                </td>
                <td
                  style={{
                    verticalAlign: "top",
                    padding: "6px 0",
                    fontWeight: 600,
                  }}
                >
                  Message
                </td>
              </tr>
            </thead>
            <tbody>
              {statusMessages
                .filter(
                  (message) =>
                    (message.timestamp && message.timestamp.trim()) ||
                    (message.message && message.message.trim())
                )
                .map((message, index) => {
                  return (
                    <tr key={index}>
                      <td
                        style={{
                          whiteSpace: "nowrap",
                          verticalAlign: "top",
                          padding: "6px 16px 6px 0",
                          borderTop: `1px solid ${tokens.colorNeutralStroke2}`,
                        }}
                      >
                        {message.timestamp}
                      </td>
                      <td
                        style={{
                          verticalAlign: "top",
                          padding: "6px 0",
                          borderTop: `1px solid ${tokens.colorNeutralStroke2}`,
                        }}
                      >
                        {message.message}
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      </DrawerBody>
    </OverlayDrawer>
  );
};

export default StatusIndicatorModal;
