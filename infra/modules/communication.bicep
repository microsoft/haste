// Azure Communication Services email backend (new in IaC — replaces the
// manually-created ACS whose connection string was pasted by hand).
// The connection string is a deploy-time output, not a stored secret.

@description('Communication Services resource name.')
param acsName string

@description('Email Communication Services resource name.')
param emailServiceName string

@description('Sender-domain mode.')
@allowed([
  'AzureManaged'
  'Custom'
])
param emailSenderDomainType string

@description('Custom sender domain (required when emailSenderDomainType == Custom).')
param emailCustomDomain string = ''

@description('Resource tags.')
param tags object = {}

var isCustom = emailSenderDomainType == 'Custom'
var domainResourceName = isCustom ? emailCustomDomain : 'AzureManagedDomain'

resource emailService 'Microsoft.Communication/emailServices@2023-04-01' = {
  name: emailServiceName
  location: 'global'
  tags: tags
  properties: {
    dataLocation: 'United States'
  }
}

resource emailDomain 'Microsoft.Communication/emailServices/domains@2023-04-01' = {
  parent: emailService
  name: domainResourceName
  location: 'global'
  tags: tags
  properties: {
    domainManagement: isCustom ? 'CustomerManaged' : 'AzureManaged'
    userEngagementTracking: 'Disabled'
  }
}

resource acs 'Microsoft.Communication/communicationServices@2023-04-01' = {
  name: acsName
  location: 'global'
  tags: tags
  properties: {
    dataLocation: 'United States'
    linkedDomains: [
      emailDomain.id
    ]
  }
}

@secure()
output connectionString string = acs.listKeys().primaryConnectionString
output senderDomain string = emailDomain.properties.fromSenderDomain
output acsName string = acs.name
