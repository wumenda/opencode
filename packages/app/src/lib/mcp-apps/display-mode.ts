export type DisplayMode = "inline" | "fullscreen" | "pip"

export const SUPPORTED_DISPLAY_MODES: DisplayMode[] = ["inline"]

/** 按宿主支持列表协商实际生效的显示模式；不支持则回退 inline。 */
export function resolveDisplayMode(requested: DisplayMode, supported: DisplayMode[]): DisplayMode {
  return supported.includes(requested) ? requested : "inline"
}