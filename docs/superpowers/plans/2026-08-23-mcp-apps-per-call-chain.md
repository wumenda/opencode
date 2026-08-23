# MCP Apps 按调用实例隔离（调用链展示）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让对话流里每个 tool 调用实例的 UI 各自定格在自己那次调用的结果上；右侧 MCP Apps 面板按"调用链"展示——每次调用一个二级 tab（显示工具名 + 调用序号），不再按 `server::resourceUri` 合并成单实例。

**Architecture:** 引入"调用实例"维度 `instanceID = part.id`，贯穿三层：①事件路由 key 从 `sessionID:server/resourceUri` 升级为 `sessionID:server/resourceUri:instanceID`，使 `McpAppHost` 广播收敛为实例级隔离（对话流每份 iframe 只收到自己那次调用的事件，天然定格）；②`buildSkillAppGroups` 去重键从 `skill::server::resourceUri` 改为 `skill::instanceID`（同一 part 的 running→completed 更新仍合并，多次调用生成独立条目），二级 tab 展示调用链；③`toolTabId` 追加 `instanceID`。**不再遵守 SEP-1865 "App 按 resourceUri 单实例"语义**——同一资源不同调用即不同展示实例。

**Tech Stack:** TypeScript、Bun（`bun test` / `bun typecheck`）、SolidJS（`createMemo`/`createEffect`/`For`/`Show`）、Playwright（mock server e2e）、现有 `@opencode-ai/session-ui/mcp-tool` 与 `@opencode-ai/session-ui` 组件库。

**目标文件（新增/修改）：**
- Modify: `packages/session-ui/src/components/mcp-tool.tsx`
- Modify: `packages/session-ui/src/components/mcp-tool.test.ts`
- Modify: `packages/session-ui/src/context/mcp-app.tsx`
- Modify: `packages/app/src/components/mcp-app-view.tsx`
- Modify: `packages/app/src/pages/session/v2/mcp-apps-panel-state.ts`
- Modify: `packages/app/src/pages/session/v2/mcp-apps-panel-state.test.ts`
- Modify: `packages/app/src/pages/session/v2/mcp-apps-panel.tsx`
- Modify: `packages/app/e2e/regression/mcp-apps-panel.spec.ts`

**执行环境：**
- 测试必须从包目录运行（不能从仓库根目录，见根 CLAUDE.md）。
- session-ui 包测试：`bun test src/components/mcp-tool.test.ts`
- app 包测试：`bun test src/pages/session/v2/mcp-apps-panel-state.test.ts`
- 类型检查（从 `packages/app`）：`bun typecheck`；e2e 类型：`bun run typecheck:e2e`
- e2e（从 `packages/app`）：`bunx playwright test e2e/regression/mcp-apps-panel.spec.ts --workers=1`
- 提交遵循 AGENTS.md：`type(scope): summary`；短横线分支名。当前分支 `mcp-apps-skill-tab`。

---

## Task 1: `McpAppInfo` 增加 `instanceID` + `toolName`，`mcpAppFromPart` 填充

**Files:**
- Modify: `packages/session-ui/src/components/mcp-tool.tsx:9-14`（McpAppInfo）、`:33-44`（mcpAppFromPart）
- Test: `packages/session-ui/src/components/mcp-tool.test.ts`

- [ ] **Step 1: 写失败测试**

在 `packages/session-ui/src/components/mcp-tool.test.ts` 中，给 `part()` 工厂增加可选 `id` 参数（默认值 `"part_1"` 保持不变，保证既有用例不受影响）：

