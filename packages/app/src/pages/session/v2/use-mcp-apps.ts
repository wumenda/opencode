import { createMemo } from "solid-js"
import type { Accessor } from "solid-js"
import type { ToolPart } from "@opencode-ai/sdk/v2"
import {
  mcpAppFromPart,
  skillNameFromPart,
  type McpAppInfo,
} from "@opencode-ai/session-ui/mcp-tool"
import { useSync } from "@/context/sync"
import { buildSkillAppGroups, type SkillAppGroup } from "./mcp-apps-panel-state"

export type McpAppsSnapshot = {
  groups: SkillAppGroup[]
  /** 会话中最近一次执行的 MCP App（按 parts 顺序取最后一个带 ui 的工具），用于面板自动切换焦点。 */
  latestExecuted: { app: McpAppInfo; partID: string } | undefined
}

/**
 * 从会话消息中收集 MCP App 并按"所属 skill"分组。
 * 遍历消息/parts（保持流顺序），维护 currentSkill 游标：
 * 遇到 skill 工具 part 记下技能名；其后带 ui:// resourceUri 的 MCP 工具都归入该 skill。
 * 直连调用（skill 之外）的工具归入 name === undefined 的分组。
 * 同时记录最近一次执行的 MCP App（含其 partID），供右侧面板在新 tool 执行时切换 tab 焦点。
 */
export function useMcpApps(sessionID: Accessor<string | undefined>): Accessor<McpAppsSnapshot> {
  const sync = useSync()

  return createMemo<McpAppsSnapshot>(() => {
    const id = sessionID()
    if (!id) return { groups: [], latestExecuted: undefined }

    const messages = sync().data.message[id] ?? []
    const labeled: McpAppInfo[] = []
    let currentSkill: string | undefined
    let latest: { app: McpAppInfo; partID: string } | undefined

    for (const msg of messages) {
      const parts = sync().data.part[msg.id] ?? []
      for (const part of parts) {
        if (part.type !== "tool") continue
        const tool = part as ToolPart
        const skill = skillNameFromPart(tool)
        if (skill !== undefined) currentSkill = skill
        const app = mcpAppFromPart(tool)
        if (app) {
          labeled.push({ ...app, skill: currentSkill })
          latest = { app: { ...app, skill: currentSkill }, partID: part.id }
        }
      }
    }

    return { groups: buildSkillAppGroups(labeled), latestExecuted: latest }
  })
}
