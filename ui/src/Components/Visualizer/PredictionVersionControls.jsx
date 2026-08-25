// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// The results page's prediction-version control: which saved version the map
// is drawing, how to switch, and how to download the one on screen.
//
// A model's predictions are append-only — the raw model output plus every
// version an analyst saved from edit mode — but until now that history was
// only visible INSIDE edit mode, so a read-only analyst could not tell that
// the map was showing someone's corrections rather than the model's own
// output (or that corrections existed at all). This card says so on every
// visit, in both modes, next to the two actions that follow from it:
// switching versions and downloading the one being shown.
//
// Three things it is careful about:
//
//   • a version whose sidecar has not been backfilled yet is offered as
//     DISABLED with the reason, because selecting it would produce an empty
//     map, not a different one — and when the page lands on one anyway (the
//     server's default can be a version that was saved before its sidecar
//     existed), the card says so and points at the raw output;
//   • version selection moves the MAP only — Assessment and Validation
//     always read the newest saved version — so when the server says the
//     selection is not the newest, that divergence is stated here rather
//     than left to be discovered in a report; and
//   • the download goes through GetModelArtifact (auth, managed identity,
//     Range) like every other artifact on this page, never a blob SAS URL.
//
// All copy and every option comes from predictionVersions.js, which is pure
// and unit-tested; this file is layout.
import PropTypes from "prop-types";
import {
  Button,
  Dropdown,
  MessageBar,
  MessageBarActions,
  MessageBarBody,
  MessageBarTitle,
  Option,
  Spinner,
  Text,
  Tooltip,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
import {
  describeVersionDownload,
  selectedVersionText,
  versionKey,
} from "./predictionVersions";

const useStyles = makeStyles({
  // A card in the results page's top-centre overlay column (see Visualizer's
  // `topStack`), which owns the positioning: this one only has to size itself
  // and take back the pointer events the column gives up.
  root: {
    boxSizing: "border-box",
    width: "100%",
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalXS,
    padding: tokens.spacingHorizontalS,
    borderRadius: tokens.borderRadiusMedium,
    pointerEvents: "auto",
  },
  row: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
  },
  label: {
    color: tokens.colorNeutralForeground2,
    whiteSpace: "nowrap",
  },
  dropdown: {
    flex: 1,
    minWidth: "200px",
  },
  note: {
    width: "100%",
  },
});

const PredictionVersionControls = ({
  options,
  selectedVersion,
  onSelectVersion,
  onDownload,
  isSwitching = false,
  pending = null,
  divergence = null,
  failure = null,
  onDismissFailure,
  disabled = false,
}) => {
  const styles = useStyles();
  if (!Array.isArray(options) || options.length === 0) return null;

  const selectedKey = versionKey(selectedVersion);

  return (
    <div className={`${styles.root} labeling-tool-surface`}>
      <div className={styles.row}>
        <Text size={200} className={styles.label} id="predictionVersionLabel">
          Prediction version
        </Text>
        <Dropdown
          className={styles.dropdown}
          id="predictionVersionSelect"
          aria-labelledby="predictionVersionLabel"
          disabled={disabled || isSwitching}
          selectedOptions={[selectedKey]}
          value={selectedVersionText(options, selectedVersion)}
          onOptionSelect={(_event, data) => {
            if (!data?.optionValue) return;
            onSelectVersion(Number(data.optionValue));
          }}
        >
          {options.map((option) => (
            <Option
              key={option.key}
              value={option.key}
              text={option.text}
              disabled={option.disabled}
            >
              {/* A disabled option cannot explain itself, and "why can't I
                  pick version 2?" is exactly the question it raises — so the
                  reason rides along in a tooltip as well as in the option's
                  own text. The tooltip wraps the label rather than the
                  Option so the Dropdown keeps a plain Option as its child. */}
              {option.disabled ? (
                <Tooltip
                  content={option.disabledReason}
                  relationship="description"
                  withArrow
                >
                  <span>{option.text}</span>
                </Tooltip>
              ) : (
                option.text
              )}
            </Option>
          ))}
        </Dropdown>
        {isSwitching && (
          <Spinner size="tiny" aria-label="Loading the selected version" />
        )}
        <Tooltip
          content={describeVersionDownload(selectedVersion)}
          relationship="label"
        >
          <Button
            appearance="subtle"
            id="predictionVersionDownload"
            icon={<FluentIcon name="download" />}
            disabled={disabled || isSwitching}
            onClick={() => onDownload(selectedVersion)}
          />
        </Tooltip>
      </div>

      {pending && (
        <MessageBar intent="info" className={styles.note}>
          <MessageBarBody>
            <MessageBarTitle>{pending.title}</MessageBarTitle>
            {pending.body}
          </MessageBarBody>
        </MessageBar>
      )}

      {divergence && (
        <MessageBar intent="warning" className={styles.note}>
          <MessageBarBody>
            <MessageBarTitle>{divergence.title}</MessageBarTitle>
            {divergence.body}
          </MessageBarBody>
        </MessageBar>
      )}

      {failure && (
        <MessageBar
          intent="error"
          className={styles.note}
          politeness="assertive"
        >
          <MessageBarBody>
            <MessageBarTitle>{failure.title}</MessageBarTitle>
            {failure.body}
          </MessageBarBody>
          {typeof onDismissFailure === "function" && (
            <MessageBarActions
              containerAction={
                <Button
                  appearance="transparent"
                  aria-label="Dismiss"
                  icon={<FluentIcon name="cancel" />}
                  onClick={onDismissFailure}
                />
              }
            />
          )}
        </MessageBar>
      )}
    </div>
  );
};

PredictionVersionControls.propTypes = {
  options: PropTypes.arrayOf(
    PropTypes.shape({
      key: PropTypes.string.isRequired,
      version: PropTypes.number.isRequired,
      text: PropTypes.string.isRequired,
      disabled: PropTypes.bool,
      disabledReason: PropTypes.string,
    })
  ).isRequired,
  selectedVersion: PropTypes.number,
  onSelectVersion: PropTypes.func.isRequired,
  onDownload: PropTypes.func.isRequired,
  isSwitching: PropTypes.bool,
  pending: PropTypes.shape({
    title: PropTypes.string,
    body: PropTypes.string,
  }),
  divergence: PropTypes.shape({
    title: PropTypes.string,
    body: PropTypes.string,
  }),
  failure: PropTypes.shape({
    title: PropTypes.string,
    body: PropTypes.string,
  }),
  onDismissFailure: PropTypes.func,
  disabled: PropTypes.bool,
};

export default PredictionVersionControls;
