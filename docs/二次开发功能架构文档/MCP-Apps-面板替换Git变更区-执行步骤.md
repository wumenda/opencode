# MCP Apps 面板替换 Git 变更区 — 执行步骤文档

> 适用范围：opencode 源码二次开发——将 Web 界面右上角侧面板的 Git 变更展示区域替换为 MCP Apps UI 展示区域。
> 前置文档：`MCP-Apps-概述.md`（协议规范）、`MCP-Apps-Web侧执行步骤.md`（Web 侧已落地实现）。
> 执行方式：按任务顺序执行，每个任务内遵循 TDD（先写失败测试→验证失败→最小实现→验证通过→提交）。
> 每 3-4 个任务向用户汇报进度，等待确认后继续。

---

## 1. 可行性分析

### 结论：可以实现，且改造量可控。

### 1.1 现有能力盘点

| 能力 | 状态 | 关键文件 |
|------|------|----------|
| MCP App iframe 沙箱渲染 | 已实现 | [mcp-app-view.tsx](../packages/app/src/components/mcp-app-view.tsx) |
| 工具内联 iframe（tool 下方） | 已实现 | [mcp-tool.tsx](../packages/session-ui/src/components/mcp-tool.tsx) |
| MCP App 渲染上下文 Provider | 已实现 | [mcp-app.tsx](../packages/session-ui/src/context/mcp-app.tsx) |
| 从 ToolPart 提取 App 信息 | 已实现 | `mcpAppFromPart()` in [mcp-tool.tsx](../packages/session-ui/src/components/mcp-tool.tsx) |
| 侧面板 Tab 系统（含折叠/展开） | 已实现 | [session-side-panel.tsx](../packages/app/src/pages/session/session-side-panel.tsx) |
| 侧面板状态管理（开/关、宽度） | 已实现 | [review-panel-v2-state.ts](../packages/app/src/pages/session/v2/review-panel-v2-state.ts) |
| 会话消息/Parts 数据访问 | 已实现 | `sync().data.message[id]` + `sync().data.part[msgId]` |

### 1.2 改造路径

当前侧面板的 Review Tab 渲染 `ReviewPanelV2`（Git Diff 面板）。改造方案：

```
替换前：
  SessionSidePanel
    └── review tab → ReviewPanelV2 (FileTree + DiffPreview)

替换后：
  SessionSidePanel
    └── review tab → McpAppsPanel (TabBar + McpAppView iframe)
```

核心改动点：
1. **新建** `McpAppsPanel` 组件——内部 Tab 切换不同 App iframe
2. **新建** MCP Apps 数据收集逻辑——从会话 Parts 中提取已完成 MCP 工具的 UI 信息
3. **修改** `session.tsx`——用 `McpAppsPanel` 替换 `reviewPanelV2` 作为面板内容
4. **修改** `SessionSidePanel`——Tab 标签从 "Review" 改为 "Apps"，移除文件树侧边栏开关
5. **保留** 工具内联 iframe 展示不变（`McpTool` 组件不改动）

### 1.3 双展示可行性

用户要求 MCP App 的 iframe 同时在两处展示：
- **工具执行下方**（内联）：已由 `McpTool` 组件实现，通过 `useMcpAppRenderer()` 渲染 `McpAppView`
- **侧面板区域**：新增 `McpAppsPanel`，直接使用 `McpAppView` 组件渲染

`McpAppView` 是自包含的——每个实例独立创建 MCP Client 连接、blob URL 和 AppBridge。两个实例并行运行不会冲突，App 内的状态独立维护。如果需要双展示共享状态，可通过 AppBridge 的 `sendToolResult` 机制分别初始化。

### 1.4 风险点

