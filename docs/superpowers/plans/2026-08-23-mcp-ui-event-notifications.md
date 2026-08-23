# MCP 非标准 uiEvent 通知支持 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 opencode host + web 完整支持 MCP server 发送的"携带 `uiEvent` 扩展字段的非标准 notification"，端到端可用（pdf2json 的 `content.send_progress_with_data` 即此场景）。

**Architecture:** 根因是 MCP SDK 用严格的 `ProgressNotificationParamsSchema`（`z.object`）解析 `notifications/progress`，会把 params 中的未知扩展字段 `uiEvent` 剥离（已验证：解析后 `uiEvent` 为 `undefined`）。修复点集中在 host 的 MCP 客户端注册层：用 `.loose()` 宽松 schema 重注册 `notifications/progress` handler，解析保留 `uiEvent` 后仍转交 SDK 内置的 `progressToken -> callTool onprogress` 分发；同时设置 `fallbackNotificationHandler` 兜底捕获未注册 method 的通知，凡携带 `progressToken + uiEvent` 的走同一条进度管道。`uiEvent` 一旦到达 `onprogress` 回调，后续链路（`tools.ts` 写入 `metadata.mcpProgress` → SSE → web `McpTool` → `McpAppHost` 注册表 → iframe App）已全部就绪，web 侧无需改动。

**Tech Stack:** Bun、TypeScript、Effect、`@modelcontextprotocol/sdk`（1.29.0）、`bun:test`、SolidJS（web 侧只跑回归验证）。

---

## 背景与根因（执行者必读）

MCP Apps 服务器（如 `mcps/pdf2json`）通过 `notifications/progress` 的标准 JSON-RPC 通知携带非标准扩展字段：

```json
{
  "jsonrpc": "2.0",
  "method": "notifications/progress",
  "params": {
    "progressToken": 3,
    "progress": 0,
    "total": 10,
    "message": "PDF 解析完成，共 2 页",
    "uiEvent": { "event_type": "images_loaded", "image_paths": ["page-0.png"] }
  }
}
```

opencode host 使用官方 SDK `Client`（`packages/opencode/src/mcp/index.ts` 的 `createClient()`）。SDK 在协议层对 `notifications/progress` 的内置 handler 注册在 `@modelcontextprotocol/sdk/dist/esm/shared/protocol.js` 构造函数（L27-30），经 `setNotificationHandler`（L918-924）包装为 `parseWithCompat(ProgressNotificationSchema, notification)`。而 `ProgressNotificationParamsSchema` 是严格 `z.object`（`dist/esm/types.js` L584-591），**默认 strip 模式会剥离未知键 `uiEvent`**。

已验证（bun 实测）：

```
parsed params keys: [ "progress", "total", "message", "progressToken" ]
uiEvent preserved: undefined
```

因此 `catalog.ts` L118 `uiEvent: (p as { uiEvent?: unknown }).uiEvent` 永远拿到 `undefined`，`uiEvent` 从未进入 `metadata.mcpProgress`，web / iframe 自然收不到。另外，任何 method 未注册的非标准通知（如 `ui/notifications/*`）会被 SDK 静默丢弃（`protocol.js` L273-283：`handler === undefined` 时直接 `return`）。

修复后链路（web 侧已就绪，仅 host 补上缺失的一环）：

```
MCP server ── notifications/progress + uiEvent ──▶
  SDK 宽松 schema 解析（uiEvent 保留）
  → 内置 _onprogress 分发（progressToken -> callTool onprogress）
  → catalog.ts onProgress({ progress, total, message, uiEvent }, toolCallId)
  → session/tools.ts 写入 part metadata.mcpProgress（含 uiEvent）
  → message.part.updated → SSE → web server-sdk.tsx / server-session.ts
  → session-ui mcp-tool.tsx push tool-progress(uiEvent)
  → McpAppHost 注册表 → app mcp-app-view.tsx 转发 notifications/progress(uiEvent) → iframe App
```

---

## 文件结构

| 文件 | 责任 |
|---|---|
| `packages/opencode/src/mcp/catalog.ts`（改） | 新增宽松 schema、`dispatchProgress`、`installUiEventNotificationHandlers` 导出 |
| `packages/opencode/src/mcp/index.ts`（改） | `watch()` 中调用 installer 安装 handler |
| `packages/opencode/test/mcp/catalog-ui-event.test.ts`（建） | 单元/集成测试：真实 SDK Client+Server+InMemoryTransport，验证 uiEvent 端到端到达 onprogress |
| `docs/mcp-apps-ui-protocol.md`（改） | 文档化 uiEvent 扩展字段的端到端支持 |

