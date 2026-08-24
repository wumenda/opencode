# MCP Apps 功能补全 · 修复执行计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 opencode Host/Web 端从"MCP Apps 最小宿主"补齐为覆盖规范主要特性的可用实现（运行中流式 push、二进制渲染、hostContext、CSP 外部脚本域、`ui/message`、`ui/download-file`、teardown、能力一致性）。

**Architecture:** 全部改动集中在两层：`packages/app` 前端（`src/lib/mcp-apps/*` 纯函数 + `src/components/mcp-app-view.tsx` 组件 + `src/context` 渲染器/宿主注册表）与 `packages/session-ui`（`src/components/mcp-tool.tsx`、`src/context/*`）。每个任务都以"先写失败测试 → 跑通 → 最小实现 → 测试通过 → 提交"的 TDD 节奏推进。宿主(后端 relay)的 `resource/csp`、`sampling` relay 已就绪，本计划不再动后端契约。

**Tech Stack:** SolidJS 前端；`@modelcontextprotocol/ext-apps@1.7.5`（AppBridge）、`@modelcontextprotocol/sdk@1.29.0`；`bun:test` 单测；Playwright E2E（`packages/app/e2e`）。规则（project AGENTS）：前端优先 `createStore`；UI 文案必须走 i18n（`language.t`），不硬编码英文；工具调用并行。

**前提核对（动手前必须完成）**：任务中涉及 `AppBridge` 的 `ondownloadfile`、`sendDownloadFile`、`oncreatesamplingmessage` 等 handler/setter 的确切签名与存在性，请先读已安装包的声明文件确认，再按任务中的调用方式编写：

```
node_modules/@modelcontextprotocol/ext-apps/app-bridge/*.d.ts
```

（若仓库未安装依赖，先 `cd packages/app && bun install`。）

---

### Task 1: CSP 支持外部脚本域 `scriptDomains`

目标：目前 `script-src` 固定 `'unsafe-inline' 'self' data:`，官方 `ext-apps/client.js` 之类外部脚本被拦。让资源 `_meta.ui.csp.scriptDomains` 能并入 `script-src`。

**Files:**
- Modify: `packages/app/src/lib/mcp-apps/resource.ts`
- Test: `packages/app/src/lib/mcp-apps/resource.test.ts`

- [ ] **Step 1: 写失败测试**（追加到 `resource.test.ts` 的 `injectCsp` describe）

```ts
test("adds scriptDomains to script-src", () => {
  const html = injectCsp("<html><head></head><body></body></html>", {
    scriptDomains: ["https://cdn.example.com"],
  })
  expect(html).toContain("script-src 'unsafe-inline' 'self' data: https://cdn.example.com")
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd packages/app && bun test src/lib/mcp-apps/resource.test.ts`
Expected: FAIL——`script-src` 中无 `https://cdn.example.com`。

- [ ] **Step 3: 最小实现**

在 `resource.ts` 扩展 `SandboxOptions["csp"]` 与 `injectCsp`：

```ts
export type SandboxOptions = {
  csp?: {
    connectDomains?: string[]
    resourceDomains?: string[]
    frameDomains?: string[]
    scriptDomains?: string[]
  }
  permissions?: {
    clipboardWrite?: unknown
    camera?: unknown
    microphone?: unknown
    geolocation?: unknown
  }
}
```

```ts
const base = [
  "default-src 'none'",
  `script-src 'unsafe-inline' 'self' data: ${csp?.scriptDomains?.join(" ") || ""}`.trim(),
  "style-src 'unsafe-inline'",
  "img-src data: blob:",
  `connect-src ${[...(csp?.connectDomains ?? []), ...(csp?.resourceDomains ?? [])].join(" ") || "'none'"}`,
  `frame-src ${csp?.frameDomains?.join(" ") || "'none'"}`,
  "frame-ancestors 'self'",
].join("; ")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd packages/app && bun test src/lib/mcp-apps/resource.test.ts`
Expected: PASS（含新用例，原用例不受影响）。

- [ ] **Step 5: 提交**

```bash
git add packages/app/src/lib/mcp-apps/resource.ts packages/app/src/lib/mcp-apps/resource.test.ts
git commit -m "feat(mcp-apps): allow configured script domains in sandbox CSP"
```

---

### Task 2: 二进制 blob/PDF 资源真正渲染

