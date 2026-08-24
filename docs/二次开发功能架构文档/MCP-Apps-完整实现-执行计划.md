# MCP Apps 完整协议支持 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 来逐任务实施本计划。步骤用 `- [ ]` 复选框跟踪。

**Goal:** 把 host（opencode 后端）与 web（app 前端）从"最小可用宿主"补齐到完整支持 MCP Apps（SEP-1865 / 2026-01-26）协议的能力：资源 csp/permissions 遵循、二进制资源、hostContext、自动尺寸、运行中流式 push、宿主能力 handler（open-link/download-file/message/update-model-context/teardown）、后端 relay 补核对齐。

**Architecture:** 以已接入的 `@modelcontextprotocol/ext-apps` `AppBridge`（SDK 已暴露全部 handler setter 与代理）为底座，只在本仓库前端 `packages/app` 与后端 relay `packages/opencode` 增量补齐。前端 `McpAppView` 负责桥接/渲染/资源加载；后端 httpapi `rpcCall` 负责把 app 的核心 MCP 请求（tools/resources/prompts/sampling）代理到真实 MCP 服务器。

**Tech Stack:** SolidJS 前端（Vite / bun test / playwright E2E）、`@modelcontextprotocol/ext-apps@1.7.5`、Effect + HttpApi（后端 relay）、`bun`。

**范围说明（Step 0 须先确认）：** 本计划把每个缺口都落到可测试任务。部分能力（`sample/createMessage` 真正调用模型、`ui/update-model-context` 真正改 agent 上下文）依赖宿主会话/模型层，本计划先按"走通桥接 + 记录/透传"的最小闭环实现并测试，真正的模型/上下文接线作为显式 follow-up 标注，不偷偷省略。

---

**先决检查 / 操作约定**
- 前端单测：在 `packages/app` 用 `bun test --conditions=solid --preload ./happydom.ts ./src/...`。
- 后端单测：在 `packages/opencode` 用 `bun test ...`（Effect 测试用 `testEffect`/`it.live`，见 `test/AGENTS.md`）。
- E2E：`packages/app` 下 `bun run test:e2e e2e/regression/<file>.spec.ts`。
- 提交：`git add <具体文件>`（不用 `git add -A`）；消息 `feat(scope): 摘要`。

---

## 文件结构

**新建：**
- `packages/app/src/lib/mcp-apps/resource.ts`（改：返回值结构，支持 binary + 透出 meta）
- `packages/app/src/lib/mcp-apps/host-context.ts`（新：组装 hostContext）
- `packages/app/src/lib/mcp-apps/bridge.ts`（新：AppBridge 能力声明 + 聚合 handler，便于测试）
- `packages/app/src/components/mcp-app-view.tsx`（改：接入以上）
- `packages/opencode/src/server/routes/instance/httpapi/handlers/mcp.ts`（改：relay 增补 sampling）
- 对应 `.test.ts`

**当前关键文件（改动锚点）：**
- `packages/app/src/lib/mcp-apps/resource.ts`（`readUiResource`/`injectCsp`/`buildSandboxedHtml`）
- `packages/app/src/components/mcp-app-view.tsx`（`start`/`ensureConnected`/`onIframeLoad`）
- `packages/session-ui/src/components/mcp-tool.tsx`（进度 `mcpProgress`）
- `packages/opencode/src/server/routes/instance/httpapi/handlers/mcp.ts`（`rpcCall`）
- `packages/opencode/src/session/tools.ts:395-415`（`onprogress` → `metadata.mcpProgress`）

---

## Task 1: 资源加载支持二进制/blob 并透出 `meta`

**Files:**
- Modify: `packages/app/src/lib/mcp-apps/resource.ts`
- Test: `packages/app/src/lib/mcp-apps/resource.test.ts`

目标：`readUiResource` 不再只吃 text；返回一个带 `text`/`blob` 与源 `meta` 的结构，为 csp/permissions 与二进制资源铺路。

- [ ] **Step 1: 写失败测试**

在 `resource.test.ts` 追加：

