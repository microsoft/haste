// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import PropTypes from "prop-types";
import WorkspaceLoader from "../WorkspaceLoader";

const LOAD_STEPS = [
  "Loading imagery configuration",
  "Finding model artifacts",
  "Loading building tiles",
  "Loading model features",
  "Restoring saved labels",
  "Preparing the map",
];

const InteractiveLabelerLoader = ({ loadState, error, onRetry, onGoBack }) => {
  return (
    <WorkspaceLoader
      eyebrow="Interactive labeler"
      title="Preparing your workspace"
      steps={LOAD_STEPS}
      loadState={loadState}
      error={error}
      errorTitle="Could not load the labeler"
      onRetry={onRetry}
      onGoBack={onGoBack}
    />
  );
};

InteractiveLabelerLoader.propTypes = {
  loadState: PropTypes.shape({
    step: PropTypes.number.isRequired,
    loaded: PropTypes.number,
    total: PropTypes.number,
  }),
  error: PropTypes.string,
  onRetry: PropTypes.func,
  onGoBack: PropTypes.func,
};

export default InteractiveLabelerLoader;