// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { catalogText, hasCatalogCapability } from "./ModelCatalogHelper.js";

export function getLayerInferenceReadiness(layer) {
  if (layer?.workflowType != null && layer.workflowType !== "standard") {
    return { ready: false, detail: "Catalog inference is available for standard image layers only." };
  }
  if (layer?.status !== "Processed" ||
      !(layer.postEventProcessedImageryUrl || layer.postEventMosaicCogImageryUrl)) {
    return { ready: false, detail: "Prepare post-event imagery before running inference." };
  }
  if (!layer.buildingFootprintsUrl) {
    return { ready: false, detail: "Cached building footprints are required for inference." };
  }
  return { ready: true, detail: "Run a catalog model without training labels or fine-tuning." };
}

export function buildInferenceCatalogEndpoint(projectId, imageLayerId) {
  return `GetModelCatalog?${new URLSearchParams({
    capability: "inference", projectId, imageLayerId,
  })}`;
}

export function getCatalogInferenceReadiness(model) {
  const reason = catalogText(model?.inferenceReadiness?.reason, "");
  const detail = catalogText(model?.inferenceReadiness?.detail, "");
  const explanation = [reason, detail].filter(Boolean).join(": ");
  if (!hasCatalogCapability(model, "inference")) {
    return {
      ready: false,
      detail: explanation || "No compatible inference recipe is available.",
    };
  }
  const ready = model.inferenceReady === true && model.inferenceReadiness?.ready !== false;
  return {
    ready,
    detail: ready ? detail || "Compatible with this image layer."
      : explanation || "Inference readiness has not been confirmed for this image layer.",
  };
}

export function isInferenceOnlyModel(model) {
  return model?.modelType === "pretrained";
}

export function getCatalogRunProvenance(model) {
  if (!isInferenceOnlyModel(model)) return null;
  return {
    catalogName: catalogText(model.catalogModelName, "Unknown catalog model"),
    adapter: catalogText(model.pretrainedInference?.adapter, ""),
    requestId: catalogText(model.inferenceRequestId, ""),
  };
}

export function getModelCancellationLabel(model) {
  const active = (status) => status === "Queued" || status === "InProgress";
  if (!isInferenceOnlyModel(model) && active(model?.status)) return "Cancel Training";
  return active(model?.inferenceStatus) ? "Cancel Inference" : null;
}

export async function refreshCatalogInferenceModels(refresh) {
  if (await refresh(false) === false) {
    throw new Error("Unable to refresh model rows.");
  }
}

// One controller per opened dialog. It owns the immutable request snapshot and
// locks synchronously, before React can render a disabled Submit button.
export function createCatalogInferenceSubmission(createId = () => crypto.randomUUID()) {
  let clientRequestId = createId();
  let previousFields = null;
  let pending = false;
  let accepted = null;

  return {
    async submit({ projectId, imageLayerId, baseModelName, name }, put) {
      if (pending) return null;
      if (accepted) return accepted;
      if (!projectId || !imageLayerId || !baseModelName) {
        throw new Error("Choose a compatible catalog model before submitting.");
      }
      // Whitelist browser inputs. Checkpoints, scripts and configuration always
      // come from the authoritative server-side catalog.
      const fields = {
        projectId, imageLayerId, baseModelName,
        ...(name?.trim() ? { name: name.trim() } : {}),
      };
      const identity = JSON.stringify(fields);
      if (previousFields !== null && previousFields !== identity) clientRequestId = createId();
      previousFields = identity;
      pending = true;
      try {
        const response = await put("PutRunCatalogInferenceQueueMessage", { ...fields, clientRequestId });
        // apiPut deliberately retains its legacy numeric-409 behavior.
        if (response === 409) {
          throw new Error("Inference request conflicts with the current layer, catalog, or request identity (409). Check the compatibility details before retrying.");
        }
        if (!response || typeof response.modelId !== "string" || !response.modelId ||
            response.modelType !== "pretrained") {
          throw new Error("The server returned an invalid inference acceptance. Retry unchanged to check the same request safely.");
        }
        accepted = response;
        return response;
      } finally {
        pending = false;
      }
    },
  };
}
