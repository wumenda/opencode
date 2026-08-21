# MCP Apps Web 侧执行步骤文档

> 适用范围：opencode 源码二次开发——Web 端完整支持 MCP Apps 协议（SEP-1865）。
> 前置文档：`MCP-Apps-概述.md`（协议规范）、`CODEBASE_ANALYSIS.md`（代码库结构）。
> 执行方式：按任务顺序执行，每个任务内遵循 TDD（先写失败测试→验证失败→最小实现→验证通过→提交）。
> 每 3-4 个任务向用户汇报进度，等待确认后继续。

---

## 0. 背景与已落地契约（Host 侧，已完成）

Host 侧（packages/opencode）已实现并通过 typecheck，Web 侧开发依赖以下三个数据契约。

### 契约 1：ToolPart.metadata.mcp（工具结果 UI 元数据）

MCP 工具执行完成后，结果 part 的 `metadata.mcp` 字段携带 UI 渲染所需信息：

```ts
// packages/schema/src/v1/session.ts ToolPart.metadata（Record<string, any>）
metadata.mcp = {
  server: string          // MCP server 配置名（如 "weather"）
  tool: string            // 原生工具名（不带 server 前缀）
  ui: {
    resourceUri?: string  // ui:// 资源 URI，App HTML 入口
    visibility: Array<"model" | "app">
  }
  meta?: unknown          // MCP result._meta 原样透传（含 result._meta.ui）
  result: {
    content: Array<{ type: "text"|"image"|"resource", ... }>
    structuredContent?: unknown
  }
}
```

