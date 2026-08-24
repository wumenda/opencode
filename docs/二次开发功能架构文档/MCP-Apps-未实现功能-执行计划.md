# MCP Apps 未实现功能 · 执行计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现未支持清单（[MCP-Apps-未支持功能清单.md](./MCP-Apps-%E6%9C%AA%E6%94%AF%E6%8C%81%E5%8A%9F%E8%83%BD%E6%B8%85%E5%8D%95.md)）中可在前端落地/可测的 6 项：sampling 能力钩子、敏感权限透传、hostContext 实时订阅、tool-cancelled 推送、update-model-context 上下文落地、request-display-mode 协商。

**Architecture:** 改动集中在 `packages/app`（`src/components/mcp-app-view.tsx` 为宿主桥接核心）与 `packages/session-ui`（`src/context/*` 为宿主注册表/上下文、`src/components/mcp-tool.tsx` 为工具 part 渲染）。每项以 TDD 推进：先加可测纯逻辑/能力函数测试，再接线进 `McpAppView`/`McpTool`。sampling 与 update-model-context 属基础设施闸口，本计划实现**机制 + 可插拔宿主钩子**，真实 LLM provider / 模型上下文合并是宿主集成点（在任务内明确边界，非空占位）。

**Tech Stack:** SolidJS；`@modelcontextprotocol/ext-apps@1.7.5`（AppBridge 已含 `oncreatesamplingmessage` / `sendToolCancelled` / `setHostContext` / `onrequestdisplaymode` setter）；`@opencode-ai/ui/theme/context` 的 `useTheme`；`bun:test`；Playwright E2E（已装 Chromium）。

---

### Task 1: sampling 能力钩子（宿主可插拔）

目标：让 McpAppView 在宿主提供 `onSampling` 时声明 `sampling` 能力并接通 AppBridge `oncreatesamplingmessage`；未提供则保持不声明（语义一致，不虚报）。真实 LLM 由宿主注入。

**Files:**
- Modify: `packages/app/src/lib/mcp-apps/bridge.ts`
- Test: `packages/app/src/lib/mcp-apps/bridge.test.ts`
- Modify: `packages/app/src/components/mcp-app-view.tsx`

- [ ] **Step 1: 写失败测试**（追加到 bridge.test.ts）

```ts
test("declares sampling when a handler is enabled", () => {
  const caps = hostCapabilities({ openLink: false, downloadFile: false, message: false, logging: false, sampling: true })
  expect(caps.sampling).toEqual({})
  const off = hostCapabilities({ openLink: true, downloadFile: true, message: true, logging: true, sampling: false })
  expect(off.sampling).toBeUndefined()
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd packages/app && bun test src/lib/mcp-apps/bridge.test.ts`
Expected: FAIL——`hostCapabilities` 不接受 `sampling` 参数或未输出 `sampling`。

- [ ] **Step 3: 最小实现**（改 `bridge.ts`）

```ts
export type HostCapabilities = {
  openLinks?: Record<string, never>
  downloadFile?: Record<string, never>
  message?: Record<string, never>
  serverTools: Record<string, never>
  serverResources: Record<string, never>
  logging?: Record<string, never>
  sampling?: { tools?: {} }
}

export function hostCapabilities(flags: {
  openLink: boolean
  downloadFile: boolean
  message: boolean
  logging: boolean
  sampling?: boolean
}): HostCapabilities {
  return {
    ...(flags.openLink ? { openLinks: {} } : {}),
    ...(flags.downloadFile ? { downloadFile: {} } : {}),
    ...(flags.message ? { message: {} } : {}),
    serverTools: {},
    serverResources: {},
    ...(flags.logging ? { logging: {} } : {}),
    ...(flags.sampling ? { sampling: { tools: {} } } : {}),
  }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd packages/app && bun test src/lib/mcp-apps/bridge.test.ts`
Expected: PASS（含原有用例）。

- [ ] **Step 5: 接线进组件**（改 `mcp-app-view.tsx`）
  ① 新增 prop，并 import 类型：

```ts
export type McpAppViewProps = {
  server: string
  resourceUri: string
  fallbackData?: CallToolResult
  onError?: (message: string) => void
  fillHeight?: boolean
  theme?: "light" | "dark"
  /** 宿主提供的 LLM 采样实现（AppBridge oncreatesamplingmessage）。未提供时不声明 sampling 能力。 */
  onSampling?: (request: CreateMessageRequest["params"]) => Promise<CreateMessageResult | CreateMessageResultWithTools>
}
```

