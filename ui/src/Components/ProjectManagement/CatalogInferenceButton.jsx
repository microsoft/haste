// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { Button, Tooltip } from "@fluentui/react-components";
import PropTypes from "prop-types";
import CatalogInferenceModal from "../CatalogInferenceModal";
import { getLayerInferenceReadiness } from "../CatalogInferenceHelper";
import { FluentIcon } from "../../util/icons";

export default function CatalogInferenceButton({
  imageLayer, projectId, index, compact = false, setModalComponent, fetchProjectDetails,
}) {
  const readiness = getLayerInferenceReadiness(imageLayer);
  if (imageLayer.workflowType != null && imageLayer.workflowType !== "standard") return null;
  return (
    <Tooltip content={readiness.detail} relationship="description">
      <span>
        <Button id={`singleProjectCatalogInference${index}`}
          appearance={compact ? "subtle" : "secondary"}
          size={compact ? "small" : "medium"}
          className={compact ? "lcard-icon-btn" : "dashboard-button dashboard-button-light"}
          icon={compact ? <FluentIcon name="Forward" /> : undefined}
          aria-label="Inference" disabled={!readiness.ready}
          onClick={() => setModalComponent(
            <CatalogInferenceModal
              onClose={() => setModalComponent(null)} projectId={projectId}
              imageLayer={imageLayer} fetchProjectDetails={fetchProjectDetails}
            />
          )}>
          {!compact && "Inference"}
        </Button>
      </span>
    </Tooltip>
  );
}

CatalogInferenceButton.propTypes = {
  imageLayer: PropTypes.object.isRequired,
  projectId: PropTypes.string.isRequired,
  index: PropTypes.number.isRequired,
  compact: PropTypes.bool,
  setModalComponent: PropTypes.func.isRequired,
  fetchProjectDetails: PropTypes.func.isRequired,
};