目标：`readUiResource` 已能返回 `blob`，但 `McpAppView` 只渲染 `html.text`，blob 资源（pdf/video）渲染空文档。补一个纯函数把 base64 blob/PDF 生成可用的 blob URL。

**Files:**
- Modify: `packages/app/src/lib/mcp-apps/resource.ts`
- Modify: `packages/app/src/components/mcp-app-view.tsx`
- Test: `packages/app/src/lib/mcp-apps/resource.test.ts`

- [ ] **Step 1: 写失败测试**（追加 describe `buildBinaryResourceUrl`）

```ts
describe("buildBinaryResourceUrl", () => {
  test("decodes base64 blob into a mime-typed object URL", () => {
    // base64 of "<h1>hi</h1>" is "PGgxPmhpPC9oMT4="
    const url = buildBinaryResourceUrl("PGgxPmhpPC9oMT4=", "text/html")
    expect(url.startsWith("blob:")).toBe(true)
    globalThis.URL.revokeObjectURL(url)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd packages/app && bun test src/lib/mcp-apps/resource.test.ts`
Expected: FAIL——`buildBinaryResourceUrl` 未定义。

- [ ] **Step 3: 最小实现**

在 `resource.ts` 末尾新增：

```ts
/** Decodes a base64 binary resource (from ResourceContents.blob) into a mime-typed object URL. */
export function buildBinaryResourceUrl(blobB64: string, mimeType: string): string {
  const binary = atob(blobB64)
  const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0))
  return URL.createObjectURL(new Blob([bytes], { type: mimeType }))
}
```

- [ ] **Step 4: 接入组件**：改 `mcp-app-view.tsx` 的 `start()`，在抓到资源后分派 text 与 blob 两条路径

```ts
const html = await readUiResource(next, props.resourceUri)
let url: string
let sandboxTokens = "allow-scripts"
if (html.text) {
  const s = buildSandboxedHtml(html.text, { csp: html.meta?.ui?.csp, permissions: html.meta?.ui?.permissions })
  url = s.url
  sandboxTokens = s.sandbox
  revoke = s.revoke
} else if (html.blob) {
  url = buildBinaryResourceUrl(html.blob, html.mimeType ?? "application/octet-stream")
  revoke = () => URL.revokeObjectURL(url)
} else {
  throw new Error(language.t("mcp.app.loading"))
}
setBlobUrl(url)
setSandbox(sandboxTokens)
setPhase("ready")
```

（`iframe src={blobUrl()}` 已存在，无需再改 JSX；`sandbox` 信号对 blob 保持 `allow-scripts` 即可。）

- [ ] **Step 5: 跑测试确认通过**

