// Reads the image a container app is running, so re-provisioning keeps what azd deploy pushed.
param name string
param exists bool

resource existingApp 'Microsoft.App/containerApps@2024-03-01' existing = if (exists) {
  name: name
}

#disable-next-line BCP318
output image string = exists ? existingApp.properties.template.containers[0].image : ''
