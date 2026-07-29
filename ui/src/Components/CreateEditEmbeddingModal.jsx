// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Modal to customize and launch a building-embedding job (building labeling
// workflow). Mirrors CreateEditModelTrainingModal — collects the embedding
// backbone + per-backbone parameters and POSTs to PutRunEmbeddingQueueMessage.
import { useContext, useMemo, useState } from "react";
import {
  Dropdown,
  Option,
  Field,
  Input,
  Button,
} from "@fluentui/react-components";
import proptypes from "prop-types";

import { apiPut } from "../util/api";
import { validateInt } from "../util/validation";
import { AppContext } from "../AppContext";
import SectionModal from "./SectionModal";

// Keep this list in sync with build_embedding_model() in
// hastelib/src/hastegeo/workflows/embed_buildings.py — the backend rejects
// anything not on its supported list.
const EMBEDDING_MODEL_OPTIONS = [
  {
    key: "mosaiks",
    text: "MOSAIKS (random conv features)",
    description:
      "Fast, untrained random convolution features. Output dim is configurable.",
  },
  {
    key: "dinov2_vits14",
    text: "DINOv2 ViT-S/14 (384-dim)",
    description:
      "Self-supervised ViT trained by Meta — strong general-purpose visual features. ~22M params, 384-dim output.",
  },
  {
    key: "dinov2_vitb14",
    text: "DINOv2 ViT-B/14 (768-dim)",
    description:
      "Larger DINOv2 variant. ~86M params, 768-dim output — slower but often more discriminative than ViT-S.",
  },
];

const CreateEditEmbeddingModal = ({
  onClose,
  projectId,
  imageLayer,
  fetchProjectDetails,
}) => {
  CreateEditEmbeddingModal.propTypes = {
    onClose: proptypes.func.isRequired,
    projectId: proptypes.string.isRequired,
    imageLayer: proptypes.object.isRequired,
    fetchProjectDetails: proptypes.func,
  };

  const { setDialog, appParams, setIsLoading } = useContext(AppContext);
  const [state, setState] = useState({
    name: "embedding-" + Date.now(),
    nameError: "",
    embeddingModel: "mosaiks",
    numFeatures: "1024",
    numFeaturesError: "",
    resizeFactor: "4",
    resizeFactorError: "",
    batchSize: "16",
    batchSizeError: "",
  });

  const isMosaiks = state.embeddingModel === "mosaiks";
  const modelHelp = useMemo(
    () =>
      EMBEDDING_MODEL_OPTIONS.find((o) => o.key === state.embeddingModel)
        ?.description || "",
    [state.embeddingModel]
  );

  function onField(value, key) {
    setState((s) => ({ ...s, [key]: value }));
  }

  function onModelChange(_e, data) {
    const key = data.optionValue;
    if (!key) return;
    // Switching to DINOv2 picks per-backbone defaults that match what the
    // server-side preprocessor would fill in (resizeFactor=1, no num_feats).
    setState((s) => {
      if (key === "mosaiks") {
        return {
          ...s,
          embeddingModel: "mosaiks",
          resizeFactor: s.resizeFactor || "4",
          numFeatures: s.numFeatures || "1024",
        };
      }
      return {
        ...s,
        embeddingModel: key,
        resizeFactor: "1",
      };
    });
  }

  async function submit() {
    const resizeFactorError = validateInt("Resize factor", state.resizeFactor);
    const batchSizeError = validateInt("Batch size", state.batchSize);
    const numFeaturesError = isMosaiks
      ? validateInt("Number of features", state.numFeatures)
      : "";
    if (numFeaturesError || resizeFactorError || batchSizeError) {
      setState((s) => ({
        ...s,
        numFeaturesError,
        resizeFactorError,
        batchSizeError,
      }));
      return;
    }

    setIsLoading(true, "Starting embedding job...");
    try {
      const body = {
        projectId,
        imageLayerId: imageLayer.imageLayerId,
        modelType: "embedding",
        name: state.name,
        embeddingModel: state.embeddingModel,
        resizeFactor: parseInt(state.resizeFactor, 10),
        batchSize: state.batchSize,
        userId: appParams.userId,
      };
      // num_feats is MOSAIKS-only. DINOv2 variants have a fixed output dim
      // determined by the variant — sending a value would be misleading
      // since the workflow ignores it.
      if (isMosaiks) {
        body.numFeatures = parseInt(state.numFeatures, 10);
      }
      await apiPut("PutRunEmbeddingQueueMessage", body);
      onClose();
      if (fetchProjectDetails) fetchProjectDetails();
      setDialog("Success", "Embedding job started.", [
        {
          type: "primary",
          key: "close",
          text: "Close",
          onClick: () => setDialog(),
        },
      ]);
    } catch (error) {
      console.error("Error starting embedding job:", error);
      setDialog("Error", "Failed to start the embedding job.");
    }
    setIsLoading(false);
  }

  return (
    <SectionModal
      title="New Embedding"
      icon="OpenFolderHorizontal"
      onClose={onClose}
      body={
        <>
          <div className="row mb-2">
            <div className="col-12">
              <Field label="Name" validationMessage={state.nameError}>
                <Input
                  id="createEmbeddingName"
                  value={state.name}
                  onChange={(e, data) => onField(data.value, "name")}
                />
              </Field>
            </div>
          </div>
          <div className="row mb-2">
            <div className="col-12">
              <Field label="Embedding model">
                <Dropdown
                  id="createEmbeddingModel"
                  selectedOptions={[String(state.embeddingModel)]}
                  value={
                    EMBEDDING_MODEL_OPTIONS.find(
                      (o) => o.key === state.embeddingModel
                    )?.text || ""
                  }
                  onOptionSelect={onModelChange}
                >
                  {EMBEDDING_MODEL_OPTIONS.map((o) => (
                    <Option key={o.key} value={o.key}>
                      {o.text}
                    </Option>
                  ))}
                </Dropdown>
              </Field>
              <p style={{ fontSize: 12, color: "#666", margin: "8px 0" }}>
                {modelHelp}
              </p>
            </div>
          </div>
          <div className="row mb-4">
            <div className="col-12 flex-column flex-md-row d-flex">
              {isMosaiks && (
                <Field
                  label="Number of features"
                  className="me-0 me-md-4 mb-2"
                  required
                  validationMessage={state.numFeaturesError}
                >
                  <Input
                    id="createEmbeddingNumFeatures"
                    value={state.numFeatures}
                    onChange={(e, data) => onField(data.value, "numFeatures")}
                  />
                </Field>
              )}
              <Field
                label="Resize factor"
                className="me-0 me-md-4 mb-2"
                required
                validationMessage={state.resizeFactorError}
              >
                <Input
                  id="createEmbeddingResizeFactor"
                  value={state.resizeFactor}
                  onChange={(e, data) => onField(data.value, "resizeFactor")}
                />
              </Field>
              <Field
                label="Batch size"
                className="mb-2"
                required
                validationMessage={state.batchSizeError}
              >
                <Input
                  id="createEmbeddingBatchSize"
                  value={state.batchSize}
                  onChange={(e, data) => onField(data.value, "batchSize")}
                />
              </Field>
            </div>
          </div>
          <div className="row">
            <div className="col-12 d-flex justify-content-end">
              <Button
                appearance="primary"
                className="me-2"
                onClick={submit}
                id="createEmbeddingSubmit"
              >
                Embed
              </Button>
              <Button onClick={onClose}>Cancel</Button>
            </div>
          </div>
        </>
      }
    />
  );
};

export default CreateEditEmbeddingModal;
