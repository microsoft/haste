export async function loadHomeData(get) {
  const [dashboard, catalog] = await Promise.allSettled([
    get("GetDashboardData"),
    get("GetModelCatalog"),
  ]);

  return {
    dashboardData: dashboard.status === "fulfilled" ? dashboard.value : null,
    dashboardError: dashboard.status === "rejected" ? dashboard.reason : null,
    catalog:
      catalog.status === "fulfilled"
        ? catalog.value?.modelCatalog || []
        : [],
    catalogError: catalog.status === "rejected" ? catalog.reason : null,
  };
}