| 风险 | 等级 | 缓解 |
|------|------|------|
| 同一 App 多次调用产生多个 Tab | 中 | 按 `{server, resourceUri}` 去重，保留最新结果 |
| iframe 数量过多导致性能问题 | 低 | 非活跃 Tab 的 iframe 可延迟挂载（`deferContent` 模式） |
| MCP Server 未连接时 iframe 加载失败 | 低 | `McpAppView` 已有重试机制和错误状态展示 |
| 丢失 Git Diff 功能 | 中 | 可作为后续任务添加为独立 Tab，本期不做 |

---

## 2. 目标架构

```
packages/app/src/
├── pages/session/
│   ├── session.tsx                          # 修改：替换 reviewPanelV2 → mcpAppsPanel
│   ├── session-side-panel.tsx               # 修改：Tab 标签改为 Apps，移除 sidebar toggle
│   └── v2/
│       ├── mcp-apps-panel-state.ts          # 新建：面板状态（活跃 Tab、去重逻辑）
│       └── mcp-apps-panel.tsx               # 新建：面板组件（TabBar + McpAppView）
└── components/
    └── mcp-app-view.tsx                     # 不修改（已有 iframe 渲染器）

packages/app/src/i18n/
└── en.ts                                    # 修改：新增 i18n key
```

### 数据流

```
sync().data.message[sessionID]     → Message[]（消息记录列表）
sync().data.part[message.id]       → Part[]（每条消息的 Parts）
    ↓ 遍历所有 Parts
    ↓ 过滤 type === "tool" && state.status === "completed"
    ↓ mcpAppFromPart(part) 提取 { server, resourceUri, fallbackData }
    ↓ 去重（按 server + resourceUri，保留最新）
    ↓
McpAppsPanel
    ├── TabBar（每个 App 一个 Tab）
    └── McpAppView（活跃 Tab 的 iframe）
```

---

## 3. 实施任务

### Task 1: 创建 MCP Apps 面板状态管理

**Files:**
- Create: `packages/app/src/pages/session/v2/mcp-apps-panel-state.ts`

- [ ] **Step 1: 创建状态管理文件**

```ts
// packages/app/src/pages/session/v2/mcp-apps-panel-state.ts
import { createSignal } from "solid-js"
import type { McpAppInfo } from "@opencode-ai/session-ui/components/mcp-tool"

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
```

- [ ] **Step 2: 运行 typecheck 验证**

Run: `cd packages/app && bun typecheck`
Expected: PASS（无类型错误）

- [ ] **Step 3: 提交**

```bash
git add packages/app/src/pages/session/v2/mcp-apps-panel-state.ts
git commit -m "feat(app): add MCP apps panel state management"
```

---

### Task 2: 创建 MCP Apps 数据收集 Hook

**Files:**
- Create: `packages/app/src/pages/session/v2/use-mcp-apps.ts`

- [ ] **Step 1: 创建数据收集 Hook**

```ts
// packages/app/src/pages/session/v2/use-mcp-apps.ts
import { createMemo } from "solid-js"
import type { Accessor } from "solid-js"
import type { ToolPart } from "@opencode-ai/sdk/v2"
import { mcpAppFromPart, type McpAppInfo } from "@opencode-ai/session-ui/components/mcp-tool"
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
```

- [ ] **Step 2: 运行 typecheck 验证**

Run: `cd packages/app && bun typecheck`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add packages/app/src/pages/session/v2/use-mcp-apps.ts
git commit -m "feat(app): add useMcpApps hook to collect MCP app UIs from session"
```

---

### Task 3: 添加 i18n Keys

**Files:**
- Modify: `packages/app/src/i18n/en.ts`

- [ ] **Step 1: 在 en.ts 中添加 i18n key**

在 `mcp.app.connectTimeout` 行之后添加：

```ts
  "mcp.app.panel.empty": "No MCP apps available",
  "mcp.app.panel.title": "Apps",
  "mcp.app.panel.tabLabel": "{{server}} / {{tool}}",