```ts
import type { CreateMessageRequest, CreateMessageResult, CreateMessageResultWithTools } from "@modelcontextprotocol/sdk/types.js"
```

  ② 构造 AppBridge 的 capability 行改为含 sampling 开关，并在构造后按需挂 handler：

```ts
const next = new AppBridge(
      client,
      { name: "opencode", version: "1.0.0" },
      hostCapabilities({ openLink: true, downloadFile: true, message: true, logging: true, sampling: !!props.onSampling }),
      { hostContext },
    )
    if (props.onSampling) {
      next.oncreatesamplingmessage = async (params) => props.onSampling!(params)
    }
```

- [ ] **Step 6: 编译 + 回归**

Run: `cd packages/app && bun test src/lib/mcp-apps/bridge.test.ts`（全过）
Run: `cd packages/app && bunx tsc --noEmit -p tsconfig.json`，仅允许既有 `src/custom-elements.d.ts` 报错；`bridge.ts`/`mcp-app-view.tsx` 不得有新类型错误。

- [ ] **Step 7: 提交**

```bash
cd packages/app
git add src/lib/mcp-apps/bridge.ts src/lib/mcp-apps/bridge.test.ts src/components/mcp-app-view.tsx
git commit -m "feat(mcp-apps): add pluggable sampling capability hook"
```

---

### Task 2: 敏感权限透传（camera/mic/geo/clipboard → iframe allow）

目标：把资源 `_meta.ui.permissions` 请求的能力映射为 iframe 的 Permission-Policy `allow` 属性（`camera` / `microphone` / `geolocation` / `clipboard-write`）。

**Files:**
- Modify: `packages/app/src/lib/mcp-apps/resource.ts`
- Test: `packages/app/src/lib/mcp-apps/resource.test.ts`
- Modify: `packages/app/src/components/mcp-app-view.tsx`

- [ ] **Step 1: 写失败测试**（追加到 resource.test.ts `buildSandboxedHtml` describe）

```ts
test("maps requested resource permissions into an iframe allow attribute", () => {
  const sandbox = buildSandboxedHtml("<html><head></head><body></body></html>", {
    permissions: { clipboardWrite: {}, camera: {}, microphone: {}, geolocation: {} },
  })
  expect(sandbox.allow).toContain("camera")
  expect(sandbox.allow).toContain("microphone")
  expect(sandbox.allow).toContain("geolocation")
  expect(sandbox.allow).toContain("clipboard-write")
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd packages/app && bun test src/lib/mcp-apps/resource.test.ts`
Expected: FAIL——`buildSandboxedHtml` 返回对象没有 `allow`。

- [ ] **Step 3: 最小实现**（改 `resource.ts` 的 `buildSandboxedHtml`）

```ts
/** 把资源声明的权限映射为 iframe Permission-Policy allow 属性值。 */
export function buildAllow(permissions?: SandboxOptions["permissions"]): string {
  const parts: string[] = []
  if (permissions?.clipboardWrite) parts.push("clipboard-write")
  if (permissions?.camera) parts.push("camera")
  if (permissions?.microphone) parts.push("microphone")
  if (permissions?.geolocation) parts.push("geolocation")
  return parts.join("; ")
}

export function buildSandboxedHtml(
  html: string,
  opts?: SandboxOptions,
): { url: string; revoke: () => void; html: string; sandbox: string; allow: string } {
  const htmlOut = injectCsp(html, opts?.csp)
  const blob = new Blob([htmlOut], { type: "text/html" })
  const url = URL.createObjectURL(blob)
  const allows = ["allow-scripts"]
  if (opts?.permissions?.clipboardWrite) allows.push("allow-clipboard-write")
  return {
    url,
    revoke: () => URL.revokeObjectURL(url),
    html: htmlOut,
    sandbox: allows.join(" "),
    allow: buildAllow(opts?.permissions),
  }
}
```

- [ ] **Step 4: 接线进组件**（改 `mcp-app-view.tsx`）
  ① 新增 signal `const [allow, setAllow] = createSignal("")`。
  ② 在 `start()` 的 text 分支把 `s.allow` 放入 `setAllow`（blob 分支置空）：