来源：[session/tools.ts](../packages/opencode/src/session/tools.ts#L490-L506)。

### 契约 2：ToolPart.metadata.mcpProgress（执行进度）

UI 工具执行中，MCP progress 通知实时更新（仅 `state.status === "running"` 时）：

```ts
metadata.mcpProgress = { progress: number, total?: number, message?: string, time: number }
```

### 契约 3：POST /mcp/:name/rpc（JSON-RPC 方法代理端点）

浏览器侧 MCP Client 的 HTTP 通道，定义于 [groups/mcp.ts](../packages/opencode/src/server/routes/instance/httpapi/groups/mcp.ts#L149-L162)：

```
POST /mcp/:name/rpc
Body: { method: string, params?: unknown }
→ 200: JSON-RPC result 部分（任意 JSON）
→ 404 McpServerNotFoundError（server 未配置）
→ 400 McpRpcError（server 未连接 / 方法不支持 / MCP 调用失败）
```

支持方法：`initialize`、`ping`、`tools/list`、`tools/call`、`resources/list`、`resources/read`、`resources/templates/list`、`prompts/list`、`prompts/get`。

**注意**：`:name` 必须是已通过 `connect` 端点连接的 server；未连接时 App 需先触发 `POST /mcp/:name/connect`。

---

## 1. Web 侧目标架构

```
packages/app（SolidJS）
├── src/lib/mcp-apps/
│   ├── http-rpc-transport.ts   # MCP SDK Transport → POST /mcp/:name/rpc 适配器
│   ├── app-bridge-host.ts      # AppBridge 封装：iframe ↔ host MCP client 桥接
│   └── resource.ts             # ui:// 资源读取 + CSP 注入 + blob URL 生成
├── src/components/mcp-app-view.tsx  # 沙箱 iframe 组件（时间线内联）
└── src/pages/session/timeline/...   # tool part 渲染集成点
```

渲染决策（已与用户确认）：
- **iframe 渲染位置**：时间线内联（工具 part 下方，随对话滚动）；
- **App 内工具调用权限**：直接透传来源 MCP server，不走 opencode 权限弹窗；
- **协议实现**：官方 `@modelcontextprotocol/ext-apps` SDK（AppBridge）。

---

## 2. 任务分解

### 任务 6：安装 ext-apps 依赖 + HTTP JSON-RPC transport

**目标**：浏览器内建立起"App ↔ Host ↔ MCP server"的 JSON-RPC 通道。

**步骤**：

1. **确认 API 形状（动手前必做）**
   - `bun add @modelcontextprotocol/ext-apps`（在 `packages/app`；版本以 npm 最新为准，预期 2026.x 预发布版）。
   - 通读 `node_modules/@modelcontextprotocol/ext-apps/dist/*.d.ts`，重点确认：
     - `AppBridge` 构造签名（预期接收 MCP SDK `Transport` 实例与 iframe 元素/窗口引用）；
     - 消息绑定方式（是自动监听 iframe postMessage，还是需要手动转发）；
     - client 侧 UI 能力协商是否由 AppBridge 自动处理。
   - **若实际 API 与本文档假设不符，以 .d.ts 为准并在本文档记录差异后再继续。**

   **API 确认记录（2026-08-21，以 ext-apps@1.7.5 .d.ts 为准）**：
   - ext-apps 为稳定版 1.7.5（非预期的 2026.x 预发布）；
   - `AppBridge` 构造签名：`new AppBridge(client: Client | null, hostInfo, capabilities)` —— 接收 MCP SDK **Client 实例**（非 Transport）；iframe 通信用 `PostMessageTransport(iframe.contentWindow, iframe.contentWindow)` 传给 `bridge.connect()`；
   - `PostMessageTransport` 通过 `event.source === iframe.contentWindow` 验证消息来源（安全假设成立）；
   - **AppBridge 要求浏览器侧 Client 先完成 initialize 握手**（`client.connect(transport)` 后才能 `bridge.connect()`）→ `HttpRpcTransport` 承载 Client 的全部 JSON-RPC 消息（initialize/tools/call 等）；
   - peer 依赖 `@modelcontextprotocol/sdk@^1.29.0`、`zod@^4`（运行时 `import "zod/v4"`）需显式安装：已装 `@modelcontextprotocol/sdk@1.29.0`（与 host 同版本）+ `zod@4.4.3`；
   - **偏差**：vendored client（`opencode-ai-client-1.17.13-v2.tgz`）的 `mcp` 命名空间无 `rpc` 方法（host 提交未重新生成 client SDK），transport 改用原生 `fetch`（测试注入 `fetchFn`），不走 `client.mcp.rpc()`。

2. **TDD：`src/lib/mcp-apps/http-rpc-transport.ts`**
   - 先写 `src/lib/mcp-apps/http-rpc-transport.test.ts`：
     - 请求消息（带 `id`）→ fetch 收到 `POST /mcp/:name/rpc`，body 为 `{method, params}`；
     - 响应 result → 包装为 JSON-RPC response `{jsonrpc:"2.0", id, result}` 并触发 `onmessage`；
     - 响应错误 → 包装为 `{jsonrpc:"2.0", id, error}`；
     - 通知（无 `id`）→ 发送但不等待/不触发 onmessage；
     - `close()` 后不再发送。
   - 实现 `HttpRpcTransport`：实现 `@modelcontextprotocol/sdk` 的 `Transport` 接口（`start/send/close` + `onmessage/onclose/onerror`），内部用生成的 client SDK `client.mcp.rpc()` 方法。
   - fetch mock 用测试内注入 `fetchFn` 参数，不用 globalThis 覆盖（仓库测试规范）。

3. **TDD：`src/lib/mcp-apps/resource.ts`**
   - `readUiResource(server, uri)`：调 `resources/read`，校验 `contents[0]` 为 `text/html`，非 HTML 抛错。
   - `buildSandboxedHtml(html)`：在 `<head>` 顶部注入 CSP meta：
     ```html
     <meta http-equiv="Content-Security-Policy"
           content="default-src 'none'; script-src 'unsafe-inline' 'self' data:; style-src 'unsafe-inline'; img-src data: blob:; connect-src 'none'; frame-ancestors 'self'">
     ```
     （若 HTML 无 `<head>`，包一层完整文档结构。）返回 blob URL。
   - `revokeObjectURL` 清理函数。

**验证**：
- `cd packages/app && bun test src/lib/mcp-apps/`
- `bun typecheck`

**完成标准**：transport 与 resource 单测全绿；typecheck 通过。

---

### 任务 7：McpAppView 沙箱 iframe 组件

**目标**：可复用的 App 渲染组件，管理 AppBridge 完整生命周期。

**组件接口**：

```tsx
<McpAppView
  server={string}            // MCP server 配置名
  resourceUri={string}       // ui:// 资源 URI
  fallbackData?: unknown     // 可选：契约 1 的 metadata.mcp.result，经 postMessage 初始注入
  onError?: (msg: string) => void
/>
```

**步骤**：

1. **实现 `src/components/mcp-app-view.tsx`**（SolidJS，onMount/onCleanup 管理生命周期）：
   - 挂载时流程：
     ```
     检查 server 连接状态（GET /mcp，读 status map）
       └─ 未连接 → POST /mcp/:name/connect → 轮询等待（上限 30s）
     readUiResource(server, resourceUri) → buildSandboxedHtml → blob URL
     <iframe src={blobUrl} sandbox="allow-scripts" />
     创建 HttpRpcTransport(server) + AppBridge 绑定 iframe
     ```
   - 卸载时（onCleanup）：`AppBridge.close()` → `transport.close()` → `revokeObjectURL`。
   - 加载/错误/空态渲染：加载中显示骨架（复用现有 spinner 样式）、错误显示可重试提示（`McpServerNotFoundError` → "MCP server 未连接，点击重试"）。
   - iframe 定高（默认 320px，可后续加 resize 消息协议）。

2. **安全边界（实现时逐条自查）**：
   - `sandbox` 属性仅 `allow-scripts`（无 `allow-same-origin`，blob URL 也不同源）；
   - CSP 由任务 6 的 `buildSandboxedHtml` 注入；
   - 不透传 `allow-forms/allow-popups/allow-top-navigation`；
   - AppBridge 消息仅接受来自本 iframe `contentWindow` 的 postMessage（官方 SDK 行为，需在 .d.ts 确认）。

3. **单测**：组件级测试可选（仓库 app 包测试基建薄弱则跳过组件测试，靠任务 8 集成 + 任务 9 端到端覆盖），transport/resource 已在任务 6 覆盖。

**验证**：`bun typecheck`；手动 `bun dev:web` + 临时测试页挂一个固定 server/resourceUri 检查 iframe 渲染与生命周期。

**完成标准**：组件可挂载/卸载无泄漏（Network 面板无残留请求、无孤儿 postMessage listener）。

---

### 任务 8：时间线 tool part 渲染集成

**目标**：带 UI 的 MCP 工具结果在时间线内联渲染 App。

**步骤**：

1. **定位渲染分发点**：
   - [message-timeline.tsx](../packages/app/src/pages/session/timeline/message-timeline.tsx#L1023-L1089)（assistant part 渲染）；
   - [session-message.ts](../packages/app/src/utils/session-message.ts#L303-L365)（`SessionMessageAssistantTool` → `ToolPart` 转换，确认 `metadata` 完整透传到 web 侧数据结构，若被过滤则在此补齐）。

2. **集成逻辑**（新建或扩展 tool part 展开态组件）：
   ```
   part.type === "tool" && part.metadata?.mcp?.ui?.resourceUri && part.state.status === "completed"
     → 在工具结果下方渲染 <McpAppView server={metadata.mcp.server} resourceUri={...} fallbackData={metadata.mcp.result} />
   ```

3. **流式进度展示**：`part.metadata?.mcpProgress` 存在且工具 running 时，在工具卡片显示进度条（`progress/total/message`）。纯 UI，不影响数据层。

4. **性能防抖**：
   - 同一 callID 的 App 不因 part 更新事件重建（用 `createMemo` 缓存 McpAppView props，key 用 `callID`）；
   - 折叠态不挂载 iframe（仅展开时渲染）。

**验证**：`bun typecheck`；`bun dev:web` 手动触发一次带 UI 的 MCP 工具调用，确认时间线出现 App。

**完成标准**：工具结果 UI 在时间线内联渲染；进度条随 MCP progress 更新；折叠/展开不重建 iframe。

---

### 任务 9：测试与端到端验证

**目标**：Host 侧单测补齐 + 全链路可复现验证。

**步骤**：

1. **Host 侧 TDD 补测**（`packages/opencode/test/mcp/`）：
   - `toolUi()`：`_meta.ui.resourceUri` 新格式 / `ui/resourceUri` 废弃格式 / 无 `_meta` / `visibility: ["app"]` 过滤，四例；
   - `session/tools.ts` 的 metadata 组装（参照现有 catalog.test.ts 的 mock 风格）；
   - rpc handler：mock `mcp.clients()`，验证方法转发与 404/400 分支。

2. **最小 MCP Apps 测试 server**（端到端夹具，放 `packages/opencode/test/mcp/fixtures/ui-server.ts`）：
   - stdio server，暴露：
     - 工具 `show_dashboard`：`_meta.ui.resourceUri = "ui://dashboard"`，结果 `_meta.ui` 同步指向；
     - resource `ui://dashboard`：返回一段含按钮的最小 HTML（点击按钮调 `tools/list` 验证 AppBridge 双向通信）。
   - 用 `@modelcontextprotocol/sdk` server 侧 API（host 依赖里已有）。

3. **端到端手动验证清单**（可复现，记录到本文档末尾）：
   ```
   a. opencode.json 配置 ui-server（stdio）
   b. cd packages/opencode && bun dev serve
   c. cd packages/app && bun dev:web
   d. 会话中让模型调用 show_dashboard
   e. 验证：时间线出现 iframe App；App 内按钮可触发 tools/list（Network 面板见 /mcp/:name/rpc）；进度条更新；折叠/展开正常；刷新页面后历史 part 的 App 仍可渲染
   ```

**完成标准**：单测全绿；端到端清单逐项通过并留痕。

---

## 3. 风险与备选方案

| 风险 | 影响 | 备选 |
|---|---|---|
| ext-apps 为预发布版，API 与假设不符 | 任务 6/7 返工 | 以 .d.ts 为准调整；桥接层集中在 `app-bridge-host.ts`，更换实现只动一个文件 |
| ext-apps 在浏览器/SolidJS 环境不可用 | 协议实现从零 | 手写 JSON-RPC over postMessage（规范已获取，工作量约 3-4 倍，仅作兜底） |
| blob URL + sandbox 的 CSP 注入被浏览器策略覆盖 | App 渲染失败 | 改用 `srcdoc`；再不行降级为 data: URL |
| V2 会话事件不透传 metadata | Web 拿不到 mcp 契约 | 检查 event-reducer/server-session-v2-reducer 的 part 投影，补透传 |
| App 高度固定导致内容裁切 | 体验问题 | 后续加 resize postMessage 协议（spec 允许），MVP 不做 |

## 4. 提交规范

- 每任务一提交：`feat(app): ...` / `test(mcp): ...`，`git add` 具体路径；
- 改动涉及 `packages/opencode` 的测试在包目录内运行；
- 不手改 `packages/client/src/generated*`。

## 5. 端到端验证留痕（任务 9 完成后填写）

### 已自动化完成的验证（单测级，全绿）

- [x] **toolUi() 单测**（`packages/opencode/test/mcp/mcp-ui.test.ts`，4 例）：`_meta.ui.resourceUri` 新格式 / `_meta["ui/resourceUri"]` 废弃格式 / 无 `_meta` 返回 undefined / `visibility: ["app"]` 保留 app-only。
- [x] **rpc handler 集成测试**（`packages/opencode/test/server/httpapi-mcp-rpc.test.ts`）：真实 HTTP MCP SDK server，验证 `tools/list` 200 转发、`resources/subscribe` 400（McpRpcError）、缺失 server 404（McpServerNotFoundError）。
- [x] **最小 MCP Apps 测试 server**（`packages/opencode/test/mcp/fixtures/ui-server.ts`）：stdio server，暴露 `show_dashboard` 工具（`_meta.ui.resourceUri = "ui://dashboard"`）与 `ui://dashboard` 资源（HTML 内含调用 `tools/list` 的按钮，验证 AppBridge 双向通信）。

### 手动端到端清单（需真实模型 provider，待执行）

```
a. opencode.json 配置 ui-server（stdio）：
   "mcp": { "ui-server": { "type": "local", "command": ["bun", "run", "packages/opencode/test/mcp/fixtures/ui-server.ts"] } }
b. cd packages/opencode && bun dev serve
c. cd packages/app && bun dev:web
d. 会话中让模型调用 show_dashboard
e. 验证：时间线出现 iframe App；App 内按钮可触发 tools/list（Network 面板见 /api/mcp/ui-server/rpc）；进度条更新；折叠/展开正常；刷新页面后历史 part 的 App 仍可渲染
```

- [ ] a. 配置 ui-server
- [ ] b/c. 启动 serve + web
- [ ] d. 触发工具调用
- [ ] e. iframe 渲染 / 双向通信 / 进度 / 折叠 / 刷新恢复
