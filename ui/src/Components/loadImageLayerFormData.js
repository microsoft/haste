export async function loadImageLayerFormData(imageLayerId, projectId, get) {
  const [imageLayerToEdit, project] = await Promise.all([
    imageLayerId
      ? get(
          `GetLayerDetailView?projectId=${projectId}` +
            `&imageLayerId=${imageLayerId}`
        )
      : Promise.resolve(null),
    get(`GetProjectDetails?projectId=${projectId}`),
  ]);
  return { imageLayerToEdit, project };
}