```

- [ ] **Step 2: 运行 typecheck 验证**

Run: `cd packages/app && bun typecheck`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add packages/app/src/i18n/en.ts
git commit -m "feat(app): add i18n keys for MCP apps panel"
```

---

### Task 4: 创建 McpAppsPanel 组件

**Files:**
- Create: `packages/app/src/pages/session/v2/mcp-apps-panel.tsx`

- [ ] **Step 1: 创建面板组件**

```tsx
// packages/app/src/pages/session/v2/mcp-apps-panel.tsx
import { For, Show, createEffect, createMemo, type JSX } from "solid-js"
import { Tabs } from "@opencode-ai/ui/tabs"
import { Icon } from "@opencode-ai/ui/v2/icon"
import { useLanguage } from "@/context/language"
import { McpAppView } from "@/components/mcp-app-view"
import { appTabId, type McpAppsPanelState } from "./mcp-apps-panel-state"
import type { McpAppInfo } from "@opencode-ai/session-ui/components/mcp-tool"
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js"

export type McpAppsPanelProps = {
  apps: () => McpAppInfo[]
  state: McpAppsPanelState
}

export function McpAppsPanel(props: McpAppsPanelProps): JSX.Element {
  const language = useLanguage()
  const apps = props.apps
  const state = props.state

  // 当 apps 列表变化时，自动选中第一个 Tab（如果当前没有选中项或选中项已不存在）
  createEffect(() => {
    const list = apps()
    const active = state.activeTabId()
    if (list.length === 0) {
      state.setActiveTabId(undefined)
      return
    }
    const exists = active && list.some((app) => appTabId(app) === active)
    if (!exists) state.setActiveTabId(appTabId(list[0]))
  })

  const activeApp = createMemo(() => {
    const active = state.activeTabId()
    if (!active) return undefined
    return apps().find((app) => appTabId(app) === active)
  })

  return (
    <div class="flex h-full flex-col overflow-hidden bg-v2-background-bg-base contain-strict">
      <Show
        when={apps().length > 0}
        fallback={
          <div class="flex h-full flex-col items-center justify-center gap-3 text-center">
            <Icon name="mcp" class="size-8 opacity-10" />
            <div class="text-14-regular text-v2-text-text-muted max-w-56">
              {language.t("mcp.app.panel.empty")}
            </div>
          </div>
        }
      >
        {/* Tab 栏 */}
        <div class="flex shrink-0 items-center gap-1 border-b border-v2-border-border-base px-2">
          <For each={apps()}>
            {(app) => {
              const id = appTabId(app)
              const isActive = () => state.activeTabId() === id
              return (
                <button
                  type="button"
                  class="flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2 text-13-medium transition-colors"
                  classList={{
                    "border-v2-border-border-bold text-v2-text-text-base": isActive(),
                    "border-transparent text-v2-text-text-muted hover:text-v2-text-text-base": !isActive(),
                  }}
                  onClick={() => state.setActiveTabId(id)}
                >
                  <Icon name="mcp" class="size-3.5" />
                  <span>{app.server}</span>
                </button>
              )
            }}
          </For>
        </div>

        {/* 活跃 App 的 iframe 渲染 */}
        <div class="min-h-0 flex-1 overflow-hidden">
          <Show when={activeApp()}>
            {(app) => (
              <McpAppView
                server={app().server}
                resourceUri={app().resourceUri}
                fallbackData={
                  typeof app().fallbackData === "object" && app().fallbackData !== null
                    ? (app().fallbackData as CallToolResult)
                    : undefined
                }
              />
            )}
          </Show>
        </div>
      </Show>
    </div>
  )
}
```

- [ ] **Step 2: 运行 typecheck 验证**

