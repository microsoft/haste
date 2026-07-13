// Feature-flagged Front Door (Premium) + WAF in front of the Static Web App.
// Default off (enableFrontDoor=false) — preserves the bash EnableFrontDoor=false
// behaviour. (Reproduces create_frontdoor_and_waf.)

@description('Front Door (CDN) profile name.')
param frontDoorName string

@description('WAF policy name.')
param wafPolicyName string

@description('Static Web App name to use as the origin.')
param staticWebAppName string

resource staticWebApp 'Microsoft.Web/staticSites@2024-04-01' existing = {
  name: staticWebAppName
}

resource wafPolicy 'Microsoft.Network/FrontDoorWebApplicationFirewallPolicies@2024-02-01' = {
  name: wafPolicyName
  location: 'global'
  sku: {
    name: 'Premium_AzureFrontDoor'
  }
  properties: {
    policySettings: {
      enabledState: 'Enabled'
      mode: 'Prevention'
    }
    managedRules: {
      managedRuleSets: [
        {
          ruleSetType: 'DefaultRuleSet'
          ruleSetVersion: '1.0'
        }
        {
          ruleSetType: 'Microsoft_BotManagerRuleSet'
          ruleSetVersion: '1.0'
        }
      ]
    }
  }
}

resource profile 'Microsoft.Cdn/profiles@2024-02-01' = {
  name: frontDoorName
  location: 'global'
  sku: {
    name: 'Premium_AzureFrontDoor'
  }
  identity: {
    type: 'SystemAssigned'
  }
}

resource endpoint 'Microsoft.Cdn/profiles/afdEndpoints@2024-02-01' = {
  parent: profile
  name: '${frontDoorName}-endpoint'
  location: 'global'
  properties: {
    enabledState: 'Enabled'
  }
}

resource originGroup 'Microsoft.Cdn/profiles/originGroups@2024-02-01' = {
  parent: profile
  name: '${frontDoorName}-origin-group'
  properties: {
    loadBalancingSettings: {
      sampleSize: 4
      successfulSamplesRequired: 3
      additionalLatencyInMilliseconds: 50
    }
    healthProbeSettings: {
      probePath: '/'
      probeRequestType: 'GET'
      probeProtocol: 'Https'
      probeIntervalInSeconds: 30
    }
  }
}

resource origin 'Microsoft.Cdn/profiles/originGroups/origins@2024-02-01' = {
  parent: originGroup
  name: '${frontDoorName}-origin'
  properties: {
    hostName: staticWebApp.properties.defaultHostname
    originHostHeader: staticWebApp.properties.defaultHostname
    httpPort: 80
    httpsPort: 443
    priority: 1
    weight: 1000
    enabledState: 'Enabled'
  }
}

resource route 'Microsoft.Cdn/profiles/afdEndpoints/routes@2024-02-01' = {
  parent: endpoint
  name: 'default-route'
  dependsOn: [
    origin
  ]
  properties: {
    originGroup: {
      id: originGroup.id
    }
    patternsToMatch: [
      '/*'
    ]
    forwardingProtocol: 'MatchRequest'
    httpsRedirect: 'Enabled'
    linkToDefaultDomain: 'Enabled'
    supportedProtocols: [
      'Http'
      'Https'
    ]
    enabledState: 'Enabled'
  }
}

resource securityPolicy 'Microsoft.Cdn/profiles/securityPolicies@2024-02-01' = {
  parent: profile
  name: 'Security'
  properties: {
    parameters: {
      type: 'WebApplicationFirewall'
      wafPolicy: {
        id: wafPolicy.id
      }
      associations: [
        {
          domains: [
            {
              id: endpoint.id
            }
          ]
          patternsToMatch: [
            '/*'
          ]
        }
      ]
    }
  }
}

output endpointHostName string = endpoint.properties.hostName
