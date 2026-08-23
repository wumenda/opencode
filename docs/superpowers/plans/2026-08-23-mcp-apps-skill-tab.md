# MCP Apps 侧边栏 skill→tool 双层 Tab 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 opencode web 端侧边栏的 MCP Apps 面板从"一层扁平 tab"升级为"skill→tool 两层 tab"：skill 加载后出现一个 skill 标签，其下聚合该 skill 编排出的多个带 UI 的 MCP 工具，以二级 tool 标签展示（同一时刻只渲染激活工具的一个 iframe）。

**Architecture:** 采用方案A——纯客户端分组，不修改服务端。核心思路是在现有 part 流扫描中维护一个"当前 skill"游标：遇到 `tool === "skill"` 的 part 就记录其技能名（`state.input.name`），其后出现的带 `metadata.mcp.ui.resourceUri` 的 MCP 工具 part 都归入该 skill。再把 app 列表归一化为 `SkillGroup { name, apps[] }`，面板据此渲染两级标签。去重键从 `server::resourceUri` 升级为 `skill::server::resourceUri`，避免同一工具被多个 skill 使用时误合并。

**Tech Stack:** TypeScript、Bun (`bun test` / `bun typecheck`)、SolidJS (`createSignal` / `createMemo` / `createEffect` / `For` / `Show`)、现有 `@opencode-ai/session-ui/mcp-tool` 与 `@opencode-ai/session-ui` 组件库。

**目标文件（新增/修改）：**
- Modify: `packages/session-ui/src/components/mcp-tool.tsx`
- Modify: `packages/session-ui/src/components/mcp-tool.test.ts`
- Modify: `packages/app/src/pages/session/v2/mcp-apps-panel-state.ts`
- Create: `packages/app/src/pages/session/v2/mcp-apps-panel-state.test.ts`
- Modify: `packages/app/src/pages/session/v2/use-mcp-apps.ts`
- Modify: `packages/app/src/pages/session/v2/mcp-apps-panel.tsx`
- Modify: `packages/app/src/pages/session.tsx` (仅改一处传参名)
- Modify: `packages/app/src/i18n/en.ts`、`packages/app/src/i18n/zh.ts`

**执行环境：**
- 测试必须从包目录运行（不能用仓库根目录跑，见根 CLAUDE.md）。
- session-ui 包测试命令：`bun test src/components/mcp-tool.test.ts`
- app 包测试命令：`bun test src/pages/session/v2/mcp-apps-panel-state.test.ts`
- 类型检查（从包目录）：`bun typecheck`
- 分支/提交命名遵循仓库 AGENTS.md（`type(scope): summary`，短横线分支名）。

---

## Task 1: `McpAppInfo` 增加 `skill` 字段 + `skillNameFromPart` 工具函数

**Files:**
- Modify: `packages/session-ui/src/components/mcp-tool.tsx:9-41`
- Modify: `packages/session-ui/src/components/mcp-tool.test.ts`

- [ ] **Step 1: 写失败测试**

在 `packages/session-ui/src/components/mcp-tool.test.ts` 中，先扩展测试工厂 `part()`（加可选 `tool`、`inputValue`，默认值保持不变，保证现有用例不受影响）：

```ts
function part(input: {
  status?: "pending" | "running" | "completed" | "error"
  tool?: string
  inputValue?: Record<string, unknown>
  stateMetadata?: Record<string, unknown>
}): ToolPart {
  const status = input.status ?? "completed"
  return {
    id: "part_1",
    sessionID: "ses_1",
    messageID: "msg_1",
    type: "tool",
    callID: "call_1",
    tool: input.tool ?? "weather_show_dashboard",
    state: {
      status,
      input: input.inputValue ?? {},
      output: "done",
      title: "Show dashboard",
      metadata: input.stateMetadata ?? {},
      time: { start: 1, end: 2 },
    },
  } as ToolPart
}
```