---

### Task 1: Host — 宽松 schema 重注册 `notifications/progress`，保留 uiEvent 扩展字段

**Files:**
- Modify: `packages/opencode/src/mcp/catalog.ts`
- Modify: `packages/opencode/src/mcp/index.ts:464-478`（`watch()` 内注册 handler 的位置）
- Test: `packages/opencode/test/mcp/catalog-ui-event.test.ts`（Create）

- [ ] **Step 1: 写失败测试（验证当前 uiEvent 被剥离）**

创建 `packages/opencode/test/mcp/catalog-ui-event.test.ts`：

```ts
import { describe, expect, test } from "bun:test"
import { Client } from "@modelcontextprotocol/sdk/client/index.js"
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js"
import { Server } from "@modelcontextprotocol/sdk/server/index.js"
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js"
import { McpCatalog } from "@/mcp/catalog"

const options = { toolCallId: "call_step", abortSignal: new AbortController().signal } as any

/** 构造一个在工具执行中发送带 uiEvent 扩展字段的 progress 通知的 MCP server。 */
function uiEventServer(method: string) {
  const server = new Server({ name: "ui-event-server", version: "1.0.0" }, { capabilities: { tools: {} } })
  server.setRequestHandler(ListToolsRequestSchema, () =>
    Promise.resolve({
      tools: [{ name: "step", description: "step", inputSchema: { type: "object", properties: {} } }],
    }),
  )
  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const token = request.params._meta?.progressToken
    if (token !== undefined) {
      await server.notification({
        method,
        params: {
          progressToken: token,
          progress: 1,
          total: 2,
          message: "working",
          uiEvent: { event_type: "images_loaded", image_paths: ["a.png"] },
        },
      })
    }
    return { content: [{ type: "text", text: "done" }] }
  })
  return server
}

async function run(method: string) {
  const server = uiEventServer(method)
  const client = new Client({ name: "test", version: "1.0.0" })
  McpCatalog.installUiEventNotificationHandlers(client)
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair()
  await Promise.all([client.connect(clientTransport), server.connect(serverTransport)])

  const received: McpCatalog.McpProgress[] = []
  const tool = McpCatalog.convertTool(
    { name: "step", description: "", inputSchema: { type: "object", properties: {} } } as any,
    client,
    undefined,
    (progress) => received.push(progress),
  )
  await tool.execute?.({}, options)

  await Promise.all([client.close(), server.close()])
  return received
}

describe("MCP non-standard uiEvent notifications", () => {
  test("preserves uiEvent from notifications/progress instead of stripping it", async () => {
    const received = await run("notifications/progress")
    expect(received).toHaveLength(1)
    expect(received[0]).toMatchObject({ progress: 1, total: 2, message: "working" })
    expect(received[0].uiEvent).toEqual({ event_type: "images_loaded", image_paths: ["a.png"] })
  })
})
```

- [ ] **Step 2: 运行测试，确认当前失败（red）**

Run（在 `packages/opencode` 下，勿从仓库根运行）：

```bash
bun test test/mcp/catalog-ui-event.test.ts
```

Expected: FAIL —— 两个失败点：`installUiEventNotificationHandlers` 不存在（编译错误），以及（若临时忽略编译错误）`received[0].uiEvent` 为 `undefined`，`toEqual({ event_type: "images_loaded", ... })` 断言失败。

- [ ] **Step 3: 实现 catalog.ts —— 宽松 schema + 安装函数**

修改 `packages/opencode/src/mcp/catalog.ts`：

1) 扩展 import（文件顶部）：

```ts
import {
  CallToolResultSchema,
  ListToolsResultSchema,
  ProgressNotificationParamsSchema,
  ProgressNotificationSchema,
  ToolSchema,
  type Notification,
  type Tool as MCPToolDef,
} from "@modelcontextprotocol/sdk/types.js"
```

2) 在 `McpProgress` 接口（约 L50）之后新增：

