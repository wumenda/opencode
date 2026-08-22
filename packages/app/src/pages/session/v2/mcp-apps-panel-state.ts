import { createSignal } from "solid-js"
import type { McpAppInfo } from "@opencode-ai/session-ui/mcp-tool"

/**
 * 按 {server, resourceUri} 去重，保留最新的 App 信息（后执行的覆盖先执行的）。
 */
export function dedupeMcpApps(apps: McpAppInfo[]): McpAppInfo[] {
  const map = new Map<string, McpAppInfo>()
  for (const app of apps) {
    const key = `${app.server}::${app.resourceUri}`
    map.set(key, app)
  }
  return [...map.values()]
}

/**
 * 生成 Tab 唯一标识。
 */
export function appTabId(app: McpAppInfo): string {
  return `${app.server}::${app.resourceUri}`
}

export function createMcpAppsPanelState() {
  const [activeTabId, setActiveTabId] = createSignal<string | undefined>()

  return {
    activeTabId,
    setActiveTabId,
  }
}

export type McpAppsPanelState = ReturnType<typeof createMcpAppsPanelState>