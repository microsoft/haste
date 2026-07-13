// VNet, NSG and three subnets (replaces configure_networking_and_logging's
// network portion). Subnets are declared inline to avoid update races.

@description('Azure region.')
param location string

@description('Virtual network name.')
param vnetName string

@description('Network security group name.')
param nsgName string

@description('Functions VNet-integration subnet name.')
param functionsSubnetName string

@description('Batch pool subnet name.')
param batchSubnetName string

@description('Resource tags.')
param tags object = {}

resource nsg 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: nsgName
  location: location
  tags: tags
  properties: {
    securityRules: []
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: vnetName
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.0.0.0/16'
      ]
    }
    subnets: [
      {
        name: 'default'
        properties: {
          addressPrefix: '10.0.0.0/24'
          networkSecurityGroup: {
            id: nsg.id
          }
          serviceEndpoints: [
            {
              service: 'Microsoft.Web'
            }
            {
              service: 'Microsoft.Storage'
            }
          ]
          delegations: [
            {
              name: 'serverFarms'
              properties: {
                serviceName: 'Microsoft.Web/serverFarms'
              }
            }
          ]
        }
      }
      {
        name: functionsSubnetName
        properties: {
          addressPrefix: '10.0.1.0/24'
          networkSecurityGroup: {
            id: nsg.id
          }
          serviceEndpoints: [
            {
              service: 'Microsoft.Storage'
            }
            {
              service: 'Microsoft.Web'
            }
          ]
          delegations: [
            {
              // Flex Consumption VNet integration requires the integration
              // subnet to be delegated to Microsoft.App/environments.
              name: 'appEnvironments'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
      {
        name: batchSubnetName
        properties: {
          addressPrefix: '10.0.2.0/24'
          serviceEndpoints: [
            {
              service: 'Microsoft.Storage'
            }
          ]
        }
      }
    ]
  }
}

output vnetId string = vnet.id
output vnetName string = vnet.name
output defaultSubnetId string = '${vnet.id}/subnets/default'
output functionsSubnetId string = '${vnet.id}/subnets/${functionsSubnetName}'
output batchSubnetId string = '${vnet.id}/subnets/${batchSubnetName}'
output nsgId string = nsg.id
