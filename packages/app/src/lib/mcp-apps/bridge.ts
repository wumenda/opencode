export type HostCapabilities = {
  openLinks?: Record<string, never>
  downloadFile?: Record<string, never>
  message?: Record<string, never>
  serverTools: Record<string, never>
  serverResources: Record<string, never>
  logging?: Record<string, never>
}

export function hostCapabilities(flags: {
  openLink: boolean
  downloadFile: boolean
  message: boolean
  logging: boolean
}): HostCapabilities {
  return {
    ...(flags.openLink ? { openLinks: {} } : {}),
    ...(flags.downloadFile ? { downloadFile: {} } : {}),
    ...(flags.message ? { message: {} } : {}),
    serverTools: {},
    serverResources: {},
    ...(flags.logging ? { logging: {} } : {}),
  }
}