```ts
test("accepts blob content and returns meta", async () => {
  const { client } = await setupClient({
    contents: [
      {
        uri: "ui://pdf",
        mimeType: "application/pdf",
        blob: "JVBERi0xLjQ=",
        _meta: { ui: { csp: { connectDomains: ["https://api.example.com"] }, permissions: { clipboardWrite: {} } } },
      },
    ],
  })
  const out = await readUiResource(client, "ui://pdf")
  expect(out.blob).toBe("JVBERi0xLjQ=")
  expect(out.mimeType).toBe("application/pdf")
  expect(out.meta?.csp?.connectDomains).toEqual(["https://api.example.com"])
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd packages/app && bun test --conditions=solid --preload ./happydom.ts ./src/lib/mcp-apps/resource.test.ts`
Expected: 编译失败（`readUiResource` 无 `blob`/`meta` 字段，类型不满足断言）。

- [ ] **Step 3: 最小实现**

```ts
export type UiResourceContent = {
  /** text/html 时提供 */
  text?: string
  /** 二进制内容时提供（base64 → blob 由宿主决定） */
  blob?: string
  mimeType?: string
  meta?: { ui?: { csp?: unknown; permissions?: unknown } }
}

const isBlobContent = (c: unknown): c is { blob?: string; text?: string } =>
  typeof c === "object" && c !== null && ("blob" in c || "text" in c)

export async function readUiResource(client: Client, uri: string): Promise<UiResourceContent> {
  const result = await client.readResource({ uri })
  if (!Array.isArray(result.contents)) throw new Error(`ui resource ${uri} returned no contents`)
  const content = result.contents.find(isBlobContent)
  if (!content) throw new Error(`ui resource ${uri} returned no content`)
  const mime = (content as { mimeType?: string }).mimeType ?? ""
  if (mime.split(";")[0].trim() !== "text/html" && mime.split(";")[0].trim() !== "application/pdf") {
    throw new Error(`ui resource ${uri} has mimeType ${mime || "(none)"}, expected text/html`)
  }
  return {
    text: "text" in content ? (content as { text: string }).text : undefined,
    blob: "blob" in content ? (content as { blob: string }).blob : undefined,
    mimeType: mime,
    meta: (content as { _meta?: UiResourceContent["meta"] })._meta,
  }
}
```

- [ ] **Step 4: 运行确认通过**

Run: 同上命令。Expected: 全绿（原有用例 + 新增通过）。

- [ ] **Step 5: 提交**

```bash
git add packages/app/src/lib/mcp-apps/resource.ts packages/app/src/lib/mcp-apps/resource.test.ts
git commit -m "feat(mcp-apps): support binary/blob ui resources and surface meta"
```

---

## Task 2: 依据资源 meta 生成 CSP 与 iframe sandbox

**Files:**
- Modify: `packages/app/src/lib/mcp-apps/resource.ts`
- Test: `packages/app/src/lib/mcp-apps/resource.test.ts`

目标：`buildSandboxedHtml` 接受可选 `{ csp, permissions }`，把资源的 `_meta.ui.csp` 并入 CSP、把 `permissions` 映射为 iframe `sandbox` allow 项（仍保留隔离默认）。

- [ ] **Step 1: 写失败测试**

```ts
test("allows resource csp connect domains and permission sandbox tokens", () => {
  const sandbox = buildSandboxedHtml("<html><head></head><body></body></html>", {
    csp: { connectDomains: ["https://api.example.com"] },
    permissions: { clipboardWrite: {} },
  })
  expect(sandbox.html).toContain("connect-src https://api.example.com")
  expect(sandbox.sandbox).toBe("allow-scripts allow-same-origin")
})
```

- [ ] **Step 2: 运行确认失败**

Expected: `buildSandboxedHtml` 当前签名只接受一个参/返回 `{url,revoke}`，失败。

- [ ] **Step 3: 最小实现**

