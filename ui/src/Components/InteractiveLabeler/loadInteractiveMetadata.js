export async function loadInteractiveMetadata({
  get,
  projectId,
  imageLayerId,
  modelId,
  signal,
}) {
  const options = { signal };
  const [layerResult, modelsResult, labelsResult] = await Promise.allSettled([
    get(
      `GetLayerLabelingToolData?projectId=${projectId}` +
        `&imageLayerId=${imageLayerId}`,
      options
    ),
    get(
      `GetLayerModelsDetails?projectId=${projectId}` +
        `&imageLayerId=${imageLayerId}`,
      options
    ),
    get(
      `GetInteractiveLabels?projectId=${projectId}&modelId=${modelId}`,
      options
    ),
  ]);

  if (modelsResult.status === "rejected") throw modelsResult.reason;
  const model = (modelsResult.value || []).find(
    (candidate) => String(candidate.modelId) === String(modelId)
  );

  return {
    layerData: layerResult.status === "fulfilled" ? layerResult.value : null,
    layerError: layerResult.status === "rejected" ? layerResult.reason : null,
    model,
    savedLabels:
      labelsResult.status === "fulfilled"
        ? labelsResult.value?.labels || {}
        : {},
    savedLabelsLoaded: labelsResult.status === "fulfilled",
    savedLabelsError:
      labelsResult.status === "rejected" ? labelsResult.reason : null,
  };
}