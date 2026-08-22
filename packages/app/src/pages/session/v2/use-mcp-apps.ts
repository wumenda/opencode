import { createMemo } from "solid-js"
import type { Accessor } from "solid-js"
import type { ToolPart } from "@opencode-ai/sdk/v2"
import { mcpAppFromPart, type McpAppInfo } from "@opencode-ai/session-ui/mcp-tool"
import { useSync } from "@/context/sync"
import { dedupeMcpApps } from "./mcp-apps-panel-state"

/**
 * 从会话消息中收集所有已完成 MCP 工具的 App UI 信息。
 * 扫描所有消息的 Parts，提取携带 ui:// resourceUri 的 MCP 工具结果。
 */
export function useMcpApps(sessionID: Accessor<string | undefined>): Accessor<McpAppInfo[]> {
  const sync = useSync()

  return createMemo(() => {
    const id = sessionID()
    if (!id) return []

    const messages = sync().data.message[id] ?? []
    const apps: McpAppInfo[] = []

    for (const msg of messages) {
      const parts = sync().data.part[msg.id] ?? []
      for (const part of parts) {
        if (part.type !== "tool") continue
        const app = mcpAppFromPart(part as ToolPart)
        if (app) apps.push(app)
      }
    }

    return dedupeMcpApps(apps)
  })
}