```ts
if (html.text) {
  const s = buildSandboxedHtml(html.text, { csp: html.meta?.ui?.csp, permissions: html.meta?.ui?.permissions })
  url = s.url
  sandboxTokens = s.sandbox
  revoke = s.revoke
  setAllow(s.allow)
}
```

  ③ iframe 加 `allow={allow()}`：

```tsx
<iframe
  src={blobUrl()}
  sandbox={sandbox()}
  allow={allow()}
  ...
/>
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd packages/app && bun test src/lib/mcp-apps/resource.test.ts`
Expected: PASS。

- [ ] **Step 6: 编译 + 提交**

Run: `cd packages/app && bunx tsc --noEmit -p tsconfig.json`（只允许既有 custom-elements.d.ts 报错）
```bash
git add src/lib/mcp-apps/resource.ts src/lib/mcp-apps/resource.test.ts src/components/mcp-app-view.tsx
git commit -m "feat(mcp-apps): pass requested camera/mic/geo/clipboard onto iframe allow"
```

---

### Task 3: hostContext 实时订阅（主题 + 容器尺寸）

目标：McpAppView 订阅宿主主题与自身容器尺寸，变化时调用 `bridge.setHostContext` 推送 `host-context-changed`。

**Files:**
- Create: `packages/app/src/lib/mcp-apps/host-context-utils.ts`
- Test: `packages/app/src/lib/mcp-apps/host-context-utils.test.ts`
- Modify: `packages/app/src/components/mcp-app-view.tsx`

- [ ] **Step 1: 写失败测试**（新建 host-context-utils.test.ts）

```ts
import { describe, expect, test } from "bun:test"
import { toMcpTheme } from "./host-context-utils"

describe("toMcpTheme", () => {
  test("maps host light/dark mode to an MCP theme label", () => {
    expect(toMcpTheme("light")).toBe("light")
    expect(toMcpTheme("dark")).toBe("dark")
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd packages/app && bun test src/lib/mcp-apps/host-context-utils.test.ts`
Expected: FAIL——模块不存在。

- [ ] **Step 3: 最小实现**（新建 host-context-utils.ts）

```ts
/** 把 ui theme context 的 mode 规整为 McpUiTheme（"light"|"dark"）。 */
export function toMcpTheme(mode: "light" | "dark"): "light" | "dark" {
  return mode
}
```

- [ ] **Step 4: 接线进组件**（改 `mcp-app-view.tsx`）
  ① import：`import { useTheme } from "@opencode-ai/ui/theme/context"`；`import { toMcpTheme } from "@/lib/mcp-apps/host-context-utils"`。
  ② 组件内读取主题并订阅：

```ts
const themeCtx = useTheme()
const resolvedTheme = createMemo(() => toMcpTheme(themeCtx.mode()))
```

  ③ 新增一个 `publishHostContext()` 与 ResizeObserver 订阅（该组件外层已有 `div` 容器；给该 div 加 `ref`）。文件顶部加：

```ts
let containerRef: HTMLDivElement | undefined
let resizeObserver: ResizeObserver | undefined

const publishHostContext = (width?: number, height?: number) => {
  void bridge?.setHostContext(
    buildHostContext({ width, height, theme: resolvedTheme(), locale: language.intl() }),
  )
}

const onResize = () => {
  if (containerRef) publishHostContext(containerRef.clientWidth || undefined, containerRef.clientHeight || undefined)
}

createEffect(() => {
  // 主题变化实时推送给 App
  void resolvedTheme()
  publishHostContext()
})
```

  ④ 组件外层 div 加 `ref={containerRef}`（保持已有 class 不变）。
  ⑤ `onMount` 里启动 ResizeObserver（浏览器环境才可用）：

```ts
onMount(() => {
  void start()
  unregister = host.register(appKey(), handleEvent)
  if (typeof ResizeObserver !== "undefined" && containerRef) {
    resizeObserver = new ResizeObserver(onResize)
    resizeObserver.observe(containerRef)
  }
})
onCleanup(() => {
  unregister?.()
  resizeObserver?.disconnect()
  void bridge?.close()
  void client?.close()
  revoke?.()
})
```

（`AppBridge.setHostContext` 只发变更字段；尺寸/主题未变化时不发通知。）

- [ ] **Step 5: 跑测试确认通过**

Run: `cd packages/app && bun test src/lib/mcp-apps/host-context-utils.test.ts`
Expected: PASS。

