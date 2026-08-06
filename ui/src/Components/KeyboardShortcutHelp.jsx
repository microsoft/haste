// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useState } from "react";
import { ActionButton } from "@fluentui/react";
import PropTypes from "prop-types";

const rootStyle = {
  color: "#605e5c",
  fontSize: 11,
  marginTop: 8,
};

const itemStyle = {
  display: "block",
  height: "auto",
  margin: 0,
  padding: "0 0 8px",
  position: "relative",
  width: "100%",
};

const keysStyle = {
  alignItems: "center",
  display: "flex",
  flexWrap: "wrap",
  gap: 4,
  lineHeight: "20px",
  minHeight: 20,
  position: "relative",
  width: "100%",
};

const keyGroupStyle = {
  alignItems: "center",
  display: "inline-flex",
  gap: 4,
};

const keyStyle = {
  background: "#f3f2f1",
  border: "1px solid #c8c6c4",
  borderRadius: 3,
  color: "#323130",
  display: "inline-block",
  fontFamily: "inherit",
  fontSize: 10,
  fontWeight: 600,
  lineHeight: "16px",
  minWidth: 18,
  padding: "0 4px",
  textAlign: "center",
  whiteSpace: "nowrap",
};

const separatorStyle = {
  color: "#8a8886",
  display: "inline-block",
  lineHeight: "16px",
  whiteSpace: "pre",
};

const descriptionStyle = {
  clear: "both",
  display: "block",
  fontSize: 11,
  height: "auto",
  lineHeight: "16px",
  margin: "3px 0 0",
  overflow: "visible",
  overflowWrap: "break-word",
  position: "relative",
  whiteSpace: "normal",
  width: "100%",
};

const KeyboardShortcutHelp = ({
  shortcuts,
  title = "Keyboard shortcuts",
}) => {
  const [isExpanded, setIsExpanded] = useState(true);

  return (
    <section style={rootStyle} aria-label={title}>
      <ActionButton
        aria-expanded={isExpanded}
        iconProps={{
          iconName: isExpanded ? "ChevronDown" : "ChevronRight",
        }}
        onClick={() => setIsExpanded((expanded) => !expanded)}
        styles={{
          root: {
            color: "#323130",
            fontSize: 11,
            fontWeight: 600,
            height: 24,
            padding: 0,
          },
          icon: { fontSize: 10 },
        }}
      >
        {title}
      </ActionButton>
      {isExpanded && (
        <div role="list">
          {shortcuts.map((shortcut) => (
            <div
              role="listitem"
              style={itemStyle}
              key={`${shortcut.keys.join("-")}-${shortcut.description}`}
            >
              <div style={keysStyle}>
                {shortcut.keys.map((key, index) => (
                  <span style={keyGroupStyle} key={`${key}-${index}`}>
                    {index > 0 && (
                      <span style={separatorStyle}>
                        {shortcut.separator || "/"}
                      </span>
                    )}
                    <kbd style={keyStyle}>{key}</kbd>
                  </span>
                ))}
              </div>
              <div style={descriptionStyle}>{shortcut.description}</div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
};

KeyboardShortcutHelp.propTypes = {
  shortcuts: PropTypes.arrayOf(
    PropTypes.shape({
      keys: PropTypes.arrayOf(PropTypes.string).isRequired,
      separator: PropTypes.string,
      description: PropTypes.string.isRequired,
    })
  ).isRequired,
  title: PropTypes.string,
};

export default KeyboardShortcutHelp;
