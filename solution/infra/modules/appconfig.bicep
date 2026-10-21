// ASI10: App Configuration holds the agent kill switch. chat-api reads it with its managed identity (Data Reader);
// the developer who runs azd can flip it (Data Owner). Access keys are disabled.
//
// The `agent-kill-switch` key is not declared here: a redeploy must never reset a switch an operator engaged.
// The postprovision hook creates it with `off` only when it is missing, and chat-api treats a missing key as engaged.
param location string
param tags object
param resourceToken string
param readerPrincipalId string
param developerPrincipalId string
param developerPrincipalType string

var roles = {
  appConfigDataReader: '516239f1-63e1-4d78-a4de-a74fb236a071'
  appConfigDataOwner: '5ae67dd6-50cb-40e7-96ff-dc2bfa4b606b'
}

resource store 'Microsoft.AppConfiguration/configurationStores@2024-05-01' = {
  name: 'appcs-${resourceToken}'
  location: location
  tags: tags
  // The subscription's single free store is already in use, and the free tier's daily request quota would throttle
  // per-run checks into a fail-closed outage.
  sku: { name: 'standard' }
  properties: {
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
    softDeleteRetentionInDays: 1
    enablePurgeProtection: false
  }
}

resource readerRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(store.id, readerPrincipalId, roles.appConfigDataReader)
  scope: store
  properties: {
    principalId: readerPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.appConfigDataReader)
  }
}

resource developerRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(developerPrincipalId)) {
  name: guid(store.id, developerPrincipalId, roles.appConfigDataOwner)
  scope: store
  properties: {
    principalId: developerPrincipalId
    principalType: developerPrincipalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.appConfigDataOwner)
  }
}

output endpoint string = store.properties.endpoint
output name string = store.name