Run: `cd packages/app && bun typecheck`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add packages/app/src/pages/session/v2/mcp-apps-panel.tsx
git commit -m "feat(app): add McpAppsPanel component with tabbed iframe rendering"
```

---

### Task 5: 在 session.tsx 中接入 McpAppsPanel

**Files:**
- Modify: `packages/app/src/pages/session.tsx`

- [ ] **Step 1: 添加 import**

在 session.tsx 顶部 import 区添加：

```ts
import { McpAppsPanel } from "@/pages/session/v2/mcp-apps-panel"
import { createMcpAppsPanelState } from "@/pages/session/v2/mcp-apps-panel-state"
import { useMcpApps } from "@/pages/session/v2/use-mcp-apps"
```

- [ ] **Step 2: 创建面板状态和 Apps 数据源**

在 `reviewV2State` 创建之后（约 L1295 附近）添加：

```ts
  const mcpAppsState = createMcpAppsPanelState()
  const mcpApps = useMcpApps(() => params.id)
```

- [ ] **Step 3: 创建 mcpAppsPanel getter**

在 `reviewPanelV2` 定义之后（约 L1357 附近）添加：

```ts
  const mcpAppsPanel = () => (
    <div class="flex flex-col h-full overflow-hidden bg-v2-background-bg-base contain-strict">
      <McpAppsPanel apps={mcpApps} state={mcpAppsState} />
    </div>
  )
```

- [ ] **Step 4: 替换 SidePanel 的 panel 内容**

在 `newSessionDesign()` 分支中（约 L2328-L2351），将 `reviewPanel={reviewPanelV2}` 替换为 `reviewPanel={mcpAppsPanel}`：

```tsx
                    <SessionSidePanel
                      canReview={() => mcpApps().length > 0}
                      diffs={() => []}
                      diffsReady={() => true}
                      empty={() => ""}
                      hasReview={() => mcpApps().length > 0}
                      reviewHasFocusableContent={() => mcpApps().length > 0}
                      reviewCount={() => mcpApps().length}
                      reviewPanel={mcpAppsPanel}
                      activeDiff={undefined}
                      focusReviewDiff={() => {}}
                      reviewSnap={ui.reviewSnap}
                      size={size}
                      stacked={desktopV2PanelLayout().stacked}
                    />
```

注意：移除了 `reviewSidebarToggle` prop（不传则不渲染折叠按钮），移除了 `fileBrowserState` prop。

- [ ] **Step 5: 运行 typecheck 验证**

Run: `cd packages/app && bun typecheck`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add packages/app/src/pages/session.tsx
git commit -m "feat(app): wire McpAppsPanel into session layout, replacing review panel"
```

---

### Task 6: 修改 SessionSidePanel Tab 标签

**Files:**
- Modify: `packages/app/src/pages/session/session-side-panel.tsx`

- [ ] **Step 1: 修改 Review Tab 标签文本**

在 `SessionSidePanel` 中找到 Review Tab 渲染（约 L563-L573），将标签内容改为 Apps：

```tsx
                            <Show when={reviewTab() && props.canReview()}>
                              <Tabs.Trigger
                                value="review"
                                id={reviewTabID}
                                aria-controls={activeTab() === "review" ? reviewTabPanelID : undefined}
                              >
                                {language.t("mcp.app.panel.title")}
                              </Tabs.Trigger>
                            </Show>
```

- [ ] **Step 2: 运行 typecheck 验证**

Run: `cd packages/app && bun typecheck`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add packages/app/src/pages/session/session-side-panel.tsx
git commit -m "feat(app): change review tab label to Apps for MCP apps panel"
```

---

### Task 7: 修改面板打开条件

**Files:**
- Modify: `packages/app/src/pages/session.tsx`

当前面板的显示条件依赖 `canReview()`（检查是否有 project）。MCP Apps 面板不需要 project，只需要有 session。

- [ ] **Step 1: 修改 canReview 逻辑（仅针对 V2 布局）**

在 V2 布局的 `SessionSidePanel` 调用处（约 L2328），将 `canReview` 改为始终返回 true（只要有 sessionID）：

```tsx
                      canReview={() => !!params.id}
