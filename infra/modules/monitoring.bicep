// Log Analytics workspace + (App Insights components are created per-function
// in functions.bicep and linked back to this workspace).

@description('Azure region.')
param location string

@description('Log Analytics workspace name.')
param logAnalyticsName string

@description('Resource tags.')
param tags object = {}

@description('Days to keep workspace data. Lowering it deletes older data.')
@minValue(30)
@maxValue(730)
param retentionInDays int = 30

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: retentionInDays
  }
}

output logAnalyticsId string = logAnalytics.id
output logAnalyticsName string = logAnalytics.name