```ts
function part(input: {
  id?: string
  status?: "pending" | "running" | "completed" | "error"
  tool?: string
  inputValue?: Record<string, unknown>
  stateMetadata?: Record<string, unknown>
}): ToolPart {
  const status = input.status ?? "completed"
  return {
    id: input.id ?? "part_1",
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

在 `mcpAppFromPart` 的 `describe` 块中，把所有既有 `toEqual` 断言**逐条补上 `instanceID: "part_1"`**（当前期望对象缺该字段会 FAIL），例如第一条改为：

```ts
test("returns app info for completed tool with mcp ui resourceUri", () => {
  const info = mcpAppFromPart(part({ stateMetadata: { mcp: mcpMeta } }))
  expect(info).toEqual({
    server: "weather",
    resourceUri: "ui://dashboard",
    instanceID: "part_1",
    toolName: "show_dashboard",
    fallbackData: undefined,
  })
})
```

同理更新其余 2 条 toEqual 断言（`running` / `error` 两条，均补 `instanceID: "part_1"`、`toolName: "show_dashboard"` 或 `"ui"`——error 那条 metadata 为 `{ server: "ui", ui: { resourceUri: "ui://x" } }`，无 `tool`，故 `toolName: undefined`）。并在 describe 块末尾新增两条：

```ts
test("uses the part id as the per-call instance id", () => {
  const info = mcpAppFromPart(part({ id: "prt_call_2", stateMetadata: { mcp: mcpMeta } }))
  expect(info).toEqual({
    server: "weather",
    resourceUri: "ui://dashboard",
    instanceID: "prt_call_2",
    toolName: "show_dashboard",
    fallbackData: undefined,
  })
})

test("omits toolName when the mcp metadata has no tool", () => {
  const info = mcpAppFromPart(part({ stateMetadata: { mcp: { server: "ui", ui: { resourceUri: "ui://x" } } } }))
  expect(info).toEqual({ server: "ui", resourceUri: "ui://x", instanceID: "part_1", toolName: undefined, fallbackData: undefined })
})
```

- [ ] **Step 2: 运行测试确认失败**

在 `packages/session-ui` 目录运行：`bun test src/components/mcp-tool.test.ts`
预期 FAIL：`toEqual` 因缺 `instanceID` / `toolName` 字段而断言失败。

- [ ] **Step 3: 最小实现**

在 `packages/session-ui/src/components/mcp-tool.tsx` 中更新类型与提取函数：

```ts
export type McpAppInfo = {
  server: string
  resourceUri: string
  /** 调用实例标识（part.id）：同一 tool 多次调用各自独立，事件按它隔离。 */
  instanceID: string
  /** 工具名（metadata.mcp.tool），供面板 tab 显示调用链。 */
  toolName?: string
  skill?: string
  fallbackData?: unknown
}
```

并把 `mcpAppFromPart` 的返回改为：

```ts
export function mcpAppFromPart(part: ToolPart): McpAppInfo | undefined {
  if (part.state.status !== "running" && part.state.status !== "completed" && part.state.status !== "error") return
  const mcp = record(toolMetadata(part)?.mcp)
  if (!mcp) return
  const server = mcp.server
  const resourceUri = record(mcp.ui)?.resourceUri
  if (typeof server !== "string" || !server) return
  if (typeof resourceUri !== "string" || !resourceUri) return
  const toolName = typeof mcp.tool === "string" ? mcp.tool : undefined
  return { server, resourceUri, instanceID: part.id, toolName, fallbackData: undefined }
}
```

- [ ] **Step 4: 运行测试确认通过**

在 `packages/session-ui` 目录运行：`bun test src/components/mcp-tool.test.ts`
预期 PASS：原 6 条 `mcpAppFromPart` + 新增 2 条 + 既有 `mcpProgressFromPart` / `skillNameFromPart` 全部通过。

- [ ] **Step 5: 提交**

```bash
git add packages/session-ui/src/components/mcp-tool.tsx packages/session-ui/src/components/mcp-tool.test.ts
git commit -m "feat(session-ui): add per-call instanceID and toolName to McpAppInfo"
```

---

## Task 2: `McpTool` 事件 key 带实例 + `McpAppRendererInput` 增加 `instanceID`

**Files:**
- Modify: `packages/session-ui/src/components/mcp-tool.tsx:103-106`、`:195-197`（push key 与 renderApp）
- Modify: `packages/session-ui/src/context/mcp-app.tsx:4-10`

- [ ] **Step 1: 直接实现（无独立纯逻辑可先测，行为由 Task 6 e2e 回归覆盖）**

在 `packages/session-ui/src/context/mcp-app.tsx` 中，给 `McpAppRendererInput` 增加字段：

```ts
export type McpAppRendererInput = {
  server: string
  resourceUri: string
  fallbackData?: unknown
  /** 归属会话：McpAppHost 事件按 sessionID 隔离，避免跨 session 串扰。 */
  sessionID?: string
  /** 调用实例标识（part.id）：host 事件按实例隔离，避免同名工具多次调用互相覆盖。 */
  instanceID?: string
}
```

在 `packages/session-ui/src/components/mcp-tool.tsx` 中，把 `appKey` 与 `renderApp` 改为携带实例：

```ts
// McpAppHost 事件按 sessionID + 调用实例隔离：key 带上 part 归属会话与实例 id，
// 同一 server/resourceUri 的多次调用（不同 part.id）互不串扰，各自定格。
const appKey = (info: McpAppInfo) =>
  `${props.part.sessionID}:${info.server}/${info.resourceUri}:${info.instanceID}`