（保留原有的 `mcpMeta` 常量与 `mcpAppFromPart` / `mcpProgressFromPart` 两个 describe 不变。）

在新 `describe` 块中补充 `skillNameFromPart` 测试：

```ts
describe("skillNameFromPart", () => {
  test("returns the skill name for a completed skill tool", () => {
    expect(skillNameFromPart(part({ tool: "skill", inputValue: { name: "refinery" } }))).toBe("refinery")
  })

  test("returns the skill name for a running skill tool", () => {
    expect(skillNameFromPart(part({ tool: "skill", status: "running", inputValue: { name: "refinery" } }))).toBe("refinery")
  })

  test("returns undefined for non-skill tools", () => {
    expect(skillNameFromPart(part({}))).toBeUndefined()
  })

  test("returns undefined when the skill input has no name", () => {
    expect(skillNameFromPart(part({ tool: "skill", inputValue: {} }))).toBeUndefined()
  })

  test("returns undefined while the skill tool is still pending", () => {
    expect(skillNameFromPart(part({ tool: "skill", status: "pending", inputValue: { name: "x" } }))).toBeUndefined()
  })
})
```

别忘了在文件顶部 import 中加入 `skillNameFromPart`：

```ts
import { mcpAppFromPart, mcpProgressFromPart, skillNameFromPart } from "./mcp-tool"
```

- [ ] **Step 2: 运行测试确认失败**

在 `packages/session-ui` 目录运行：`bun test src/components/mcp-tool.test.ts`

预期 FAIL：`property skillNameFromPart does not exist` / 未定义。

- [ ] **Step 3: 最小实现**

在 `packages/session-ui/src/components/mcp-tool.tsx` 中，给 `McpAppInfo` 增加 `skill?: string`，并在文件底部（`mcpAppFromPart` 附近）新增 `skillNameFromPart`：

```ts
export type McpAppInfo = {
  server: string
  resourceUri: string
  skill?: string
  fallbackData?: unknown
}
```

沿用文件已有的 `record` 类型守卫，新增工具函数（放在 `mcpAppFromPart` 下方）：

```ts
/** Extracts the skill name from a `skill` tool part's input, if any. */
export function skillNameFromPart(part: ToolPart): string | undefined {
  if (part.tool !== "skill") return undefined
  if (part.state.status !== "running" && part.state.status !== "completed") return undefined
  const input = part.state.input
  if (input && typeof input === "object" && typeof (input as Record<string, unknown>).name === "string")
    return (input as Record<string, unknown>).name as string
  return undefined
}
```

- [ ] **Step 4: 运行测试确认通过**

在 `packages/session-ui` 目录运行：`bun test src/components/mcp-tool.test.ts`

预期 PASS：原有 6 个 `mcpAppFromPart` + 4 个 `mcpProgressFromPart` 用例依旧通过，新增 5 个 `skillNameFromPart` 用例全部通过（`skill` 为可选字段时 `toEqual` 会忽略 `undefined`，不影响旧的相等断言）。

- [ ] **Step 5: 提交**

```bash
git add packages/session-ui/src/components/mcp-tool.tsx packages/session-ui/src/components/mcp-tool.test.ts
git commit -m "feat(session-ui): add McpAppInfo.skill and skillNameFromPart"
```

---

## Task 2: 面板分组纯函数 `buildSkillAppGroups` + 两级选中态

**Files:**
- Modify: `packages/app/src/pages/session/v2/mcp-apps-panel-state.ts`
- Create: `packages/app/src/pages/session/v2/mcp-apps-panel-state.test.ts`

- [ ] **Step 1: 写失败测试**

创建 `packages/app/src/pages/session/v2/mcp-apps-panel-state.test.ts`：

