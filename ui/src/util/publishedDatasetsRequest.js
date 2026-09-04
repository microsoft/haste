export function buildPublishedDatasetsEndpoint({
  currentPage,
  pageSize,
  sort,
  targetFilter,
  statusFilter,
  searchText,
}) {
  const query = new URLSearchParams({
    page: String(currentPage),
    pageSize: String(pageSize),
    sortKey: sort.key,
    sortDirection: sort.dir,
  });
  if (targetFilter !== "all") query.set("target", targetFilter);
  if (statusFilter !== "all") query.set("status", statusFilter);
  if (searchText) query.set("search", searchText);
  return `GetPublishedDatasets?${query}`;
}

export function shouldPollPublishedDatasets({
  hasActiveItems,
  searchReady,
  visibilityState,
  requestRunning,
}) {
  return (
    hasActiveItems &&
    searchReady &&
    visibilityState === "visible" &&
    !requestRunning
  );
}

export function preparePublishedDatasetsRequest(request, key, forceRefresh) {
  if (forceRefresh && request.isRunning(key)) request.abort();
  return !request.isRunning(key);
}