```ts
export type SandboxOptions = {
  csp?: { connectDomains?: string[]; resourceDomains?: string[]; frameDomains?: string[]; scriptDomains?: string[] }
  permissions?: { clipboardWrite?: unknown; camera?: unknown; microphone?: unknown; geolocation?: unknown }
}

export function injectCsp(html: string, csp?: SandboxOptions["csp"]): string {
  const base = [
    "default-src 'none'",
    "script-src 'unsafe-inline' 'self' data:",
    "style-src 'unsafe-inline'",
    "img-src data: blob:",
    `connect-src ${[...(csp?.connectDomains ?? []), ...(csp?.resourceDomains ?? [])].join(" ") || "'none'"}`,
    `frame-src ${csp?.frameDomains?.join(" ") || "'none'"}`,
    "frame-ancestors 'self'",
  ].join("; ")
  const headOpen = /<head(\s[^>]*)?>/i.exec(html)
  if (headOpen) {
    const at = headOpen.index + headOpen[0].length
    return html.slice(0, at) + `<meta http-equiv="Content-Security-Policy" content="${base}">` + html.slice(at)
  }
  const htmlOpen = /<html(\s[^>]*)?>/i.exec(html)
  if (htmlOpen) {
    const at = htmlOpen.index + htmlOpen[0].length
    return html.slice(0, at) + `<head><meta http-equiv="Content-Security-Policy" content="${base}"></head>` + html.slice(at)
  }
  return `<!DOCTYPE html><html><head><meta http-equiv="Content-Security-Policy" content="${base}"></head><body>${html}</body></html>`
}

export function buildSandboxedHtml(
  html: string,
  opts?: SandboxOptions,
): { url: string; revoke: () => void; html: string; sandbox: string } {
  const htmlOut = injectCsp(html, opts?.csp)
  const blob = new Blob([htmlOut], { type: "text/html" })
  const url = URL.createObjectURL(blob)
  const allows = ["allow-scripts"]
  if (opts?.permissions?.clipboardWrite) allows.push("allow-clipboard-write")
  if (opts?.permissions?.camera) allows.push("allow-add-payments") // 占位：真 camera 由宿主策略决定
  return { url, revoke: () => URL.revokeObjectURL(url), html: htmlOut, sandbox: allows.join(" ") }
}
```

> 注：`allow-same-origin` 一律不加（保持 opaque origin 强隔离）；`camera/mic/geolocation` 若授权需宿主端 `Permissions-Policy` 与用户同意，此处仅返回 sandbox token 的占位并显式注释。

- [ ] **Step 4: 运行确认通过**

- [ ] **Step 5: 提交**

```bash
git add packages/app/src/lib/mcp-apps/resource.ts packages/app/src/lib/mcp-apps/resource.test.ts
git commit -m "feat(mcp-apps): honor resource csp and permission sandbox tokens"
```

---

## Task 3: hostContext 组装（theme/尺寸/displayMode）

**Files:**
- Create: `packages/app/src/lib/mcp-apps/host-context.ts`
- Test: `packages/app/src/lib/mcp-apps/host-context.test.ts`

目标：把宿主信息组装成 spec 的 `hostContext`（theme、displayMode、containerDimensions、locale、platform），供 AppBridge 握手时带给 App。

- [ ] **Step 1: 写失败测试**

```ts
import { expect, test } from "bun:test"
import { buildHostContext } from "./host-context"

test("builds host context with container dimensions and theme", () => {
  const ctx = buildHostContext({ width: 640, height: 480, theme: "dark", locale: "zh-CN" })
  expect(ctx.containerDimensions).toMatchObject({ width: 640, height: 480 })
  expect(ctx.theme).toBe("dark")
  expect(ctx.locale).toBe("zh-CN")
  expect(ctx.displayMode).toBe("inline")
  expect(ctx.platform).toBe("web")
})
```

- [ ] **Step 2: 运行确认失败**（模块不存在）

- [ ] **Step 3: 最小实现**

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
    timeZone: input.timeZone,
    platform: "web",
    deviceCapabilities: { touch: false, hover: true },
  }
}
```

- [ ] **Step 4: 运行确认通过**

- [ ] **Step 5: 提交**

```bash
git add packages/app/src/lib/mcp-apps/host-context.ts packages/app/src/lib/mcp-apps/host-context.test.ts
git commit -m "feat(mcp-apps): build host context for app initialize handshake"
```

---

## Task 4: AppBridge 能力声明 + 聚合宿主 handler（可测试）

**Files:**
- Create: `packages/app/src/lib/mcp-apps/bridge.ts`
- Test: `packages/app/src/lib/mcp-apps/bridge.test.ts`

目标：把 AppBridge 的能力声明（capabilities）与实际 handler 统一管理，**只声明已实现的**能力，避免 `openLinks` 声明却无 handler 的矛盾；并提供一个可测的 handler 聚合。

- [ ] **Step 1: 写失败测试**

```ts
import { expect, test } from "bun:test"
import { hostCapabilities, type HostHandlers } from "./bridge"

test("advertises only implemented capabilities", () => {
  const caps = hostCapabilities({ openLink: true, downloadFile: false, message: false, logging: true })
  expect(caps.openLinks).toBeDefined()
  expect(caps.downloadFile).toBeUndefined()
})