Run: `cd packages/app && bun test src/lib/mcp-apps`（回归不破坏既有）
Expected: 全过。

- [ ] **Step 6: 编译 + 提交**

```bash
git add src/lib/mcp-apps/host-context-utils.ts src/lib/mcp-apps/host-context-utils.test.ts src/components/mcp-app-view.tsx
git commit -m "feat(mcp-apps): push live theme and container size via host-context"
```

---

### Task 4: 运行中 `tool-cancelled` 推送

目标：错误（取消）状态时向已挂载 App 推 `ui/notifications/tool-cancelled`。因 ToolPart 取消表现为 `status:"error"`，需允许 App 在 error 状态继续渲染（保持挂载），并推取消原因。

**Files:**
- Modify: `packages/session-ui/src/context/mcp-app-host.tsx`
- Test: `packages/session-ui/src/context/mcp-app-host.test.ts`
- Modify: `packages/session-ui/src/components/mcp-tool.tsx`
- Test: `packages/session-ui/src/components/mcp-tool.test.ts`
- Modify: `packages/app/src/components/mcp-app-view.tsx`

- [ ] **Step 1: 写失败测试 A**（mcp-app-host.test.ts 追加）

```ts
test("routes tool-cancelled to the registered sink", () => {
  const reg = createMcpAppHostRegistry()
  const received: McpAppEvent[] = []
  const un = reg.register("a/ui://x", (e) => received.push(e))
  reg.push("a/ui://x", { type: "tool-cancelled", reason: "canceled" })
  expect(received).toEqual([{ type: "tool-cancelled", reason: "canceled" }])
  un()
})
```

- [ ] **Step 2: 写失败测试 B**（mcp-tool.test.ts 追加，先确认该文件 `part()` fixture 的用法）

```ts
test("returns app info for a cancelled (error) tool so it stays mounted", () => {
  const info = mcpAppFromPart(part({ status: "error", stateMetadata: { mcp: { server: "ui", ui: { resourceUri: "ui://x" } } } }))
  expect(info).toEqual({ server: "ui", resourceUri: "ui://x", fallbackData: undefined })
})
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd packages/session-ui && bun test src/context/mcp-app-host.test.ts`（A 失败：`tool-cancelled` 不在 `McpAppEvent` 联合）
Run: `cd packages/session-ui && bun test src/components/mcp-tool.test.ts`（B 失败：error 目前返回 undefined）

- [ ] **Step 4: 最小实现**

① `mcp-app-host.tsx` 的 `McpAppEvent` 联合追加：

```ts
export type McpAppEvent =
  | { type: "tool-input-partial"; arguments: Record<string, unknown> }
  | { type: "tool-result"; result: CallToolResult }
  | { type: "tool-cancelled"; reason: string }
```

② `mcp-tool.tsx`：
- `mcpAppFromPart` 的首行（currently `if (part.state.status !== "running" && part.state.status !== "completed") return`）改为也允许 `"error"`：

```ts
if (part.state.status !== "running" && part.state.status !== "completed" && part.state.status !== "error") return
```

- 新增 createEffect，error 时推送取消：

```ts
createEffect(() => {
  const info = app()
  if (!info) return
  if (props.part.state.status !== "error") return
  const err = (props.part.state as { error?: string }).error
  host.push(`${info.server}/${info.resourceUri}`, { type: "tool-cancelled", reason: err ?? "cancelled" })
})
```

③ 修正既有断言"error 返回 undefined"的用例为"error 返回 info"（见 Step 2 的 B 测试语义）。

- [ ] **Step 5: McpAppView 转发**（改 mcp-app-view.tsx 的 `forward`）

```ts
const forward = (event: McpAppEvent) => {
  if (!bridge) return
  if (event.type === "tool-input-partial") void bridge.sendToolInputPartial({ arguments: event.arguments })
  else if (event.type === "tool-result") void bridge.sendToolResult(event.result as CallToolResult)
  else if (event.type === "tool-cancelled") void bridge.sendToolCancelled({ reason: event.reason })
}
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd packages/session-ui && bun test src/context/mcp-app-host.test.ts src/components/mcp-tool.test.ts`
Expected: 全 PASS。
Run: `cd packages/app && bun test src/lib/mcp-apps`（回归）
Expected: 全过。

- [ ] **Step 7: 提交**