```ts
/**
 * 松开 SDK 对 notifications/progress 的严格 zod 解析：SDK 的 ProgressNotificationParamsSchema
 * 是 `z.object`（默认 strip），会把 params 里非标准的扩展字段（如 SEP-1865 的 uiEvent）剥离；
 * `.loose()` 版保留全部扩展字段，使 uiEvent 能原样到达 convertTool 的 onprogress 回调。
 */
export const LooseProgressNotificationSchema = ProgressNotificationSchema.extend({
  params: ProgressNotificationParamsSchema.loose(),
})

/** 转交 SDK 内置的 progressToken -> callTool onprogress 分发（保持 timeout reset 与 toolCallId 关联不变）。 */
function dispatchProgress(client: Client, notification: Notification) {
  return (client as unknown as { _onprogress: (notification: Notification) => void })._onprogress(notification)
}

/**
 * 注册非标准 notification 处理（MCP Apps SEP-1865 uiEvent 扩展）：
 * 1) 用宽松 schema 重注册 notifications/progress，uiEvent 不再被 SDK 剥离；
 * 2) 兜底捕获未注册 method 的通知，凡携带 progressToken+uiEvent 的走标准进度管道。
 * 直接替换 SDK 构造函数注册的内置 progress handler，行为一致（仅解析更宽松）。
 */
export function installUiEventNotificationHandlers(client: Client) {
  client.setNotificationHandler(LooseProgressNotificationSchema, (notification) =>
    dispatchProgress(client, notification as Notification),
  )
}
```

- [ ] **Step 4: 实现 index.ts —— watch() 中安装 handler**

修改 `packages/opencode/src/mcp/index.ts` `watch()`，在 `client.setNotificationHandler(ToolListChangedNotificationSchema, ...)`（约 L469-478）之后、`if (!client.getServerCapabilities()?.tools) return` 之前插入：

```ts
      // 非标准 notification 支持（SEP-1865 uiEvent 扩展字段）：SDK 严格解析会剥离
      // notifications/progress params 中的 uiEvent，此处用宽松 schema 重注册，使
      // uiEvent 能随 onprogress 回调写入 metadata.mcpProgress，最终转发进 iframe App。
      McpCatalog.installUiEventNotificationHandlers(client)
```

- [ ] **Step 5: 运行测试，确认通过（green）**

```bash
bun test test/mcp/catalog-ui-event.test.ts
```

Expected: PASS —— `received[0].uiEvent` 等于 `{ event_type: "images_loaded", image_paths: ["a.png"] }`。

- [ ] **Step 6: 类型检查**

```bash
bun typecheck
```

Expected: 无错误（在 `packages/opencode` 下运行，勿用 `tsc`）。

- [ ] **Step 7: 提交**

```bash
git add packages/opencode/src/mcp/catalog.ts packages/opencode/src/mcp/index.ts packages/opencode/test/mcp/catalog-ui-event.test.ts
git commit -m "feat(mcp): preserve uiEvent extension in MCP progress notifications"
```

---

### Task 2: Host — fallbackNotificationHandler 兜底捕获非标准 method 通知

**Files:**
- Modify: `packages/opencode/src/mcp/catalog.ts`（`installUiEventNotificationHandlers` 内新增 fallback 分支）
- Test: `packages/opencode/test/mcp/catalog-ui-event.test.ts`（追加第二个测试）

- [ ] **Step 1: 写失败测试（自定义 method 携带 uiEvent 应路由进进度管道）**

在 `packages/opencode/test/mcp/catalog-ui-event.test.ts` 的 `describe` 块内追加：

```ts
  test("routes uiEvent-carrying custom notification methods through the progress pipeline", async () => {
    const received = await run("ui/notifications/step-update")
    expect(received).toHaveLength(1)
    expect(received[0]).toMatchObject({ progress: 1, total: 2, message: "working" })
    expect(received[0].uiEvent).toEqual({ event_type: "images_loaded", image_paths: ["a.png"] })
  })
```

- [ ] **Step 2: 运行测试，确认当前失败（red）**

```bash
bun test test/mcp/catalog-ui-event.test.ts
```

Expected: 新测试 FAIL —— SDK 对未注册 method `ui/notifications/step-update` 静默丢弃，`received` 为空数组。

- [ ] **Step 3: 实现 fallback handler**

修改 `packages/opencode/src/mcp/catalog.ts` 的 `installUiEventNotificationHandlers`：