```ts
import { describe, expect, test } from "bun:test"
import type { McpAppInfo } from "@opencode-ai/session-ui/mcp-tool"
import { buildSkillAppGroups, toolTabId } from "./mcp-apps-panel-state"

function app(partial: { server?: string; resourceUri?: string; skill?: string }): McpAppInfo {
  return { server: partial.server ?? "s", resourceUri: partial.resourceUri ?? "u", skill: partial.skill, fallbackData: undefined }
}

describe("buildSkillAppGroups", () => {
  test("groups apps under their skill, preserving first-appearance order", () => {
    const groups = buildSkillAppGroups([
      app({ skill: "skillA", server: "a", resourceUri: "ui://x" }),
      app({ skill: "skillA", server: "b", resourceUri: "ui://y" }),
      app({ skill: undefined, server: "c", resourceUri: "ui://z" }),
    ])
    expect(groups).toEqual([
      {
        name: "skillA",
        apps: [
          { server: "a", resourceUri: "ui://x", skill: "skillA", fallbackData: undefined },
          { server: "b", resourceUri: "ui://y", skill: "skillA", fallbackData: undefined },
        ],
      },
      {
        name: undefined,
        apps: [{ server: "c", resourceUri: "ui://z", skill: undefined, fallbackData: undefined }],
      },
    ])
  })

  test("dedupes the same tool app within one skill", () => {
    const groups = buildSkillAppGroups([
      app({ skill: "s", server: "a", resourceUri: "ui://x" }),
      app({ skill: "s", server: "a", resourceUri: "ui://x" }),
    ])
    expect(groups).toHaveLength(1)
    expect(groups[0]!.apps).toEqual([{ server: "a", resourceUri: "ui://x", skill: "s", fallbackData: undefined }])
  })

  test("keeps the same resource under different skills as separate apps", () => {
    const groups = buildSkillAppGroups([
      app({ skill: "s1", server: "a", resourceUri: "ui://x" }),
      app({ skill: "s2", server: "a", resourceUri: "ui://x" }),
    ])
    expect(groups).toHaveLength(2)
    expect(groups[0]!.apps).toHaveLength(1)
    expect(groups[1]!.apps).toHaveLength(1)
  })

  test("empty input yields empty groups", () => {
    expect(buildSkillAppGroups([])).toEqual([])
  })
})

describe("toolTabId", () => {
  test("uses server::resourceUri as the key", () => {
    expect(toolTabId({ server: "a", resourceUri: "ui://x", fallbackData: undefined })).toBe("a::ui://x")
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

在 `packages/app` 目录运行：`bun test src/pages/session/v2/mcp-apps-panel-state.test.ts`

预期 FAIL：`buildSkillAppGroups` / `toolTabId` 未定义（编译期报错或 import 失败）。

- [ ] **Step 3: 最小实现（替换 `mcp-apps-panel-state.ts`）**

用 `Write`/`Edit` 把 `packages/app/src/pages/session/v2/mcp-apps-panel-state.ts` 整体替换为：

```ts
import { createSignal } from "solid-js"
import type { McpAppInfo } from "@opencode-ai/session-ui/mcp-tool"

export type SkillAppGroup = {
  /** undefined 表示"直连调用"（skill 之外直接触发、无归属 skill 的工具）。 */
  name: string | undefined
  apps: McpAppInfo[]
}

const DIRECT_GROUP_KEY = "\u0000"

