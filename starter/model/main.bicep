// Starter model only. No starter application is ever deployed to Azure (ADR-0005).
// ASI03 (starter): key auth stays enabled so the starter can use an API key.

@description('Azure region for the Foundry resource.')
param location string = resourceGroup().location

@description('Foundry (AI Services) account name. Must be globally unique.')
param accountName string = 'aif-owasp-starter-${uniqueString(resourceGroup().id)}'

@description('Model deployment name used by the starter chat API.')
param deploymentName string = 'gpt-4.1'

@description('Model capacity in thousands of tokens per minute.')
param capacity int = 100

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: accountName
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
  }
  tags: {
    purpose: 'owasp-agents-sample-starter-model'
  }
}

resource deployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: deploymentName
  sku: {
    name: 'GlobalStandard'
    capacity: capacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4.1'
      version: '2025-04-14'
    }
  }
}

output accountName string = account.name
output endpoint string = 'https://${account.properties.customSubDomainName}.openai.azure.com/'
output deploymentName string = deployment.name