```

注意：仅在 `newSessionDesign()` 分支中修改。旧布局保持不变。

- [ ] **Step 2: 运行 typecheck 验证**

Run: `cd packages/app && bun typecheck`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add packages/app/src/pages/session.tsx
git commit -m "fix(app): allow MCP apps panel without project requirement"
```

---

### Task 8: 处理面板自动展开逻辑

**Files:**
- Modify: `packages/app/src/pages/session.tsx`

当前 `desktopV2ReviewOpen` 依赖 `view().reviewPanel.opened()`。当 MCP 工具执行完成且有 UI 时，应自动展开面板。

- [ ] **Step 1: 添加自动展开 effect**

在 `mcpApps` 定义之后添加：

```ts
  // 当首次出现 MCP App UI 时，自动展开侧面板
  createEffect(
    on(
      () => mcpApps().length,
      (count, prev) => {
        if (prev === undefined && count > 0) {
          if (!view().reviewPanel.opened()) view().reviewPanel.open()
        }
      },
    ),
  )
```

- [ ] **Step 2: 运行 typecheck 验证**

Run: `cd packages/app && bun typecheck`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add packages/app/src/pages/session.tsx
git commit -m "feat(app): auto-expand panel when first MCP app UI appears"
```

---

### Task 9: 调整 McpAppView 样式适配面板全高

**Files:**
- Modify: `packages/app/src/components/mcp-app-view.tsx`

当前 `McpAppView` 的 iframe 固定高度为 `h-80`（320px）。在面板中需要填满可用高度。

- [ ] **Step 1: 添加 fillHeight prop**

修改 `McpAppViewProps` 和渲染逻辑：

```tsx
export type McpAppViewProps = {
  server: string
  resourceUri: string
  fallbackData?: CallToolResult
  onError?: (message: string) => void
  /** 填满父容器高度（用于面板模式），默认 false 使用固定 h-80。 */
  fillHeight?: boolean
}
```

在 `return` 中修改容器和 iframe 的 class：

```tsx
  return (
    <div
      class="w-full overflow-hidden rounded-xl border-[0.5px] border-v2-border-border-base bg-v2-background-bg-layer-01"
      classList={{ "h-full flex flex-col": props.fillHeight }}
    >
      <Show when={phase() === "loading"}>
        <div
          class="flex items-center justify-center gap-2 text-v2-text-text-muted"
          classList={{ "h-80": !props.fillHeight, "flex-1": props.fillHeight }}
        >
          <Spinner class="size-4" />
          <span class="text-[13px] font-[440] leading-5 tracking-[-0.04px]">{language.t("mcp.app.loading")}</span>
        </div>
      </Show>
      <Show when={phase() === "error"}>
        <div
          class="flex flex-col items-center justify-center gap-2 text-v2-text-text-muted"
          classList={{ "h-80": !props.fillHeight, "flex-1": props.fillHeight }}
        >
          <span class="text-[13px] font-[440] leading-5 tracking-[-0.04px]">{errorMessage()}</span>
          <button
            type="button"
            class="cursor-pointer border-none bg-transparent p-0 text-[13px] font-[530] leading-5 tracking-[-0.04px] text-v2-text-text-base underline"
            onClick={() => void start()}
          >
            {language.t("mcp.app.retry")}
          </button>
        </div>
      </Show>
      <Show when={blobUrl()}>
        <iframe
          src={blobUrl()}
          sandbox="allow-scripts"
          class="w-full border-0 bg-v2-background-bg-layer-01"
          classList={{ "h-80": !props.fillHeight, "flex-1": props.fillHeight }}
          onLoad={(event) => void onIframeLoad(event.currentTarget)}
        />
      </Show>
    </div>
  )