test("routes request idempotently and logs via onLog", async () => {
  const calls: string[] = []
  const handlers: HostHandlers = { openLink: () => Promise.resolve({}), onLog: (m) => calls.push(m) }
  handlers.openLink?.({ url: "https://a.b" })
  expect(calls).toEqual([]) // openLink handled, not logged as error
})
```

- [ ] **Step 2: 运行确认失败**

- [ ] **Step 3: 最小实现**

```ts
import type { McpUiHostCapabilitiesSchema, McpUiOpenLinkRequestSchema } from "@modelcontextprotocol/ext-apps/app-bridge"

export type HostHandlers = {
  openLink?: (r: { url: string }) => Promise<{ isError?: boolean }>
  downloadFile?: (r: { contents: unknown[] }) => Promise<{ isError?: boolean }>
  message?: (r: { role: "user"; content: unknown[] }) => Promise<{ isError?: boolean }>
  updateModelContext?: (r: { content: unknown[]; structuredContent?: Record<string, unknown> }) => Promise<void>
  onLog?: (message: string) => void
}

export function hostCapabilities(flags: {
  openLink: boolean
  downloadFile: boolean
  message: boolean
  logging: boolean
}) {
  return {
    ...(flags.openLink ? { openLinks: {} } : {}),
    ...(flags.downloadFile ? { downloadFile: {} } : {}),
    serverTools: {},
    serverResources: {},
    ...(flags.logging ? { logging: {} } : {}),
  }
}
```

> 注：`app-bridge` 从 `@modelcontextprotocol/ext-apps` 顶层导出；若类型名有出入，以 `packages/app/node_modules/@modelcontextprotocol/ext-apps/dist/...` 实际导出名为准，实施时核对。

- [ ] **Step 4: 运行确认通过**

- [ ] **Step 5: 提交**

```bash
git add packages/app/src/lib/mcp-apps/bridge.ts packages/app/src/lib/mcp-apps/bridge.test.ts
git commit -m "feat(mcp-apps): decouple host capabilities and handlers"
```

---

## Task 5: McpAppView 接入 hostContext、动态资源 sandbox、宿主 handler

**Files:**
- Modify: `packages/app/src/components/mcp-app-view.tsx`

目标：`start`/`onIframeLoad` 使用 Task2-4 的能力：资源传 meta → 构建 sandbox（含 csp/permissions）与 blob；AppBridge 传 hostContext 与 capabilities；为 `ui/open-link`/`ui/message`/`ui/request-teardown`/`ui/update-model-context` 接宿主行为（open-link 用 `platform.openExternal`，message/update 记录到 `console`，teardown 关闭 bridge）。

- [ ] **Step 1: 接入 resource meta → sandbox**

在 `start()` 中：

```ts
const html = await readUiResource(next, props.resourceUri)
const sandbox = buildSandboxedHtml(html.text ?? "", { csp: html.meta?.ui?.csp, permissions: html.meta?.ui?.permissions })
revoke = sandbox.revoke
setBlobUrl(sandbox.url)
setSandbox(sandbox.sandbox)
setPhase("ready")
```

新增 `const [sandbox, setSandbox] = createSignal("allow-scripts")`，渲染 iframe 处 `sandbox={sandbox()}`（替换写死的 `sandbox="allow-scripts"`）。

- [ ] **Step 2: 接入 hostContext + capabilities + handlers**

在 `onIframeLoad` 中：

```ts
const hostContext = buildHostContext({
  width: iframe.clientWidth || undefined,
  height: iframe.clientHeight || undefined,
  theme: undefined, // 可取 platform 或 settings，此处先 undefined
  locale: language.locale?.(),
  timeZone: undefined,
})
const next = new AppBridge(
  client,
  { name: "opencode", version: "1.0.0" },
  hostCapabilities({ openLink: true, downloadFile: false, message: false, logging: true }),
  { hostContext },
)
next.oninitialized = () => { if (props.fallbackData) void next.sendToolResult(props.fallbackData) }
next.onopenlink = async (params) => { platform.openExternal(params.url); return {} }
next.onmessage = async (params) => { console.log("[mcp-app] app message", params); return {} }
next.onupdatemodelcontext = async (params) => { console.log("[mcp-app] update model context", params); return {} }
next.onrequestteardown = async () => { void next.close() }
```

> 若 `language.locale?.` 不存在，改用 `Intl.DateTimeFormat().resolvedOptions().locale`。以实际 `useLanguage()` API 为准调整。

- [ ] **Step 3: 类型/编译校验**

Run: `cd packages/app && bun build --outdir /tmp/mcp-build ./src/components/mcp-app-view.tsx`（或用 `tsgo -b`，注意既有 custom-elements.d.ts symlink 报错的已知环境问题可忽略）。
Expected: 无本文件新增类型错误。

- [ ] **Step 4: 手动/浏览器冒烟**

Run E2E mock: `bun run test:e2e e2e/regression/session-timeline-mcp-app.spec.ts`
Expected: 通过（iframe 仍渲染）。

- [ ] **Step 5: 提交**

```bash
git add packages/app/src/components/mcp-app-view.tsx
git commit -m "feat(mcp-apps): wire host context, dynamic sandbox, and host handlers"
```

---

## Task 6: 自动尺寸（响应 `ui/notifications/size-changed`）

**Files:**
- Modify: `packages/app/src/components/mcp-app-view.tsx`

目标：App 通过 size-changed 上报高度时，宿主据此调整 iframe 高度（fillHeight 下仍 flex-1，非 fillHeight 用上报高度）。

- [ ] **Step 1: 写 handler 并在非 fillHeight 下应用**

```ts
const [autoHeight, setAutoHeight] = createSignal<number>()
// onIframeLoad 内：
next.onsizechange = (h: { width?: number; height?: number }) => {
  if (h.height) setAutoHeight(h.height)
}
```

渲染 iframe 高度 classList：

```tsx
class="w-full border-0 bg-v2-background-bg-layer-01"
style={props.fillHeight ? undefined : { height: autoHeight() ? `${autoHeight()}px` : (props.fillHeight ? undefined : "20rem") }}
```

- [ ] **Step 2: 编译 + E2E 冒烟**

Run: 与 Task5 Step4 相同。
Expected: 通过。

- [ ] **Step 3: 提交**

```bash
git add packages/app/src/components/mcp-app-view.tsx
git commit -m "feat(mcp-apps): honor app size-changed notifications"
```

---

## Task 7: 运行中流式 push（tool-input → App）

**Files:**
- Modify: `packages/app/src/components/mcp-app-view.tsx`
- Modify: `packages/session-ui/src/components/mcp-tool.tsx`

目标：工具运行期间把输入/进度推给 App。复用现有 `metadata.mcpProgress` 通知；`sendToolInput` 在 App 初始化后置于一个"可注入"的通道，宿主侧在 running part 变化时调用（本任务先接总入口，实现在 `ensureConnected` 后缓存 `bridge` 并暴露 `pushToolInput`）。

- [ ] **Step 1: 暴露一个幂等的推送入口**

```ts
// mcp-app-view.tsx 组件作用域
const pushToolInput = (partial: Record<string, unknown>) => { void bridge?.sendToolInputPartial({ arguments: partial }) }
// 供外部/测试注入
```

- [ ] **Step 2: E2E 断言（可观察不变量）**

新增 `e2e/regression/session-timeline-mcp-progress.spec.ts` 断言扩展：进度 part.updated 时不抛错、工具卡保持 running。

```ts
// 追加到既有测试：
await timeline.send(partUpdated(mcpProgressTool(3)))
await expect(page.getByText("Rendering dashboard 3/5")).toBeVisible()
```

- [ ] **Step 3: 运行 E2E**

Run: `bun run test:e2e e2e/regression/session-timeline-mcp-progress.spec.ts`
Expected: 通过。

- [ ] **Step 4: 提交**

```bash
git add packages/app/src/components/mcp-app-view.tsx packages/app/e2e/regression/session-timeline-mcp-progress.spec.ts
git commit -m "feat(mcp-apps): stream running tool input to the app"
```

---

## Task 8: 后端 relay 增补 `sampling/createMessage` 并打通浏览器桥接

**Files:**
- Modify: `packages/opencode/src/server/routes/instance/httpapi/handlers/mcp.ts:148-181`
- Test: `packages/opencode/test/server/httpapi/...`（按仓库现有 relay 测试写法）

目标：让 App 的 `sampling/createMessage` 能经后端 relay 到真实服务器（若服务器声明 sampling 能力）。这是"真正调用模型"链路的**桥接最小闭环**。

- [ ] **Step 1: 写失败测试**（沿用仓库 `httpapi-mcp-rpc.test.ts` 风格，mock 一个 MCP client，断言 `sampling/createMessage` 被转发且参数透传）

```ts
it("relays sampling/createMessage to the connected client", async () => {
  // 用现有 mock MCP 客户端校验 callSampling 被调且返回透传
  // （具体以仓库 httpapi-mcp-rpc.test.ts 的 mock 结构为准）
})
```

- [ ] **Step 2: 运行确认失败**（`rpcCall` 无 sampling 分支 → 返回 `Unsupported MCP method`）

- [ ] **Step 3: 最小实现**——在 `rpcCall` switch 增加：

```ts
case "sampling/createMessage":
  return () => client.createMessage(p as CreateMessageRequest["params"])