```bash
cd packages/session-ui
git add src/context/mcp-app-host.tsx src/context/mcp-app-host.test.ts src/components/mcp-tool.tsx src/components/mcp-tool.test.ts
cd ../app
git add src/components/mcp-app-view.tsx
git commit -m "feat(mcp-apps): push tool-cancelled to running apps on error"
```

---

### Task 5: `ui/update-model-context` 落地（宿主侧上下文 store）

目标：`onupdatemodelcontext` 不再仅打日志——把 App 提交的 `content / structuredContent` 写入一个宿主可读的 store，供后续并入模型上下文。

**Files:**
- Create: `packages/session-ui/src/context/mcp-model-context.tsx`
- Test: `packages/session-ui/src/context/mcp-model-context.test.ts`
- Modify: `packages/session-ui/src/context/index.ts`
- Modify: `packages/app/src/components/mcp-app-view.tsx`
- Modify: `packages/app/src/pages/directory-layout.tsx`

- [ ] **Step 1: 写失败测试**（新建 mcp-model-context.test.ts）

```ts
import { describe, expect, test } from "bun:test"
import { createModelContextStore } from "./mcp-model-context"

describe("createModelContextStore", () => {
  test("stores and overwrites the latest model context", () => {
    const store = createModelContextStore()
    expect(store.latest()).toBeUndefined()
    store.set({ content: [{ type: "text", text: "a" }] })
    store.set({ content: [{ type: "text", text: "b" }] })
    expect(store.latest()?.content).toEqual([{ type: "text", text: "b" }])
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd packages/session-ui && bun test src/context/mcp-model-context.test.ts`
Expected: FAIL——模块不存在。

- [ ] **Step 3: 最小实现**（新建 mcp-model-context.tsx）

```ts
import { createContext, useContext, type ParentProps } from "solid-js"

export type ModelContextUpdate = {
  content?: unknown[]
  structuredContent?: Record<string, unknown>
}

export type ModelContextHost = {
  /** 覆盖式写入最新一次上下文；每次 update 覆盖上一次。 */
  set: (update: ModelContextUpdate) => void
  /** 读取 App 最近一次提交的上下文（供宿主并入下一轮模型请求）。 */
  latest: () => ModelContextUpdate | undefined
}

export function createModelContextStore(): ModelContextHost {
  let value: ModelContextUpdate | undefined
  return {
    set(update) {
      value = update
    },
    latest() {
      return value
    },
  }
}

const McpModelContextContext = createContext<ModelContextHost>()

export function McpModelContextProvider(props: ParentProps<{ host: ModelContextHost }>) {
  return <McpModelContextContext.Provider value={props.host}>{props.children}</McpModelContextContext.Provider>
}

export function useMcpModelContext(): ModelContextHost {
  const host = useContext(McpModelContextContext)
  if (!host) throw new Error("McpModelContextProvider missing")
  return host
}
```

- [ ] **Step 4: 接线**
  ① `context/index.ts` 追加 `export * from "./mcp-model-context"`。
  ② `mcp-app-view.tsx`：import `useMcpModelContext`；顶部 `const modelCtx = useMcpModelContext()`；`onupdatemodelcontext` 改为写 store：

```ts
next.onupdatemodelcontext = async ({ content, structuredContent }, _extra) => {
  modelCtx.set({ content, structuredContent })
  return {}
}
```

  ③ `directory-layout.tsx`：模块作用域 `const modelContextHost = createModelContextStore()`；import `McpModelContextProvider, createModelContextStore`；在 `McpAppHostProvider` 外层再包：

```tsx
<McpModelContextProvider host={modelContextHost}>
  <McpAppHostProvider host={mcpAppHost}>
    <McpAppRendererProvider render={renderMcpApp}>
      <LocalProvider>{props.children}</LocalProvider>
    </McpAppRendererProvider>
  </McpAppHostProvider>
</McpModelContextProvider>
```

（真实"并入下一轮模型请求"由宿主读 `modelContextHost.latest()` 消费，属宿主/后端集成点。）

- [ ] **Step 5: 跑测试确认通过**

Run: `cd packages/session-ui && bun test src/context`
Expected: 全 PASS（含新 store 用例）。

- [ ] **Step 6: 编译 + 提交**

Run: `cd packages/app && bunx tsc --noEmit -p tsconfig.json`（仅允许既有 custom-elements.d.ts 报错）
```bash
cd packages/session-ui
git add src/context/mcp-model-context.tsx src/context/mcp-model-context.test.ts src/context/index.ts
cd ../app
git add src/components/mcp-app-view.tsx src/pages/directory-layout.tsx
git commit -m "feat(mcp-apps): persist update-model-context into a host-visible store"
```

