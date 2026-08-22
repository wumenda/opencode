export type HostContext = {
  theme?: "light" | "dark"
  displayMode: "inline"
  containerDimensions?: { width: number; height: number }
  locale?: string
  timeZone?: string
  platform: "web"
  deviceCapabilities?: { touch: boolean; hover: boolean }
}

export function buildHostContext(input: {
  width?: number
  height?: number
  theme?: "light" | "dark"
  locale?: string
  timeZone?: string
}): HostContext {
  const dims = input.width && input.height ? { width: input.width, height: input.height } : undefined
  return {
    theme: input.theme,
    displayMode: "inline",
    containerDimensions: dims,
    locale: input.locale,
    timeZone: input.timeZone,
    platform: "web",
    deviceCapabilities: { touch: false, hover: true },
  }
}