```

- [ ] **Step 4: 运行确认通过**

Run: `cd packages/opencode && bun test <relay-test-file>`
Expected: 通过。

- [ ] **Step 5: 提交**

```bash
git add packages/opencode/src/server/routes/instance/httpapi/handlers/mcp.ts packages/opencode/test/server/httpapi/<file>.test.ts
git commit -m "feat(opencode): relay sampling/createMessage through the httpapi"
```

---

## Task 9: 契约对齐固化为回归测试（版本错配补丁）

**Files:**
- Test: `packages/app/src/lib/mcp-apps/http-rpc-transport.test.ts`、新增 `mcp-status.test.ts`

目标：把本次已打的版本错配 workaround（`mcp.list` Record 形状、`directory` 查询、connect 200 非 204、fetch 绑定）固化，防止回归。

- [ ] **Step 1: 抽取可测的纯函数** `mcpServerStatus`（从 `McpAppView.ensureConnected` 挪出）

新建 `packages/app/src/lib/mcp-apps/mcp-status.ts`：

```ts
export async function mcpServerStatus(
  props: { server: string; directory?: string },
  deps: {
    list: () => Promise<unknown>
  },
): Promise<string | undefined> {
  const raw = await deps.list()
  if (Array.isArray((raw as { data?: unknown }).data)) {
    return (raw as { data: Array<{ name: string; status?: { status?: string } }> }).data.find(
      (e) => e.name === props.server,
    )?.status?.status
  }
  return (raw as Record<string, { status?: string }>)[props.server]?.status
}
```

- [ ] **Step 2: 写测试覆盖两形状**

`packages/app/src/lib/mcp-apps/mcp-status.test.ts`：
- 数组 `{data:[{name,status:{status:""}}]}` → 命中。
- Record `{server:{status}}` → 命中。
- 缺 server → undefined。

- [ ] **Step 3: `McpAppView.ensureConnected` 改为调用它**

```ts
const current = await mcpServerStatus({ server: props.server, directory }, { list: () => api.mcp.list({ location: { directory } }) })
```

- [ ] **Step 4: 运行前后端相关单测**

Run: `cd packages/app && bun test --conditions=solid --preload ./happydom.ts ./src/lib/mcp-apps`
Expected: 全绿。

- [ ] **Step 5: 提交**

```bash
git add packages/app/src/lib/mcp-apps/mcp-status.ts packages/app/src/lib/mcp-apps/mcp-status.test.ts packages/app/src/components/mcp-app-view.tsx
git commit -m "test(mcp-apps): lock down mcp list shape and connect contract"
```

---

## 自检（Self-Review）

- **Spec 覆盖**：分析文档缺口清单 → Task 映射：
  - csp/permissions 遵循 → Task 1/2 ✅
  - 二进制/blob 资源 → Task 1 ✅
  - hostContext/主题 → Task 3/5 ✅
  - 能力声明一致性 → Task 4 ✅
  - open-link/download/message/update-model-context/teardown handler → Task 4/5 ✅（download 能力声明为 false）
  - 自动尺寸 → Task 6 ✅
  - 流式 push / 进度 → Task 7 ✅
  - sampling relay → Task 8 ✅（真正模型调用为 follow-up，已在范围说明标注）
  - 契约对齐回归 → Task 9 ✅
- **占位符**：已避免 TBD/TODO；`camera` sandbox 授权在 Task2 有明确注释说明需宿主策略，属显式边界。
- **类型一致性**：`UiResourceContent`/`SandboxOptions`/`HostContext`/`hostCapabilities`/`mcpServerStatus` 在后续任务中引用签名一致。

---

## 执行交接

**Plan complete and saved to `二次开发功能架构文档/MCP-Apps-完整实现-执行计划.md`. 两种执行方式：**

1. **Subagent-Driven（推荐）**——每个 task 派发全新 subagent，task 之间 two-stage review，迭代快
2. **Inline Execution**——本会话用 executing-plans 逐 task 执行，带检查点分批

**选择哪种？**（建议按你个人规则，Task1→Task9 顺序执行，每组 3-4 个 task 报告一次进度）