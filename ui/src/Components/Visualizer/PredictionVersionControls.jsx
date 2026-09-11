// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// PR136's top-centre version card. Missing sidecars are unavailable, not queued.
import PropTypes from "prop-types";
import { Button, Dropdown, Option, Spinner, Text, Tooltip, makeStyles, tokens } from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
import { predictionSourceOptions, versionLabel } from "./predictionVersions.js";

const useStyles = makeStyles({
  root: {
    width: "100%", boxSizing: "border-box", padding: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalS}`,
    borderRadius: tokens.borderRadiusMedium, pointerEvents: "auto",
    display: "flex", alignItems: "center", gap: tokens.spacingHorizontalS, flexWrap: "wrap",
  },
  dropdown: { flex: 1, minWidth: "160px" },
});
export default function PredictionVersionControls({ versions, source, onSelectVersion, onDownload, disabled, loading, editing }) {
  const styles = useStyles();
  const version = source.predictionVersion ?? 0;
  const options = predictionSourceOptions(versions, source.currentPredictionRevision ?? source.predictionRevision, true);
  if (options.length < 2 && version === 0) return null;
  return (
    <div className={`${styles.root} labeling-tool-surface`}>
      <Text id="predictionVersionLabel" size={200}>Prediction version</Text>
      <Dropdown id="predictionVersionSelect" aria-labelledby="predictionVersionLabel" className={styles.dropdown}
        selectedOptions={[String(version)]} value={loading ? "Loading selected version…" : `${versionLabel(version)}${editing ? " · edit preview" : ""}`}
        disabled={disabled} onOptionSelect={(_event, data) => { if (data.optionValue != null) onSelectVersion(Number(data.optionValue)); }}>
        {options.map((option) => (
          <Option key={option.version} value={String(option.version)} text={option.text} disabled={option.disabled}>
            {option.disabled ? <Tooltip content={option.reason} relationship="description"><span>{option.text} · unavailable</span></Tooltip> : option.text}
          </Option>
        ))}
      </Dropdown>
      {loading && <Spinner size="tiny" aria-label="Loading the selected version" />}
      <Tooltip content={`Download ${versionLabel(version).toLowerCase()}${editing ? " — save your preview first to include its changes" : ""}`} relationship="label">
        <Button id="predictionVersionDownload" appearance="subtle" icon={<FluentIcon name="download" />}
          disabled={disabled} onClick={() => onDownload(version, source.predictionRevision)} />
      </Tooltip>
    </div>
  );
}
PredictionVersionControls.propTypes = {
  versions: PropTypes.array.isRequired, source: PropTypes.object.isRequired,
  onSelectVersion: PropTypes.func.isRequired, onDownload: PropTypes.func.isRequired,
  disabled: PropTypes.bool, loading: PropTypes.bool,
  editing: PropTypes.bool,
};
