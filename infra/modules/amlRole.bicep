// Least-privilege AML RBAC for one Function App identity — AzureML Data
// Scientist (submit/read/cancel jobs, read compute; explicitly excludes
// workspace management and compute create/delete/listKeys). Deployed ONLY
// in Create mode (gated exclusively on `createAmlWorkspace` in main.bicep) —
// HASTE's default/first enablement path, `amlMode == 'Existing'`, never
// deploys this module; RBAC on a referenced, platform-owned workspace is a
// prerequisite owned by that platform, not something this IaC grants. Create
// mode is an explicit, later opt-in, at which point HASTE also owns the
// workspace and therefore its own RBAC. Deployed at the scope of the
// resolved AML workspace's resource group, which may differ from the env RG
// — mirrors the cross-RG, additive-only pattern in acrRole.bicep and
// batchPool.bicep. A plain resource declaration inside functionApp.bicep
// cannot express this cross-RG grant (Bicep requires a module for any
// resource deployed outside its file's own scope), so this stays a small,
// separate module instead of being inlined there.

@description('Resolved AML workspace name (existing or just-created).')
param amlWorkspaceName string

@description('System-assigned principal id of the Function App identity to grant AML access to.')
param principalId string

var amlDataScientistRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'f6c7c914-8db3-469d-8ca1-694a8f32e121'
)

resource workspace 'Microsoft.MachineLearningServices/workspaces@2025-06-01' existing = {
  name: amlWorkspaceName
}

resource amlDataScientistAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(workspace.id, principalId, 'amlDataScientist')
  scope: workspace
  properties: {
    roleDefinitionId: amlDataScientistRoleId
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}
