// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useState } from "react";
import { Button, makeStyles, tokens } from "@fluentui/react-components";
import { FluentIcon } from "../util/icons";
import PropTypes from "prop-types";

// Colours come from Fluent tokens so the panel follows the active theme.
// Hardcoded greys here render at ~1.1:1 against the dark surface, which is
// what made this block unreadable in dark mode.
const useStyles = makeStyles({
  root: {
    color: tokens.colorNeutralForeground3,
    fontSize: "11px",
    marginTop: tokens.spacingVerticalS,
  },
  toggle: {
    fontSize: "11px",
    fontWeight: tokens.fontWeightSemibold,
    height: "24px",
    minWidth: 0,
    padding: 0,
  },
  item: {
    display: "block",
    height: "auto",
    margin: 0,
    padding: `0 0 ${tokens.spacingVerticalS}`,
    position: "relative",
    width: "100%",
  },
  keys: {
    alignItems: "center",
    display: "flex",
    flexWrap: "wrap",
    gap: tokens.spacingHorizontalXS,
    lineHeight: "20px",
    minHeight: "20px",
    position: "relative",
    width: "100%",
  },
  keyGroup: {
    alignItems: "center",
    display: "inline-flex",
    gap: tokens.spacingHorizontalXS,
  },
  key: {
    backgroundColor: tokens.colorNeutralBackground3,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke1}`,
    borderRadius: tokens.borderRadiusSmall,
    color: tokens.colorNeutralForeground1,
    display: "inline-block",
    fontFamily: "inherit",
    fontSize: tokens.fontSizeBase100,
    fontWeight: tokens.fontWeightSemibold,
    lineHeight: "16px",
    minWidth: "18px",
    padding: `0 ${tokens.spacingHorizontalXS}`,
    textAlign: "center",
    whiteSpace: "nowrap",
  },
  separator: {
    color: tokens.colorNeutralForeground3,
    display: "inline-block",
    lineHeight: "16px",
    whiteSpace: "pre",
  },
  description: {
    clear: "both",
    display: "block",
    fontSize: "11px",
    height: "auto",
    lineHeight: "16px",
    margin: "3px 0 0",
    overflow: "visible",
    overflowWrap: "break-word",
    position: "relative",
    whiteSpace: "normal",
    width: "100%",
  },
});

const KeyboardShortcutHelp = ({
  shortcuts,
  title = "Keyboard shortcuts",
}) => {
  const styles = useStyles();
  const [isExpanded, setIsExpanded] = useState(true);

  return (
    <section className={styles.root} aria-label={title}>
      <Button
        appearance="subtle"
        aria-expanded={isExpanded}
        icon={
          <FluentIcon
            name={isExpanded ? "ChevronDown" : "ChevronRight"}
          />
        }
        onClick={() => setIsExpanded((expanded) => !expanded)}
        size="small"
        className={styles.toggle}
      >
        {title}
      </Button>
      {isExpanded && (
        <div role="list">
          {shortcuts.map((shortcut) => (
            <div
              role="listitem"
              className={styles.item}
              key={`${shortcut.keys.join("-")}-${shortcut.description}`}
            >
              <div className={styles.keys}>
                {shortcut.keys.map((key, index) => (
                  <span className={styles.keyGroup} key={`${key}-${index}`}>
                    {index > 0 && (
                      <span className={styles.separator}>
                        {shortcut.separator || "/"}
                      </span>
                    )}
                    <kbd className={styles.key}>{key}</kbd>
                  </span>
                ))}
              </div>
              <div className={styles.description}>{shortcut.description}</div>
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
