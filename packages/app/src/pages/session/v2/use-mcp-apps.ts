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

/**
 * 从会话消息中收集 MCP App 并按"所属 skill"分组。
 * 遍历消息/parts（保持流顺序），维护 currentSkill 游标：
 * 遇到 skill 工具 part 记下技能名；其后带 ui:// resourceUri 的 MCP 工具都归入该 skill。
 * 直连调用（skill 之外）的工具归入 name === undefined 的分组。
 */
export function useMcpApps(sessionID: Accessor<string | undefined>): Accessor<SkillAppGroup[]> {
  const sync = useSync()

  return createMemo(() => {
    const id = sessionID()
    if (!id) return []

    const messages = sync().data.message[id] ?? []
    const labeled: McpAppInfo[] = []
    let currentSkill: string | undefined

    for (const msg of messages) {
      const parts = sync().data.part[msg.id] ?? []
      for (const part of parts) {
        if (part.type !== "tool") continue
        const tool = part as ToolPart
        const skill = skillNameFromPart(tool)
        if (skill !== undefined) currentSkill = skill
        const app = mcpAppFromPart(tool)
        if (app) labeled.push({ ...app, skill: currentSkill })
      }
    }

    return buildSkillAppGroups(labeled)
  })
}