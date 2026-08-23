import { createSignal } from "solid-js"
import type { McpAppInfo } from "@opencode-ai/session-ui/mcp-tool"

export type SkillAppGroup = {
  /** undefined 表示"直连调用"（skill 之外直接触发、无归属 skill 的工具）。 */
  name: string | undefined
  apps: McpAppInfo[]
}

const DIRECT_GROUP_KEY = "\u0000"

/** 以 skill::instanceID 为去重键：同一调用实例（part.id）合并，不同实例各自成条，
 *  保留首次出现顺序。同一 server/resourceUri 的多次调用不再合并（调用链展示）。 */
export function buildSkillAppGroups(labeled: McpAppInfo[]): SkillAppGroup[] {
  const groups: SkillAppGroup[] = []
  const groupIndex = new Map<string, number>()
  const seen = new Set<string>()
  for (const app of labeled) {
    const groupKey = app.skill ?? DIRECT_GROUP_KEY
    const seenKey = `${groupKey}::${app.instanceID}`
    if (seen.has(seenKey)) continue
    seen.add(seenKey)
    let index = groupIndex.get(groupKey)
    if (index === undefined) {
      index = groups.length
      groupIndex.set(groupKey, index)
      groups.push({ name: app.skill, apps: [] })
    }
    groups[index].apps.push(app)
  }
  return groups
}

export function toolTabId(app: McpAppInfo): string {
  return `${app.server}::${app.resourceUri}::${app.instanceID}`
}

export function createMcpAppsPanelState() {
  const [activeSkill, setActiveSkill] = createSignal<string | undefined>()
  const [activeTool, setActiveTool] = createSignal<string | undefined>()
  return { activeSkill, setActiveSkill, activeTool, setActiveTool }
}

export type McpAppsPanelState = ReturnType<typeof createMcpAppsPanelState>