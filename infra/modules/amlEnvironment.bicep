// AML immutable environment version — one per HASTE container image, bound
// to the same ACR reference Azure Batch pulls (batchPool.bicep). Deployed
// ONLY in Create mode (gated exclusively on `createAmlWorkspace` in
// main.bicep) — HASTE's default/first enablement path, `amlMode ==
// 'Existing'`, never deploys this module; it references an already-
// registered environment version by its fully-qualified reference instead
// (existingAmlTrainingEnvironmentReference/existingAmlImageryprepEnvironmentReference
// in main.bicep). Create mode is an explicit, later opt-in. When deployed, a
// new version is registered only when the caller bumps `environmentVersion`
// (main.bicep defaults this to the image tag, so bumping the HASTE image tag
// creates a new, still-immutable version rather than mutating an existing
// one — mirroring the Batch pool's own immutable-image-per-deploy
// convention). AML environment versions cannot be edited in place once
// created, by design.

@description('Resolved AML workspace name (existing or just-created).')
param workspaceName string

@description('Environment name (one per HASTE image, e.g. "training", "imageryprep").')
param environmentName string

@description('Immutable environment version. Defaults to the bound image tag so a new image build always registers a new version instead of mutating one.')
param environmentVersion string

@description('Full container image reference the environment resolves to (e.g. "myacr.azurecr.io/hastetraining:1.4.1"). Prefer an ACR digest reference where available.')
param image string

@description('Human-readable description.')
param environmentDescription string = ''

resource workspace 'Microsoft.MachineLearningServices/workspaces@2025-06-01' existing = {
  name: workspaceName
}

resource environment 'Microsoft.MachineLearningServices/workspaces/environments@2025-06-01' = {
  parent: workspace
  name: environmentName
  properties: {}
}

resource environmentVersionResource 'Microsoft.MachineLearningServices/workspaces/environments/versions@2025-06-01' = {
  parent: environment
  name: environmentVersion
  properties: {
    description: environmentDescription
    image: image
    osType: 'Linux'
  }
}

output name string = environment.name
output version string = environmentVersionResource.name
// Fully-qualified AML SDK v2 environment reference (`azureml:<name>:<version>`),
// ready to bind directly to a command job's `environment` field.
output reference string = 'azureml:${environment.name}:${environmentVersionResource.name}'