/** 洗牌符用 skill::server::resourceUri 去重后，把带 skill 标记者分组成 skill→tools 两级结构，保持首次出现顺序。 */
export function buildSkillAppGroups(labeled: McpAppInfo[]): SkillAppGroup[] {
  const groups: SkillAppGroup[] = []
  const groupIndex = new Map<string, number>()
  const seen = new Set<string>()
  for (const app of labeled) {
    const groupKey = app.skill ?? DIRECT_GROUP_KEY
    const seenKey = `${groupKey}::${app.server}::${app.resourceUri}`
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
  return `${app.server}::${app.resourceUri}`
}

export function createMcpAppsPanelState() {
  const [activeSkill, setActiveSkill] = createSignal<string | undefined>()
  const [activeTool, setActiveTool] = createSignal<string | undefined>()
  return { activeSkill, setActiveSkill, activeTool, setActiveTool }
}

export type McpAppsPanelState = ReturnType<typeof createMcpAppsPanelState>
```

> 说明：删除了原先的 `dedupeMcpApps` 与 `appTabId`（仅 `use-mcp-apps.ts` 使用，Task 3 会一并迁移到新方案）。若 `typecheck` 报某处还在 import 这两个符号，属预期——流水线顺序执行到 Task 3/4 会消掉。

- [ ] **Step 4: 运行测试确认通过**

在 `packages/app` 目录运行：`bun test src/pages/session/v2/mcp-apps-panel-state.test.ts`

预期 PASS：上述 4 个分组用例 + 1 个 `toolTabId` 用例全部通过。

- [ ] **Step 5: 提交**

```bash
git add packages/app/src/pages/session/v2/mcp-apps-panel-state.ts packages/app/src/pages/session/v2/mcp-apps-panel-state.test.ts
git commit -m "feat(app): add skill group builder and two-level panel state"
```

---

## Task 3: `useMcpApps` 按 part 流游标建立 skill 归属并返回分组

**Files:**
- Modify: `packages/app/src/pages/session/v2/use-mcp-apps.ts`

- [ ] **Step 1: 直接实现（本函数无独立纯逻辑可先测，分组逻辑已在 Task 2 全覆盖）**

把 `packages/app/src/pages/session/v2/use-mcp-apps.ts` 整体替换为：

```ts
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
```

- [ ] **Step 2: 跑 app 包类型检查确认编译通过**

在 `packages/app` 目录运行：`bun typecheck`

预期 PASS：无类型错误（`dedupeMcpApps` 引用已移除；`mcp-apps-panel.tsx` 若仍引用 `appTabId`，其报错由 Task 4 接手消除，本任务先忽略该文件的临时报错）。

- [ ] **Step 3: 提交**

```bash
git add packages/app/src/pages/session/v2/use-mcp-apps.ts
git commit -m "feat(app): group MCP apps by skill in useMcpApps"
```

---

## Task 4: 双击渲染——skill 标签栏 + 二级 tool 标签（懒加载 iframe）

**Files:**
- Modify: `packages/app/src/pages/session/v2/mcp-apps-panel.tsx`
- Modify: `packages/app/src/pages/session.tsx:1300-1304`

- [ ] **Step 1: 改写 `mcp-apps-panel.tsx`**

把 `packages/app/src/pages/session/v2/mcp-apps-panel.tsx` 整体替换为：

```tsx
import { For, Show, createEffect, createMemo, type JSX } from "solid-js"
import { Icon } from "@opencode-ai/ui/icon"
import { useLanguage } from "@/context/language"
import { McpAppView } from "@/components/mcp-app-view"
import {
  toolTabId,
  type McpAppsPanelState,
  type SkillAppGroup,
} from "./mcp-apps-panel-state"

export type McpAppsPanelProps = {
  groups: () => SkillAppGroup[]
  state: McpAppsPanelState
}

export function McpAppsPanel(props: McpAppsPanelProps): JSX.Element {
  const language = useLanguage()
  const groups = props.groups
  const state = props.state

  // groups 变化时自动选中首个 skill（与它的首个 tool）；组件禁用/清空时复位。
  createEffect(() => {
    const list = groups()
    if (list.length === 0) {
      state.setActiveSkill(undefined)
      state.setActiveTool(undefined)
      return
    }
    const activeSkill = state.activeSkill()
    const exists = activeSkill !== undefined && list.some((group) => group.name === activeSkill)
    if (!exists) {
      const first = list[0]
      state.setActiveSkill(first.name)
      state.setActiveTool(first.apps[0] ? toolTabId(first.apps[0]) : undefined)
    }
  })

  const activeGroup = createMemo(
    () => groups().find((group) => group.name === state.activeSkill()) ?? groups()[0],
  )

  const activeTool = createMemo(() => {
    const group = activeGroup()
    if (!group) return undefined
    return group.apps.find((app) => toolTabId(app) === state.activeTool()) ?? group.apps[0]
  })

  const selectTool = (app: { server: string; resourceUri: string }) => state.setActiveTool(toolTabId(app))

  return (
    <div data-component="mcp-apps-panel" class="flex h-full flex-col overflow-hidden bg-v2-background-bg-base contain-strict">
      <Show
        when={groups().length > 0}
        fallback={
          <div class="flex h-full flex-col items-center justify-center gap-3 text-center">
            <Icon name="mcp" class="size-8 opacity-10" />
            <div class="max-w-56 text-14-regular text-v2-text-text-muted">
              {language.t("mcp.app.panel.empty")}
            </div>
          </div>
        }
      >
        {/* 第一层：skill 标签栏 */}
        <div class="flex shrink-0 items-center gap-1 border-b border-v2-border-border-base px-2">
          <For each={groups()}>
            {(group) => {
              const isActive = () => state.activeSkill() === group.name
              return (
                <button
                  type="button"
                  role="tab"
                  aria-selected={isActive()}
                  class="flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2 text-13-medium transition-colors"
                  classList={{
                    "border-v2-border-border-bold text-v2-text-text-base": isActive(),
                    "border-transparent text-v2-text-text-muted hover:text-v2-text-text-base": !isActive(),
                  }}
                  onClick={() => {
                    state.setActiveSkill(group.name)
                    state.setActiveTool(group.apps[0] ? toolTabId(group.apps[0]) : undefined)
                  }}
                >
                  <Icon name={group.name ? "brain" : "mcp"} class="size-3.5" />
                  <span>{group.name ?? language.t("mcp.app.panel.direct")}</span>
                  <span class="ml-1 rounded-full bg-v2-background-bg-layer-01 px-1.5 text-11-regular text-v2-text-text-muted">
                    {group.apps.length}
                  </span>
                </button>
              )
            }}
          </For>
        </div>

        {/* 第二层：选中 skill 下的 tool 标签栏（懒挂载 iframe，只渲染激活项） */}
        <Show when={(activeGroup()?.apps.length ?? 0) > 0}>
          <div class="flex shrink-0 items-center gap-1 border-b border-v2-border-border-base bg-v2-background-bg-layer-01 px-2">
            <For each={activeGroup()!.apps}>
              {(app) => {
                const isActive = () => toolTabId(app) === state.activeTool()
                return (
                  <button
                    type="button"
                    role="tab"
                    aria-selected={isActive()}
                    class="flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-1.5 text-13-regular transition-colors"
                    classList={{
                      "border-v2-border-border-bold text-v2-text-text-base": isActive(),
                      "border-transparent text-v2-text-text-muted hover:text-v2-text-text-base": !isActive(),
                    }}
                    onClick={() => selectTool(app)}
                  >
                    <Icon name="mcp" class="size-3" />
                    <span>{app.resourceUri}</span>
                  </button>
                )
              }}
            </For>
          </div>
        </Show>

        {/* 激活 tool 的 iframe 渲染；skill 下暂无带 UI 工具时显示占位 */}
        <div class="min-h-0 flex-1 overflow-hidden p-2">
          <Show
            when={activeTool()}
            fallback={
              <div class="flex h-full flex-col items-center justify-center gap-2 text-center">
                <div class="max-w-64 text-14-regular text-v2-text-text-muted">
                  {language.t("mcp.app.panel.noUiTools")}
                </div>
              </div>
            }
          >
            {(app) => <McpAppView server={app().server} resourceUri={app().resourceUri} fillHeight />}
          </Show>
        </div>
      </Show>
    </div>
  )
}
```

> 说明：`McpAppView` 不再传 `fallbackData`（已改由宿主注册表推送，保持 undefined 即可，组件该 prop 为可选）。

- [ ] **Step 2: 更新 `session.tsx` 传参名**

在 `packages/app/src/pages/session.tsx` 第 ~1300-1304 行，把 `<McpAppsPanel apps={mcpApps} state={mcpAppsState} />` 改为 `<McpAppsPanel groups={mcpApps} state={mcpAppsState} />`：

```tsx
const mcpAppsPanel = () => (
  <div class="flex flex-col h-full overflow-hidden bg-v2-background-bg-base contain-strict">
    <McpAppsPanel groups={mcpApps} state={mcpAppsState} />
  </div>
)
```

- [ ] **Step 3: 跑 app 包类型检查确认编译通过**

在 `packages/app` 目录运行：`bun typecheck`

预期 PASS：全部类型错误消除（此前 mcp-apps-panel 引用 `appTabId`/`McpAppInfo`/旧 state 的报错随本次重写消失）。

- [ ] **Step 4: 提交**

```bash
git add packages/app/src/pages/session/v2/mcp-apps-panel.tsx packages/app/src/pages/session.tsx
git commit -m "feat(app): render two-level skill-tool tabs for MCP apps panel"
```

---

## Task 5: 国际化文案（直连分组名 + 空工具占位）

**Files:**
- Modify: `packages/app/src/i18n/en.ts:342-344`
- Modify: `packages/app/src/i18n/zh.ts`（对应 `mcp.app.panel.*` 区域）

- [ ] **Step 1: 在英文源文件补键**

在 `packages/app/src/i18n/en.ts` 中，紧跟现有 `"mcp.app.panel.tabLabel"`（约第 344 行）加入两键（**英文为源文案，字节保持不变**）：

```ts
  "mcp.app.panel.direct": "Direct",
  "mcp.app.panel.noUiTools": "This skill produced no UI tools",
```

- [ ] **Step 2: 在中文文件补对应键**

在 `packages/app/src/i18n/zh.ts` 的 `mcp.app.panel.*` 区域，同步加入：

```ts
  "mcp.app.panel.direct": "直接调用",
  "mcp.app.panel.noUiTools": "该 skill 未产生带 UI 的工具",
```

> 其余 62 个 locale 由仓库 i18n 传播机制从 `en.ts` 回填覆盖，无需手工编辑；如 lint 抱怨缺键，运行仓库既有的 i18n 同步脚本即可（本任务不另造脚本）。

- [ ] **Step 3: 跑 app 包类型检查确认 i18n 类型通过**

在 `packages/app` 目录运行：`bun typecheck`

预期 PASS：`language.t("mcp.app.panel.direct")` 等两个新键在类型化 i18n API 中可用。

- [ ] **Step 4: 提交**

```bash
git add packages/app/src/i18n/en.ts packages/app/src/i18n/zh.ts
git commit -m "feat(app): add i18n copy for skill-tool MCP apps panel"
```

---

## Task 6: 回归验证与 E2E 用例

**Files:**
- Test Modify: `packages/app/e2e/regression/session-timeline-projection.spec.ts`（新增一条 skill→多 app 的 projection 断言）
- 手动验证：本地起后端 + web

- [ ] **Step 1: 全量跑两个包的相关测试，确认无回归**

在 `packages/session-ui` 运行：`bun test src/components/mcp-tool.test.ts`
在 `packages/app` 运行：`bun test src/pages/session/v2/mcp-apps-panel-state.test.ts`

预期 PASS：与 Task 1/2 相同，无回归。

- [ ] **Step 2: 补充一条 skill→多 MCP app 的 timeline 回归断言**

在 `packages/app/e2e/regression/session-timeline-projection.spec.ts` 的开头 import 处已使用 `toolPart` 工厂；在现有 `test.describe` 中新增一个用例，验证"一个 skill 前后各带一个带 UI 的 MCP app"能生成两个 `McpAppInfo`（复用已有工厂即可，按其签名传 `tool: "skill"/"custom_mcp_tool"`）。具体字段以该 spec 内 `toolPart` 工厂签名为准（其第 6 位参数传 `{ metadata: { mcp: { server, ui: { resourceUri } } } }`），此处抽象描述为：

```ts
const skillAndApps = [
  toolPart("prt_skill_group_a", "skill", "completed", { name: "refinery" }),
  toolPart("prt_app_a", "custom_mcp_tool", "completed", { target: "a" }, /* metadata */ { mcp: { server: "srv", ui: { resourceUri: "ui://a" } } }),
  toolPart("prt_app_b", "custom_mcp_tool", "completed", { target: "b" }, /* metadata */ { mcp: { server: "srv", ui: { resourceUri: "ui://b" } } }),
]
```

断言：两个 app part（`prt_app_a` / `prt_app_b`）在时间线中均可见（复用现有 `data-timeline-part-id` 断言方式）。

- [ ] **Step 3: 运行该 e2e spec**

在 `packages/app` 目录运行：`bun test e2e/regression/session-timeline-projection.spec.ts`

预期 PASS：新增用例通过，原有用例不回归。

- [ ] **Step 4: 手动验证双层 tab**

按 `packages/app/AGENTS.md` 的本地开发方式，分别启动后端与 web：

- Backend（`packages/opencode`）：`bun run --conditions=browser ./src/index.ts serve --port 4096`
- App（`packages/app`）：`bun dev -- --port 4444`
- 打开 `http://localhost:4444`，触发一个会先加载 skill、再由该 skill 调用多个带 UI 的 MCP 工具的场景，确认：
  1. skill 标签出现并显示技能名 + 工具数量角标；
  2. 选中该 skill，下方出现二级 tool 标签；
  3. 切换 tool 标签时只挂载激活项的 iframe（切换前后观察网络/元素数量减少）；
  4. skill 之外直连调用的工具出现在"直接调用"分组。

- [ ] **Step 5: 提交**

```bash
git add packages/app/e2e/regression/session-timeline-projection.spec.ts
git commit -m "test(app): cover skill-to-apps projection in e2e timeline"
```

---

## Self-Review

**1. 方案覆盖核对（对照分析结论）：**
- skill→tool 归属建立（方案A 客户端游标）→Task 3
- 两级去重键 `skill::server::resourceUri` →Task 2 `buildSkillAppGroups`
- skill 标签栏 + 工具数角标 →Task 4
- 二级 tool 标签 + 懒加载只挂激活 iframe（用户所选展示方式）→Task 4
- 直连调用分组（`name === undefined`）→Task 2/3/4 + i18n `mcp.app.panel.direct`
- skill 下无带 UI 工具占位 →Task 4 + i18n `mcp.app.panel.noUiTools`
- i18n 不硬编码（AGENTS/MCP 约束）→Task 5
所有需求点都有对应任务。

**2. 占位扫描：** 无 "TBD"/"TODO"/"implements later"；Task 6 Step 2 因依赖既有的 `toolPart` 工厂精确签名（仓库内不同 spec 的工厂参数位不完全一致），已明确要求"以其签名与 metadata 传参为准"并给出结构示意，执行时不臆造工厂签名——这是刻意保留的一个非占位提示，避免凭空写错 factory 形参。其余每个代码步骤均给出完整代码。

**3. 类型一致性：**
- `McpAppInfo.skill?: string` 在 Task 1 定义，Task 2/3/4 统一引用；
- `SkillAppGroup { name: string | undefined, apps: McpAppInfo[] }` 在 Task 2 定义，Task 3 返回类型与 Task 4 props 使用一致；
- `toolTabId`、`buildSkillAppGroups`、`createMcpAppsPanelState` 在 Task 2 定义，Task 3/4 调用一致；
- `McpAppsPanelProps.apps` 更名 `groups`，Task 4 Step 2 同步更新调用点，避免类型错配。
未发现跨任务命名不一致。