```

- [ ] **Step 2: 在 McpAppsPanel 中传入 fillHeight**

修改 `mcp-apps-panel.tsx` 中的 `McpAppView` 调用：

```tsx
              <McpAppView
                server={app().server}
                resourceUri={app().resourceUri}
                fallbackData={
                  typeof app().fallbackData === "object" && app().fallbackData !== null
                    ? (app().fallbackData as CallToolResult)
                    : undefined
                }
                fillHeight
              />
```

- [ ] **Step 3: 运行 typecheck 验证**

Run: `cd packages/app && bun typecheck`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add packages/app/src/components/mcp-app-view.tsx packages/app/src/pages/session/v2/mcp-apps-panel.tsx
git commit -m "feat(app): add fillHeight prop to McpAppView for panel full-height mode"
```

---

### Task 10: E2E 测试 — 面板渲染验证

**Files:**
- Create: `packages/app/e2e/regression/mcp-apps-panel.spec.ts`

- [ ] **Step 1: 编写 E2E 测试**

```ts
// packages/app/e2e/regression/mcp-apps-panel.spec.ts
import { test, expect } from "@playwright/test"
import { fixtureSession, fixtureMcpAppTool } from "../helpers/fixtures"

test.describe("MCP Apps Panel", () => {
  test("shows Apps tab in side panel", async ({ page }) => {
    const session = await fixtureSession(page, { design: "v2" })
    await session.openSidePanel()

    await expect(page.getByRole("tab", { name: "Apps" })).toBeVisible()
  })

  test("renders MCP app iframe in panel after tool execution", async ({ page }) => {
    const session = await fixtureSession(page, { design: "v2" })
    await session.sendMessage("show me the dashboard")

    // Wait for the MCP tool to complete and panel to show
    await expect(page.locator('[data-component="mcp-apps-panel"] iframe[sandbox="allow-scripts"]')).toBeVisible()
    await expect(page.locator('[data-component="mcp-apps-panel"] iframe[src^="blob:"]')).toBeVisible()
  })

  test("switches between multiple app tabs", async ({ page }) => {
    const session = await fixtureSession(page, { design: "v2" })
    await session.sendMessage("show dashboard")
    await session.sendMessage("show settings")

    const tabs = page.locator('[data-component="mcp-apps-panel"] button[role="tab"]')
    await expect(tabs).toHaveCount(2)

    // Click the second tab
    await tabs.nth(1).click()
    await expect(page.locator('[data-component="mcp-apps-panel"] iframe')).toBeVisible()
  })

  test("shows empty state when no MCP apps", async ({ page }) => {
    const session = await fixtureSession(page, { design: "v2" })
    await session.openSidePanel()

    await expect(page.getByText("No MCP apps available")).toBeVisible()
  })
})
```

注意：`fixtureMcpAppTool` 等测试辅助函数需要根据实际测试基础设施调整。如果现有的 E2E helpers 不支持，可先写测试骨架，后续完善。

- [ ] **Step 2: 运行测试验证（如 fixtures 就绪）**

Run: `cd packages/app && bunx playwright test e2e/regression/mcp-apps-panel.spec.ts`
Expected: PASS（如果 fixtures 未就绪，先跳过，标记为 TODO）

- [ ] **Step 3: 提交**

```bash
git add packages/app/e2e/regression/mcp-apps-panel.spec.ts
git commit -m "test(app): add E2E tests for MCP apps panel rendering and tab switching"
```

---

### Task 11: 回归验证 — 内联 iframe 不受影响

**Files:**
- 无新建文件，仅验证

- [ ] **Step 1: 运行现有 MCP App E2E 测试**

Run: `cd packages/app && bunx playwright test e2e/regression/session-timeline-mcp-app.spec.ts`
Expected: PASS（内联 iframe 渲染不受面板改动影响）

- [ ] **Step 2: 运行 typecheck**

Run: `cd packages/app && bun typecheck`
Expected: PASS

- [ ] **Step 3: 手动验证**