```

并把渲染调用改为（`<Show when={app()}>` 块内）：

```tsx
{/* Keyed by instanceID: 同一调用实例的 part 更新（running→completed）不重挂载 iframe，
    不同调用实例各自独立挂载。 */}
<Show when={app()}>
  {(info) => renderApp?.({ ...info(), sessionID: props.part.sessionID, instanceID: info().instanceID })}
</Show>
```

- [ ] **Step 2: 跑 session-ui 类型检查确认编译通过**

在 `packages/session-ui` 目录运行：`bun typecheck`
预期 PASS：无类型错误（`McpAppRendererInput` 新增可选字段，`McpTool` 内调用处已更新）。

- [ ] **Step 3: 提交**

```bash
git add packages/session-ui/src/components/mcp-tool.tsx packages/session-ui/src/context/mcp-app.tsx
git commit -m "feat(session-ui): scope MCP app events to call instance in McpTool"
```

---

## Task 3: `McpAppView` 增加 `instanceID` prop，注册 key 追加实例

**Files:**
- Modify: `packages/app/src/components/mcp-app-view.tsx:25-41`（props）、`:127-151`（appKey/register）

- [ ] **Step 1: 直接实现（行为由 Task 6 e2e 回归覆盖）**

在 `packages/app/src/components/mcp-app-view.tsx` 的 props 中增加（紧邻 `sessionID`）：

```ts
  /** 调用实例标识（part.id）：与 McpTool 的 push key 保持一致，事件按实例隔离。 */
  instanceID?: string
```

并把 `appKey` 改为（`:129`）：

```ts
  // 按 sessionID:server/resourceUri:instanceID 在宿主注册表注册/注销本 App 的 sink。
  // sessionID 前缀隔离跨会话；instanceID 后缀隔离同资源的多实例调用（调用链展示）。
  const appKey = () =>
    `${props.sessionID ? `${props.sessionID}:` : ""}${props.server}/${props.resourceUri}${props.instanceID ? `:${props.instanceID}` : ""}` as AppKey
```

- [ ] **Step 2: 跑 app 包类型检查确认编译通过**

在 `packages/app` 目录运行：`bun typecheck`
预期 PASS（`instanceID` 为可选 prop，既有调用处无需改动即可编译）。

- [ ] **Step 3: 提交**

```bash
git add packages/app/src/components/mcp-app-view.tsx
git commit -m "feat(app): scope McpAppView host key to call instance"
```

---

## Task 4: 分组改为实例级（展示调用链）+ `toolTabId` 含实例

**Files:**
- Modify: `packages/app/src/pages/session/v2/mcp-apps-panel-state.ts`
- Test: `packages/app/src/pages/session/v2/mcp-apps-panel-state.test.ts`

- [ ] **Step 1: 写失败测试**

在 `packages/app/src/pages/session/v2/mcp-apps-panel-state.test.ts` 中，把 `app()` 工厂改为必带 `instanceID`（加可选 `toolName`）：

```ts
function app(partial: { server?: string; resourceUri?: string; skill?: string; instanceID?: string; toolName?: string }): McpAppInfo {
  return {
    server: partial.server ?? "s",
    resourceUri: partial.resourceUri ?? "u",
    instanceID: partial.instanceID ?? "i_1",
    toolName: partial.toolName,
    skill: partial.skill,
    fallbackData: undefined,
  }
}
```

把 `describe("buildSkillAppGroups")` 内既有用例改写成新语义（同 resourceUri 不同实例 → 各自独立成条目）：

```ts
test("groups apps under their skill, preserving first-appearance order", () => {
  const groups = buildSkillAppGroups([
    app({ skill: "skillA", server: "a", resourceUri: "ui://x", instanceID: "p1", toolName: "step1" }),
    app({ skill: "skillA", server: "b", resourceUri: "ui://y", instanceID: "p2", toolName: "step2" }),
    app({ skill: undefined, server: "c", resourceUri: "ui://z", instanceID: "p3", toolName: "step3" }),
  ])
  expect(groups).toEqual([
    {
      name: "skillA",
      apps: [
        { server: "a", resourceUri: "ui://x", instanceID: "p1", toolName: "step1", skill: "skillA", fallbackData: undefined },
        { server: "b", resourceUri: "ui://y", instanceID: "p2", toolName: "step2", skill: "skillA", fallbackData: undefined },
      ],
    },
    {
      name: undefined,
      apps: [{ server: "c", resourceUri: "ui://z", instanceID: "p3", toolName: "step3", skill: undefined, fallbackData: undefined }],
    },
  ])
})