```ts
export function installUiEventNotificationHandlers(client: Client) {
  client.setNotificationHandler(LooseProgressNotificationSchema, (notification) =>
    dispatchProgress(client, notification as Notification),
  )
  // 兜底捕获未注册 method 的非标准通知：凡携带 progressToken + uiEvent 的，
  // 视为扩展 progress 通知走同一条进度管道（与 notifications/progress 行为一致）。
  client.fallbackNotificationHandler = async (notification) => {
    const params = notification.params
    if (params === undefined || params === null || typeof params !== "object") return
    if ("progressToken" in params && "uiEvent" in params) {
      dispatchProgress(client, notification)
    }
  }
}
```

- [ ] **Step 4: 运行测试，确认通过（green）**

```bash
bun test test/mcp/catalog-ui-event.test.ts
```

Expected: PASS —— 两个测试均通过；`ui/notifications/step-update` 的 uiEvent 到达 onprogress 回调。

- [ ] **Step 5: 类型检查 + 回归 mcp 相关单测**

```bash
bun typecheck
bun test test/mcp/
```

Expected: typecheck 无错误；`test/mcp/` 下既有测试（`catalog.test.ts`、`mcp-ui.test.ts`、`lifecycle.test.ts` 等）全部通过，无回归。

- [ ] **Step 6: 提交**

```bash
git add packages/opencode/src/mcp/catalog.ts packages/opencode/test/mcp/catalog-ui-event.test.ts
git commit -m "feat(mcp): route non-standard uiEvent notifications via fallback handler"
```

---

### Task 3: 文档 + 端到端回归验证

**Files:**
- Modify: `docs/mcp-apps-ui-protocol.md`

- [ ] **Step 1: 文档化 uiEvent 扩展字段支持**

修改 `docs/mcp-apps-ui-protocol.md`，在"后端 host"小节（现有 `1. MCP server` … `7. iframe（step-ui）` 流程，约 L214-220）后补充一段：

```markdown
**uiEvent 扩展字段**：MCP server 可在 `notifications/progress` 的 params 中携带非标准
`uiEvent` 字段（如 pdf2json 的 `content.send_progress_with_data(..., ui_event={...})`），
前端 step-ui 从 `progress.uiEvent.<key>` 读取逐步渲染所需数据。host 用宽松 schema 重注册
`notifications/progress`（`McpCatalog.installUiEventNotificationHandlers`）避免 SDK 剥离
扩展字段，uiEvent 随 `metadata.mcpProgress` 持久化并经 `tool-progress` 事件透传进 iframe；
未注册 method 的非标准通知若携带 `progressToken + uiEvent`，由 `fallbackNotificationHandler`
兜底走同一进度管道。
```

- [ ] **Step 2: Web 端回归验证（e2e）**

Run（在 `packages/app` 下）：

```bash
playwright test e2e/regression/mcp-apps-panel.spec.ts
```

Expected: 全部通过，重点确认 `forwards uiEvent extension data into the step-ui iframe` 用例仍绿（web 侧 mcp-tool → McpAppHost → iframe 的 uiEvent 转发链路无回归）。

- [ ] **Step 3: 提交**

```bash
git add docs/mcp-apps-ui-protocol.md
git commit -m "docs: document uiEvent extension support for MCP notifications"
```

---

## 自检（Self-Review）

**Spec 覆盖**：Host 支持（Task 1 修 strip、Task 2 兜底非标准 method）✓；Web 支持（Task 3 回归验证，web 链路已就绪无需改码）✓；持久化（复用现有 `metadata.mcpProgress`，Task 1 修复后自然生效）✓；文档（Task 3）✓。

**已知限制（不纳入本计划）**：
- `server-sdk.tsx` 的 `coalescedKey()` 以 `mcpProgress.progress` 为合并键，若同一 part 连续两条 uiEvent 携带相同 progress 值可能被合并丢弃；pdf2json 各事件 progress 互不相同，暂不受影响。
- 大体积 uiEvent（如 `partial_page_graphs`）会随 part metadata 序列化/SSE 传输，属既有性能特征，非正确性问题。

**占位符扫描**：无 TBD/TODO/占位，所有代码块为完整实现。

**类型一致性**：`LooseProgressNotificationSchema`、`dispatchProgress`、`installUiEventNotificationHandlers` 在 Task 1 定义、Task 2 扩展、测试引用，命名全程一致；`McpProgress.uiEvent`（既有类型）与测试断言一致。
