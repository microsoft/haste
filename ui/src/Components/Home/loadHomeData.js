export function loadHomeData(get, options = {}) {
  return {
    dashboard: get("GetDashboardData", options),
    catalog: get("GetModelCatalog", options).then(
      (response) => response?.modelCatalog || []
    ),
  };
}