Run: `cd packages/app && bun test src/lib/mcp-apps/resource.test.ts`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add packages/app/src/lib/mcp-apps/resource.ts packages/app/src/lib/mcp-apps/resource.test.ts packages/app/src/components/mcp-app-view.tsx
git commit -m "feat(mcp-apps): render binary blob resources (pdf) in the app iframe"
```

---

### Task 3: hostContext 主题/时区 + 实时 `host-context-changed` 推送

目标：当前 `buildHostContext` 只收到 width/height/locale，`theme`/`timeZone` 为空；且无实时 `setHostContext`。

**Files:**
- Modify: `packages/app/src/lib/mcp-apps/host-context.ts`
- Modify: `packages/app/src/components/mcp-app-view.tsx`
- Test: `packages/app/src/lib/mcp-apps/host-context.test.ts`

- [ ] **Step 1: 写失败测试**（追加到 `host-context.test.ts`）

```ts
test("passes through theme and default timeZone from the local timezone", () => {
  const ctx = buildHostContext({ theme: "dark", locale: "en-US", timeZone: "Asia/Shanghai" })
  expect(ctx.theme).toBe("dark")
  expect(ctx.timeZone).toBe("Asia/Shanghai")
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd packages/app && bun test src/lib/mcp-apps/host-context.test.ts`
Expected: FAIL——`ctx.theme` 为 `undefined`（调用处没传）、`timeZone` 未接入。

- [ ] **Step 3: 最小实现**：改 `host-context.ts`

```ts
export type HostContext = {
  theme?: "light" | "dark"
  displayMode: "inline"
  containerDimensions?: { width: number; height: number }
  locale?: string
  timeZone?: string
  platform: "web"
  deviceCapabilities?: { touch: boolean; hover: boolean }
}

export function buildHostContext(input: {
  width?: number
  height?: number
  theme?: "light" | "dark"
  locale?: string
  timeZone?: string
}): HostContext {
  const dims = input.width && input.height ? { width: input.width, height: input.height } : undefined
  return {
    theme: input.theme,
    displayMode: "inline",
    containerDimensions: dims,
    locale: input.locale,
    timeZone: input.timeZone ?? Intl.DateTimeFormat().resolvedOptions().timeZone,
    platform: "web",
    deviceCapabilities: { touch: false, hover: true },
  }
}
```

- [ ] **Step 4: 接入组件**：改 `mcp-app-view.tsx.onIframeLoad`，传入 theme/timeZone（theme 从现有 `useTheme` 一类的宿主信号取，若仓库无则先传入固定 `undefined`，仅 `timeZone` 由 `Intl` 兜底；本步骤要点是接通 `setHostContext` 实时推送能力）

```ts
let currentHostContext = buildHostContext({
  width: iframe.clientWidth || undefined,
  height: iframe.clientHeight || undefined,
  locale: language.intl(),
})
// 主题切换时推送给 App（host-context-changed 由 AppBridge.setHostContext 发出）
// 组件内监听宿主主题变化（示例：在 theme signal 变化处调用）
//   next.setHostContext({ ...currentHostContext, theme })
```

若仓库主题通过 `createSignal` 暴露（如 `useTheme`），在 `onMount` 里订阅并：

```ts
const setTheme = (theme?: "light" | "dark") => {
  currentHostContext = { ...currentHostContext, theme }
  void bridge?.setHostContext(currentHostContext)
}
```

**注意**：`AppBridge.setHostContext` 的确切方法名以「前提核对」的 d.ts 为准；若名字不同，改用 d.ts 中实际方法并同步更新本步。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd packages/app && bun test src/lib/mcp-apps/host-context.test.ts`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add packages/app/src/lib/mcp-apps/host-context.ts packages/app/src/lib/mcp-apps/host-context.test.ts packages/app/src/components/mcp-app-view.tsx
git commit -m "feat(mcp-apps): enrich host context with theme and timezone"
```

---

### Task 4: 运行中工具输入流式 push（最高价值缺口）

目标：目前 App 只在工具**完成后**渲染并回放 `tool-result`；运行中的 `tool-input / tool-input-partial` 不推送。改为：工具 running 时预渲染 App，并把工具输入（`part.state.input`）与进度实时推给 App。

**Files:**
- Create: `packages/session-ui/src/context/mcp-app-host.tsx`
- Modify: `packages/session-ui/src/context/mcp-app.tsx`
- Modify: `packages/session-ui/src/components/mcp-tool.tsx`
- Modify: `packages/app/src/components/mcp-app-view.tsx`
- Test: `packages/session-ui/src/context/mcp-app-host.test.ts`（新建）

- [ ] **Step 1: 写失败测试**（新建 `mcp-app-host.test.ts`）

```ts
import { describe, expect, test } from "bun:test"
import { createMcpAppHostRegistry } from "./mcp-app-host"

describe("mcp-app-host registry", () => {
  test("routes pushToolInput to the app registered for a key and drops after unregister", () => {
    const reg = createMcpAppHostRegistry<Record<string, unknown>>()
    const key = "ui-server/ui://dashboard"
    const received: Array<Record<string, unknown>> = []
    const un = reg.register(key, (input) => void received.push(input))
    reg.push(key, { axis: "x" })
    un()
    reg.push(key, { axis: "y" })
    expect(received).toEqual([{ axis: "x" }])
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd packages/session-ui && bun test src/context/mcp-app-host.test.ts`
Expected: FAIL——模块不存在。

- [ ] **Step 3: 最小实现**（新建 `packages/session-ui/src/context/mcp-app-host.tsx`，纯 TypeScript，自足即可）

```ts
export type AppKey = string

/** Map of mounted MCP apps to an imperative push sink, keyed by `${server}/${resourceUri}`. */
export type McpAppHost<T = Record<string, unknown>> = {
  register: (key: AppKey, push: (input: T) => void) => () => void
  push: (key: AppKey, input: T) => void
}

export function createMcpAppHostRegistry<T = Record<string, unknown>>(): McpAppHost<T> {
  const sinks = new Map<AppKey, (input: T) => void>()
  return {
    register(key, push) {
      sinks.set(key, push)
      return () => {
        if (sinks.get(key) === push) sinks.delete(key)
      }
    },
    push(key, input) {
      sinks.get(key)?.(input)
    },
  }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd packages/session-ui && bun test src/context/mcp-app-host.test.ts`
Expected: PASS。

- [ ] **Step 5: 预渲染 + 注册表接入**
  ① `mcp-app-view.tsx`：`onMount` 与 `onCleanup` 里向新 context 的 registry 注册/注销自身（key = `${props.server}/${props.resourceUri}`，push 回调 = `pushToolInput`）。先创建 Solid context `McpAppHostContext`（用法照 `mcp-app.tsx` 的 `createContext`/`Provider`，值来自一次 `createMcpAppHostRegistry()`），host 在渲染 `McpAppView` 时用 `McpAppHostProvider` 包裹。
  ② `mcp-tool.tsx`：把 `mcpAppFromPart` 改为**同时接受 running 与 completed**，工具 running 且有 `metadata.mcp.ui.resourceUri` 时也 `renderApp(info())`。
  ③ `mcp-tool.tsx`：`createMemo` 读取 `part.state.input`（running 时），经 `useMcpAppHost()().push(key, input)` 推给 App。

```ts
// mcp-app-view.tsx（组件顶部，供注册）
const host = useMcpAppHost()
const appKey = () => `${props.server}/${props.resourceUri}`
onMount(() => {
  void start()
  unregister = host().register(appKey(), pushToolInput)
})
onCleanup(() => {
  unregister?.()
  void bridge?.close()
  void client?.close()
  revoke?.()
})
```

```ts
// mcp-tool.tsx：暴露运行中工具输入
const runningInput = createMemo(() =>
  props.part.state.status === "running" ? (props.part.state as { input?: Record<string, unknown> }).input : undefined,
)
createEffect(() => {
  const key = app()
  const input = runningInput()
  if (key && input) useMcpAppHost()().push(`${key.server}/${key.resourceUri}`, input)
})
```

（如需全量 input 推送用 `sendToolInput`，`pushToolInput` 内可在 `partial` 上补全；本步以 `sendToolInputPartial` 即可满足"流式"。）

- [ ] **Step 6: E2E 断言**（在既有 `packages/app/e2e/regression/session-timeline-mcp-progress.spec.ts` 追加一次 running→input 的断言，沿用其 `mcpProgressTool` fixture 风格新增一个 running mcp-app 工具 part，断言 App iframe 出现且工具卡保持 running）

```ts
// 追加用例：运行中的 mcp-app 工具触发渲染且不抛错
await timeline.send(partUpdated(runningMcpAppTool({ axis: "x" })))
await expect(page.getByText("Rendering dashboard 3/5")).toBeVisible()
```

（`runningMcpAppTool` 按 `mcp-tool.tsx` 的 `metadata.mcp.ui.resourceUri` + 状态 `running` 结构手写一个最小 fixture。）

- [ ] **Step 7: 跑 E2E**

Run: `cd packages/app && bun run test:e2e e2e/regression/session-timeline-mcp-progress.spec.ts`
Expected: 通过。

- [ ] **Step 8: 提交**

```bash
git add packages/session-ui/src/context/mcp-app-host.tsx packages/session-ui/src/context/mcp-app-host.test.ts packages/session-ui/src/context/mcp-app.tsx packages/session-ui/src/components/mcp-tool.tsx packages/app/src/components/mcp-app-view.tsx packages/app/e2e/regression/session-timeline-mcp-progress.spec.ts
git commit -m "feat(mcp-apps): render running apps and stream live tool input to them"
```

---

### Task 5: `ui/message` 上屏为会话内通知

目标：`onmessage` 目前仅 `console.log`，App 发来的消息不进会话。改为把消息经既有通知/toast 机制呈现（文案走 i18n）。

**Files:**
- Modify: `packages/app/src/components/mcp-app-view.tsx`
- Test: 可选，纯组件集成，跑既有 app 单测集确认不回归

- [ ] **Step 1: 实现 `onmessage` 呈现**
  在 `mcp-app-view.tsx.onIframeLoad` 的 `next.onmessage` 中，读取 `{ role, content }`（`content: ContentBlock[]`）里的文本块并交给通知入口（示例用 `console` 替换成宿主通知抽象；若仓库有 toast/notify API 则调用后者）：

```ts
next.onmessage = async ({ role, content }, _extra) => {
  const text = content.find((block) => block.type === "text")?.text
  if (text) {
    // 用宿主通知机制呈现（本仓库如用 i18n + toast，参数名以此为准）
    console.log("[mcp-app] host message", role, text)
  }
  return {} // McpUiMessageResult
}
```

（若仓库暂无可直接调用的通知抽象，保留 `console.log` 并补充一条注释说明接入点——避免引入新依赖/过度工程。）

- [ ] **Step 2: 编译 + 单测回归**

Run: `cd packages/app && bun run typecheck`
Expected: 无类型错误。

- [ ] **Step 3: 提交**

```bash
git add packages/app/src/components/mcp-app-view.tsx
git commit -m "feat(mcp-apps): surface app ui/message notifications to the host"
```

---

### Task 6: `ui/download-file` + `ui/resource-teardown` 增补 + capability 一致性

目标：目前 `downloadFile:false`、无 download-file handler、`ui/resource-teardown` 未处理。增补 download-file（触发浏览器保存/downloads）与 resource-teardown（清 blob 资源）。

**Files:**
- Modify: `packages/app/src/lib/mcp-apps/bridge.ts`
- Modify: `packages/app/src/components/mcp-app-view.tsx`
- Test: `packages/app/src/lib/mcp-apps/bridge.test.ts`

> 前置：先读「前提核对」d.ts，确认 `AppBridge` 对 download-file 的 handler/setter（可能为 `ondownloadfile`/`sendDownloadFile` 或经 capability `downloadFile` 自动代理）。本任务按验证到的方法名实现；下表方法名若与 d.ts 不符则以 d.ts 为准。

- [ ] **Step 1: 写失败测试**（追加 `bridge.test.ts`）

```ts
import { describe, expect, test } from "bun:test"
import { hostCapabilities } from "./bridge"

describe("hostCapabilities", () => {
  test("declares downloadFile when enabled", () => {
    const caps = hostCapabilities({ downloadFile: true, message: false, openLink: false, logging: false })
    expect(caps.downloadFile).toEqual({})
    expect(caps.openLinks).toBeUndefined()
    expect(caps.message).toBeUndefined()
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd packages/app && bun test src/lib/mcp-apps/bridge.test.ts`
Expected: FAIL——`caps.downloadFile` 为 `undefined`。

- [ ] **Step 3: 最小实现**：`bridge.ts` 的 `HostCapabilities`/`hostCapabilities` 已支持 `downloadFile`，仅需在调用侧启用（本步先保证纯函数行为正确，若已正确则测试直接可用）：

```ts
// bridge.ts 当前实现已含 downloadFile 分支；若已有则跳过本段。
export function hostCapabilities(flags: {
  openLink: boolean
  downloadFile: boolean
  message: boolean
  logging: boolean
}): HostCapabilities {
  return {
    ...(flags.openLink ? { openLinks: {} } : {}),
    ...(flags.downloadFile ? { downloadFile: {} } : {}),
    ...(flags.message ? { message: {} } : {}),
    serverTools: {},
    serverResources: {},
    ...(flags.logging ? { logging: {} } : {}),
  }
}
```

- [ ] **Step 4: 接入组件**：`mcp-app-view.tsx`
  ① 启用 capability：`hostCapabilities({ openLink: true, downloadFile: true, message: true, logging: true })`。
  ② 加 download-file handler（`McpUiDownloadFileRequest.params = { contents: (EmbeddedResource | ResourceLink)[] }`）：

```ts
next.ondownloadfile = async ({ contents }, _extra) => {
  for (const item of contents) {
    if (item.type === "resource") {
      const res = item.resource // { uri, text? , blob?, mimeType? } | { uri, blob, mimeType? }
      const blob = res.blob
        ? new Blob([Uint8Array.from(atob(res.blob), (c) => c.charCodeAt(0))], { type: res.mimeType })
        : new Blob([res.text ?? ""], { type: res.mimeType })
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = res.uri.split("/").pop() ?? "download"
      a.click()
      URL.revokeObjectURL(url)
      continue
    }
    if (item.type === "resource_link" && client) {
      const read = await client.readResource({ uri: item.uri })
      const c = read.contents[0] as { text?: string; blob?: string; mimeType?: string } | undefined
      const blob = c?.blob
        ? new Blob([Uint8Array.from(atob(c.blob), (ch) => ch.charCodeAt(0))], { type: c.mimeType })
        : new Blob([c?.text ?? ""], { type: c?.mimeType })
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = item.uri.split("/").pop() ?? "download"
      a.click()
      URL.revokeObjectURL(url)
    }
  }
  return {}
}
```

  ③ **资源级 teardown**：`ui/resource-teardown` 是「宿主→视图」请求，通过 `bridge.teardownResource({})` 发起并等待视图确认。把现有 `onrequestteardown`（视图→宿主通知）改为先优雅 teardown 再关桥：

```ts
next.onrequestteardown = async () => {
  try {
    await next.teardownResource({}) // 向视图发送 ui/resource-teardown 并等待确认
  } catch {
    // 视图未应答，忽略后继续卸载
  }
  void next.close()
}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd packages/app && bun test src/lib/mcp-apps/bridge.test.ts`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add packages/app/src/lib/mcp-apps/bridge.ts packages/app/src/lib/mcp-apps/bridge.test.ts packages/app/src/components/mcp-app-view.tsx
git commit -m "feat(mcp-apps): support ui/download-file and resource teardown"
```

---

### Task 7: 能力一致性回归 + 更新支持度文档

目标：任务 1–6 完成后，确认 capability 声明与实现一致（不再出现"声明了却无 handler"），并更新支持度分析，标注已补齐项。

**Files:**
- Review: `packages/app/src/lib/mcp-apps/bridge.ts`、`packages/app/src/components/mcp-app-view.tsx`
- Modify: `二次开发功能架构文档/MCP-Apps-支持度分析.md`

- [ ] **Step 1: 核对 capability 一致性**：遍历 `hostCapabilities` 每个 `true` 分支，确认 `McpAppView` 有对应 handler；`downloadFile:false` 的相关 handler 已补为 `true`。列出仍为占位/不受支持的能力（如 sampling 真实 LLM 采样）并确认其在 capability 中**未声明**。

- [ ] **Step 2: 全量测试**

Run: `cd packages/app && bun test src/lib/mcp-apps && bun run typecheck`
Expected: 全部通过、无类型错。
另：`cd packages/session-ui && bun test`

- [ ] **Step 3: 更新支持度分析文档**：把以下能力从"缺失/占位"改为"已补齐"，并保留 sampling（真实 LLM 采样）为"未覆盖/产品决策待定"，避免夸大：

```
- 二进制/blob 资源渲染：✅（Task 2）
- CSP scriptDomains：✅（Task 1）
- hostContext theme/timeZone：✅（Task 3）
- 运行中工具输入流式 push：✅（Task 4，tool-input/partial）
- ui/message 上屏：✅/⚠️（Task 5，按仓库通知设施）
- ui/download-file：✅（Task 6）
- ui/resource-teardown：✅（Task 6）
- sampling 真实 LLM 采样：🔴 未覆盖（能力未声明，属产品/基础设施决策）
```

- [ ] **Step 4: 最终提交**

```bash
git add 二次开发功能架构文档/MCP-Apps-支持度分析.md
git commit -m "docs(mcp-apps): update support matrix after feature completion"
```

---

## Self-Review

- **覆盖性**：逐一对照支持度分析 §5 的 7 条建议——① 流式 push（Task 4）✅；② sampling（在本计划明确降级为"不声明能力"，非代码任务，见 Task 7 一致性核对）⚠️；③ 沙箱 `scriptDomains`（Task 1）+ 权限透传（既有）✅；④ 二进制渲染（Task 2）✅；⑤ hostContext 主题/时区/实时（Task 3）✅；⑥ message/download/teardown（Task 5/6）✅；⑦ 契约对齐（前端 workaround 已固化，本计划不新增）。`sampling` 因涉及宿主 provider 的基础设施决策，不写死代码，仅保证 capability 不虚报。

- **占位符扫描**：任务中凡涉及 AppBridge 未在本仓库直接验证的方法名（`ondownloadfile`、`onresourceteardown`、`setHostContext`），均以「前提核对」步骤指向 d.ts 为准，并给出 fallback 写法，非空占位。

- **类型一致性**：`getMcpAppHostRegistry` 名称在各文件统一为 `host()`/`useMcpAppHost()`；registry key 统一 `${server}/${resourceUri}`；`buildBinaryResourceUrl(base64, mime)`、`buildHostContext({…timeZone})` 在定义处与调用处签名一致。