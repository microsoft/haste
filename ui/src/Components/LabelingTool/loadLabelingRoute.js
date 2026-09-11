export function loadLabelingRoute({
  importRoute,
  loadMaps,
  get,
  projectId,
  imageLayerId,
  signal,
}) {
  const query = new URLSearchParams({ projectId, imageLayerId });
  return Promise.all([
    importRoute(),
    loadMaps(),
    get(`GetLabelingWorkspace?${query}`, { signal }),
  ]).then(([route, , workspace]) => ({
    Component: route.default,
    workspace,
  }));
}