1. 启动开发服务器
2. 打开会话页面
3. 发送消息触发 MCP 工具（如 ui-server 的 `show_dashboard`）
4. 确认：
   - 工具执行下方显示 iframe（内联，已有功能）
   - 右侧面板自动展开，显示 "Apps" Tab
   - 面板内 Tab 栏显示 server 名称
   - 点击 Tab 切换 iframe
   - 无 MCP 工具时显示空状态

---

## 4. 文件变更汇总

| 文件 | 操作 | 说明 |
|------|------|------|
| `packages/app/src/pages/session/v2/mcp-apps-panel-state.ts` | 新建 | 面板状态管理 + 去重逻辑 |
| `packages/app/src/pages/session/v2/use-mcp-apps.ts` | 新建 | 从会话 Parts 收集 MCP App UI |
| `packages/app/src/pages/session/v2/mcp-apps-panel.tsx` | 新建 | 面板组件（TabBar + McpAppView） |
| `packages/app/src/pages/session.tsx` | 修改 | 替换 reviewPanelV2 → mcpAppsPanel |
| `packages/app/src/pages/session/session-side-panel.tsx` | 修改 | Tab 标签改为 Apps |
| `packages/app/src/components/mcp-app-view.tsx` | 修改 | 添加 fillHeight prop |
| `packages/app/src/i18n/en.ts` | 修改 | 添加面板相关 i18n key |
| `packages/app/e2e/regression/mcp-apps-panel.spec.ts` | 新建 | E2E 测试 |

---

## 5. 设计决策记录

### D1: 按 {server, resourceUri} 去重

同一 MCP Server 的同一 UI 资源只保留一个 Tab，使用最新一次工具调用的结果（`fallbackData`）。

**理由**：避免同一 App 多次调用产生大量 Tab，保持面板简洁。

**替代方案**：每次调用都产生独立 Tab（以 part ID 为 key）——Tab 数量可能过多，且用户难以区分。

### D2: 面板内 Tab 而非 SidePanel Tab

MCP Apps 的 Tab 切换在面板组件内部实现，不复用 `SessionSidePanel` 的 Tab 系统。

**理由**：`SessionSidePanel` 的 Tab 系统设计用于文件 Tab（可拖拽排序、可关闭），与 MCP App Tab 的语义不同。内部 Tab 更简单且自包含。

### D3: 保留内联 iframe 展示

工具执行下方的 iframe 展示（`McpTool` 组件）不修改，面板是额外的展示位置。

**理由**：用户明确要求两处同时展示。两个 `McpAppView` 实例各自独立连接 MCP Server，不共享状态。如果需要状态同步，可通过 AppBridge 的 `sendToolResult` 分别初始化。

### D4: 移除 Git Diff 功能

本期将 Git Diff 面板完全替换为 MCP Apps 面板。Git Diff 功能在旧布局（`!newSessionDesign()`）中仍然保留。

**理由**：用户明确要求"替换"。如需保留 Git Diff，可作为后续任务在 SidePanel 中添加独立的 "Review" Tab。

### D5: 自动展开面板

当首次出现 MCP App UI（`mcpApps().length` 从 0 变为 >0）时，自动展开侧面板。

**理由**：用户触发了 MCP 工具后，应立即可见结果。后续的手动折叠/展开仍由用户控制。

---

## 6. 后续可选增强（不在本期范围）

1. **Git Diff 作为独立 Tab 恢复**：在 SidePanel 中添加 "Review" Tab，与 "Apps" Tab 并存
2. **Tab 关闭功能**：允许用户关闭不需要的 App Tab
3. **Tab 拖拽排序**：复用 SidePanel 的 SortableTab 机制
4. **iframe 懒加载**：非活跃 Tab 延迟挂载 iframe，优化性能
5. **状态同步**：内联 iframe 和面板 iframe 之间的状态同步（通过 SharedWorker 或 BroadcastChannel）
6. **多语言支持**：为新增的 i18n key 添加其他语言翻译