---

### Task 6: `ui/request-display-mode` 显式协商

目标：接管 `onrequestdisplaymode`，按宿主支持的显示模式协商并返回实际生效模式；当前宿主仅支持 `inline`（未实现 fullscreen/pip 布局），但 handler 显式协商避免依赖隐式默认。

**Files:**
- Create: `packages/app/src/lib/mcp-apps/display-mode.ts`
- Test: `packages/app/src/lib/mcp-apps/display-mode.test.ts`
- Modify: `packages/app/src/components/mcp-app-view.tsx`

- [ ] **Step 1: 写失败测试**（新建 display-mode.test.ts）

```ts
import { describe, expect, test } from "bun:test"
import { resolveDisplayMode } from "./display-mode"

describe("resolveDisplayMode", () => {
  test("returns requested mode when supported by the host", () => {
    expect(resolveDisplayMode("inline", ["inline"])).toBe("inline")
  })
  test("falls back to inline for unsupported modes", () => {
    expect(resolveDisplayMode("fullscreen", ["inline"])).toBe("inline")
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd packages/app && bun test src/lib/mcp-apps/display-mode.test.ts`
Expected: FAIL——模块不存在。

- [ ] **Step 3: 最小实现**（新建 display-mode.ts）

```ts
export type DisplayMode = "inline" | "fullscreen" | "pip"

export const SUPPORTED_DISPLAY_MODES: DisplayMode[] = ["inline"]

/** 按宿主支持列表协商实际生效的显示模式；不支持则回退 inline。 */
export function resolveDisplayMode(requested: DisplayMode, supported: DisplayMode[]): DisplayMode {
  return supported.includes(requested) ? requested : "inline"
}
```

- [ ] **Step 4: 接线**（改 mcp-app-view.tsx，import `resolveDisplayMode, SUPPORTED_DISPLAY_MODES`）

```ts
next.onrequestdisplaymode = async ({ mode }) => {
  return { mode: resolveDisplayMode(mode, SUPPORTED_DISPLAY_MODES) }
}
```

（`McpUiRequestDisplayModeRequest["params"].mode` 类型即 `DisplayMode`；若 SDK 类型不允许 import，按 `mode as DisplayMode` 断言。）

- [ ] **Step 5: 跑测试确认通过**

Run: `cd packages/app && bun test src/lib/mcp-apps/display-mode.test.ts`
Expected: PASS。

- [ ] **Step 6: 编译 + 提交**

Run: `cd packages/app && bunx tsc --noEmit -p tsconfig.json`（仅允许既有 custom-elements.d.ts 报错）
```bash
git add src/lib/mcp-apps/display-mode.ts src/lib/mcp-apps/display-mode.test.ts src/components/mcp-app-view.tsx
git commit -m "feat(mcp-apps): explicitly negotiate ui/request-display-mode"
```

---

## Self-Review

- **覆盖性**：逐一对照未支持清单——sampling（Task 1）✅、敏感权限（Task 2）✅、hostContext 实时订阅（Task 3）✅、tool-cancelled（Task 4）✅、update-model-context（Task 5，宿主 store + 集成点）✅、request-display-mode（Task 6）✅。「架构性差异」与「契约对齐」不在执行范围（非协议功能）。

- **占位符扫描**：所有代码步骤均给出完整实现；sampling 与 update-model-context 的"真实 LLM / 并入模型上下文"明确标注为**宿主注入与消费点**（有真实 hook/store 与接线，非空占位）。

- **类型一致性**：`McpAppEvent` 新成员统一为 `{ type: "tool-cancelled"; reason: string }`，在 host/test/mcp-tool/McpAppView 四处一致；`hostCapabilities` 增 `sampling?: boolean`，调用侧 `McpAppView` 传 `sampling: !!props.onSampling`；`buildSandboxedHtml` 返回对象新增 `allow`，调用侧 `setAllow(s.allow)` 一致；`resolveDisplayMode(requested, supported)` 在函数与测试一致。

- **回归注意**：Task 4 改动既有 `mcp-tool.test.ts` 中"error 返回 undefined"用例的语义（改为返回 info），需同步更新该既有断言，避免撞车。