test("keeps the same resource under different call instances as separate apps", () => {
  const groups = buildSkillAppGroups([
    app({ skill: "s", server: "a", resourceUri: "ui://x", instanceID: "p1" }),
    app({ skill: "s", server: "a", resourceUri: "ui://x", instanceID: "p2" }),
  ])
  expect(groups).toHaveLength(1)
  expect(groups[0]!.apps.map((a) => a.instanceID)).toEqual(["p1", "p2"])
})

test("merges same-part updates (running -> completed) into one app", () => {
  const groups = buildSkillAppGroups([
    app({ skill: "s", server: "a", resourceUri: "ui://x", instanceID: "p1" }),
    app({ skill: "s", server: "a", resourceUri: "ui://x", instanceID: "p1" }),
  ])
  expect(groups).toHaveLength(1)
  expect(groups[0]!.apps).toEqual([
    { server: "a", resourceUri: "ui://x", instanceID: "p1", toolName: undefined, skill: "s", fallbackData: undefined },
  ])
})

test("keeps the same resource under different skills as separate groups", () => {
  const groups = buildSkillAppGroups([
    app({ skill: "s1", server: "a", resourceUri: "ui://x", instanceID: "p1" }),
    app({ skill: "s2", server: "a", resourceUri: "ui://x", instanceID: "p2" }),
  ])
  expect(groups).toHaveLength(2)
  expect(groups[0]!.apps).toHaveLength(1)
  expect(groups[1]!.apps).toHaveLength(1)
})

