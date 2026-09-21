export async function loadValidationMapData({
  get,
  projectId,
  imageLayerId,
  resolveSampleSize,
}) {
  const query = `projectId=${projectId}&imageLayerId=${imageLayerId}`;
  const layerPromise = get(`GetLayerLabelingToolData?${query}`).catch(
    () => null
  );
  const validationData = await get(`GetBuildingValidation?${query}`);
  const sampleSize = resolveSampleSize(validationData);
  const [layerData, footprintsGeoJSON] = await Promise.all([
    layerPromise,
    get(`GetBuildingFootprintsGeoJSON?${query}&sample=${sampleSize}`),
  ]);

  return {
    layerData,
    validationData,
    footprintsGeoJSON,
    sampleSize,
  };
}