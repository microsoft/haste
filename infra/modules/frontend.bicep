// Static Web App (Standard) linked to APIM as its backend, plus the Azure Maps
// account. (Reproduces create_static_app and create_map_account.)

@description('Azure region for the Static Web App.')
param location string

@description('Static Web App name.')
param staticWebAppName string

@description('Azure Maps account name.')
param mapsAccountName string

@description('APIM resource id to link as the SWA backend.')
param apimResourceId string

@description('Resource tags.')
param tags object = {}

resource staticWebApp 'Microsoft.Web/staticSites@2024-04-01' = {
  name: staticWebAppName
  location: location
  tags: tags
  sku: {
    name: 'Standard'
    tier: 'Standard'
  }
  properties: {}
}

resource linkedBackend 'Microsoft.Web/staticSites/linkedBackends@2024-04-01' = {
  parent: staticWebApp
  name: 'apim-backend'
  properties: {
    backendResourceId: apimResourceId
    region: location
  }
}

resource mapsAccount 'Microsoft.Maps/accounts@2023-06-01' = {
  name: mapsAccountName
  location: 'global'
  tags: tags
  kind: 'Gen2'
  sku: {
    name: 'G2'
  }
  properties: {}
}

output staticWebAppName string = staticWebApp.name
output staticWebAppHostName string = staticWebApp.properties.defaultHostname
output mapsAccountName string = mapsAccount.name
// Client (app) id the SWA build embeds for Azure Maps anonymous auth
// (VITE_AZURE_MAPS_CLIENT_ID; the token itself is minted server-side by the API).
output mapsClientId string = mapsAccount.properties.uniqueId