test("empty input yields empty groups", () => {
  expect(buildSkillAppGroups([])).toEqual([])
})
```

把 `describe("toolTabId")` 改为：

```ts
describe("toolTabId", () => {
  test("uses server::resourceUri::instanceID as the key", () => {
    expect(toolTabId({ server: "a", resourceUri: "ui://x", instanceID: "p1", fallbackData: undefined })).toBe("a::ui://x::p1")
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

在 `packages/app` 目录运行：`bun test src/pages/session/v2/mcp-apps-panel-state.test.ts`
预期 FAIL：`buildSkillAppGroups` / `toolTabId` 仍按旧键（缺 `instanceID`）导致断言不符。

- [ ] **Step 3: 最小实现**

在 `packages/app/src/pages/session/v2/mcp-apps-panel-state.ts` 中替换去重与 tab id：

```ts
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
```

- [ ] **Step 4: 运行测试确认通过**

在 `packages/app` 目录运行：`bun test src/pages/session/v2/mcp-apps-panel-state.test.ts`
预期 PASS：上述 5 个分组用例 + 1 个 `toolTabId` 用例全部通过。

- [ ] **Step 5: 提交**

```bash
git add packages/app/src/pages/session/v2/mcp-apps-panel-state.ts packages/app/src/pages/session/v2/mcp-apps-panel-state.test.ts
git commit -m "feat(app): keep every tool call instance as its own panel entry"
```

---

## Task 5: 面板二级 tab 显示工具名 + 调用序号，McpAppView 传实例

**Files:**
- Modify: `packages/app/src/pages/session/v2/mcp-apps-panel.tsx:59-65`、`:114-131`、`:150-152`

- [ ] **Step 1: 直接实现（行为由 Task 6 e2e 覆盖）**

在 `packages/app/src/pages/session/v2/mcp-apps-panel.tsx` 中：

把 `selectTool` 改为接受完整 `McpAppInfo`（实例内切换用实例 id）：

```tsx
const selectTool = (app: McpAppInfo) => state.setActiveTool(toolTabId(app))
```

二级 tab 按钮内容改为「工具名 + 调用序号」（`For` 提供 index，序号 = 组内第几次调用）：

```tsx
<For each={activeGroup()!.apps}>
  {(app, index) => {
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
        <span>{app.toolName ?? app.resourceUri}</span>
        <span class="ml-1 rounded-full bg-v2-background-bg-layer-01 px-1.5 text-11-regular text-v2-text-text-muted">
          #{index() + 1}
        </span>
      </button>
    )
  }}
</For>
```

把激活 tool 的 `McpAppView` 调用补上 `instanceID`：

```tsx
{(app) => (
  <McpAppView
    server={app().server}
    resourceUri={app().resourceUri}
    sessionID={props.sessionID}
    instanceID={app().instanceID}
    fillHeight
  />
)}
```

同时把顶部 import 从 `type McpAppInfo` 保留（`selectTool` 现在用完整 `McpAppInfo`）。

- [ ] **Step 2: 跑 app 包类型检查确认编译通过**

在 `packages/app` 目录运行：`bun typecheck`
预期 PASS。

- [ ] **Step 3: 提交**

```bash
git add packages/app/src/pages/session/v2/mcp-apps-panel.tsx
git commit -m "feat(app): show tool name and call ordinal in two-level tabs"
```

---

## Task 6: 回归验证与 e2e（调用链 tab + 实例隔离定格）

**Files:**
- Test Modify: `packages/app/e2e/regression/mcp-apps-panel.spec.ts`

- [ ] **Step 1: 全量跑两个包的相关测试，确认无回归**

在 `packages/session-ui` 运行：`bun test src/components/mcp-tool.test.ts`
在 `packages/app` 运行：`bun test src/pages/session/v2/mcp-apps-panel-state.test.ts`
预期 PASS：与 Task 1/4 相同，无回归。

- [ ] **Step 2: 更新既有 e2e 两级 tab 用例的标签断言**

在 `packages/app/e2e/regression/mcp-apps-panel.spec.ts` 的 "groups a skill's MCP tools into two-level tabs" 用例中，二级 tab 的文本从 `resourceUri` 变为「toolName + #序号」（该用例的 part 的 `metadata.mcp.tool` 分别为 `"step1"` / `"step2"`）。把断言改为：

```ts
// 二级：两个 tool 子标签（工具名 + 调用序号）
await expect(panel.getByRole("tab", { name: /step1 #1/ })).toBeVisible()
await expect(panel.getByRole("tab", { name: /step2 #1/ })).toBeVisible()

// 切换 sub-tab 更新激活态
await panel.getByRole("tab", { name: /step2 #1/ }).click()
await expect(panel.getByRole("tab", { name: /step2 #1/ })).toHaveAttribute("aria-selected", "true")
```

（`getByRole("tab", { name: /step1 #1/ })` 使用子串正则，按钮内含序号 span，可命中。）

- [ ] **Step 3: 新增 e2e 用例——同一 tool 两次调用 → 面板两个 tab、各自 iframe 定格各自进度**

在 `test.describe("MCP Apps Panel")` 内新增：

```ts
test("shows each call instance as its own tab with isolated progress", async ({ page }) => {
  await setupTimeline(page, {
    settings: { newLayoutDesigns: true },
    messages: [
      userMessage(),
      assistantMessage([
        toolPart("prt_skill_dup", "skill", "completed", { name: "step-12" }),
        toolPart("prt_step1_first", "ui-server_step1", "running", {}, {
          metadata: {
            mcp: { server: "ui-server", tool: "step1", ui: { resourceUri: "ui://step1/progress.html", visibility: ["model", "app"] } },
            mcpProgress: { progress: 2, total: 5, message: "首次调用 2/5" },
          },
        }),
        toolPart("prt_step1_second", "ui-server_step1", "running", {}, {
          metadata: {
            mcp: { server: "ui-server", tool: "step1", ui: { resourceUri: "ui://step1/progress.html", visibility: ["model", "app"] } },
            mcpProgress: { progress: 4, total: 5, message: "二次调用 4/5" },
          },
        }),
      ]),
    ],
    mcpApps: stepMcpApps(["ui://step1/progress.html"]),
  })

  const panel = page.locator('[data-component="mcp-apps-panel"]')
  await expect(panel).toBeVisible()

  // 同一 tool 两次调用 → 两个带序号的二级 tab
  await expect(panel.getByRole("tab", { name: /step1 #1/ })).toBeVisible()
  await expect(panel.getByRole("tab", { name: /step1 #2/ })).toBeVisible()

  // 每个实例的 iframe 各自定格在对应那次调用的进度
  const frame1 = panel.getByRole("tab", { name: /step1 #1/ }).click().then(() => {
    return panel.locator('iframe[sandbox="allow-scripts"]').contentFrame()
  })
  await expect((await frame1).getByText("首次调用 2/5")).toBeVisible()
  await panel.getByRole("tab", { name: /step1 #2/ }).click()
  const frame2 = panel.locator('iframe[sandbox="allow-scripts"]').contentFrame()
  await expect(frame2.getByText("二次调用 4/5")).toBeVisible()
})
```

> 说明：mock `stepMcpApps` 的 `STEP_UI_HTML`（功能自包含 step-ui）会把手势后收到的 `notifications/progress` 渲染进 `#out`。实例隔离成立的条件是：`prt_step1_first` 与 `prt_step1_second` 事件 key 不同（`...:prt_step1_first` vs `...:prt_step1_second`），故第二次的进度不会覆盖第一次。

- [ ] **Step 4: 运行 e2e 全规格确认通过**

在 `packages/app` 目录运行：`bunx playwright test e2e/regression/mcp-apps-panel.spec.ts --workers=1`
预期 PASS：既有 4 条（含更新后的标签断言）+ 新增 1 条全部通过。

- [ ] **Step 5: 跑 app 全量类型检查（含 e2e）**

在 `packages/app` 目录运行：`bun typecheck; bun run typecheck:e2e`
预期 PASS。

- [ ] **Step 6: 提交**

```bash
git add packages/app/e2e/regression/mcp-apps-panel.spec.ts
git commit -m "test(app): cover per-instance call chain tabs and isolated progress"
```

---

## Self-Review

**1. 方案覆盖核对（对照需求）：**
- 对话流每份 UI 定格在对应那次调用 → Task 2（McpTool key 带 instanceID）+ Task 3（McpAppView key 带 instanceID），host 广播收敛为实例隔离 → 每份 iframe 只收自己的事件。✓
- 右侧 tab 展示调用链（每次调用一个 tab）→ Task 4（去重键 `skill::instanceID`，同 resourceUri 多实例各自成条）+ Task 5（tab 显示 toolName + 序号 #n）。✓
- 放弃 SEP-1865 resourceUri 单实例语义 → 上述去重与 tab id 均以 instanceID 为准。✓
- 同一 part 的 running→completed 更新仍合并（不产生重复 tab）→ Task 4 测试 "merges same-part updates" 显式覆盖。✓
- 面板自动切焦（latestExecuted 按 partID）→ 无需改动，天然按实例切换（每个实例独立 tab）。✓
- 现有 e2e 标签断言同步更新 → Task 6 Step 2。✓

**2. 占位扫描：** 无 "TBD"/"TODO"；每个代码步骤给出完整代码。Task 6 Step 3 的 `.then()` 链式取 frame 写法较绕，但给出完整可用代码，执行时无需猜测。

**3. 类型一致性：**
- `McpAppInfo.instanceID: string`（必填）在 Task 1 定义；Task 2（appKey 用 `info.instanceID`）、Task 3（`props.instanceID`）、Task 4（去重/`toolTabId` 用 `app.instanceID`）、Task 5（`selectTool(app: McpAppInfo)`）一致引用。`toolName?: string` 同理。
- `McpAppRendererInput.instanceID?: string` Task 2 定义，Task 2 内 renderApp 传参一致；`McpAppViewProps.instanceID?: string` Task 3 定义，Task 5 面板传参一致。
- push key（McpTool）= `${sessionID}:${server}/${resourceUri}:${instanceID}`，register key（McpAppView）= 同格式（sessionID 可选前缀 + 可选 instanceID 后缀）——Task 2/3 逐字符对齐。✓
- `toolTabId` = `server::resourceUri::instanceID`，Task 4 定义、Task 5 使用一致。✓

未发现跨任务命名不一致。
