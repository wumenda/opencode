# OpenCode MCP Apps UI 协议支持情况

本文档记录当前 OpenCode（web 前端 + 后端 host）对 **MCP Apps UI 扩展**（SEP-1865 思路）的实际支持情况，涵盖资源暴露、前端渲染、宿主↔iframe 通信、事件分发、进度推送与两级 Tab 的完整链路。内容基于当前代码实现，作为协议能力说明与后续维护的参考。

---

## 1. 概述

MCP Apps UI 让 MCP 工具通过 `ui://` 资源暴露一段可交互的 HTML 界面。OpenCode 支持两种渲染挂载点：

- **对话流工具卡内**：工具运行/完成时，工具卡下方挂载一个 iframe（`McpTool` → `McpAppView`）。
- **右侧"应用程序"面板**：按 `skill → tool` 两级 Tab 组织，渲染同一 App（`McpAppsPanel` → `McpAppView`）。

两者渲染**同一份 `ui://` HTML**，但各自是**独立的 iframe 实例**（独立 blob URL、独立 AppBridge 与 postMessage 通道）。事件通过**进程级共享的 `McpAppHost` 注册表**广播给两个挂载面，各收到同一份副本。

参考实现（演示/测试用）：

- `mcps/pdf2json/mcp_server/tools.py`：`step1/step2/step3` 确定性演示工具，运行期逐步推送 `notifications/progress`。
- `mcps/pdf2json/mcp_apps_ui/step-ui/dist/index.html`：iframe 侧 step-ui，完成 AppBridge 握手并渲染进度。

---

## 2. 资源定义与暴露

### 2.1 `ui://` 资源

MCP server 通过标准 `resources/read` 暴露 `ui://` 前缀的资源：

- `ui://step1/progress.html`、`ui://step2/progress.html` 等（见 `mcps/pdf2json/mcp_server/resources.py`）。
- MIME 类型约定为 `text/html;profile=mcp-app`；前端校验时只看 base 类型（分号前的部分），要求为 `text/html` 或 `application/pdf`（`packages/app/src/lib/mcp-apps/resource.ts` 的 `readUiResource`）。
- HTML 资源可携带 `_meta.ui.csp`（`connectDomains`/`resourceDomains`/`frameDomains`/`scriptDomains`）与 `_meta.ui.permissions`（`clipboardWrite`/`camera`/`microphone`/`geolocation`）。

### 2.2 工具 UI 元数据（`_meta.ui`）

工具声明暴露 UI 的约定（后端解析见 `packages/opencode/src/mcp/catalog.ts` 的 `toolUi`）：

```jsonc
{
  "_meta": {
    "ui": {
      "resourceUri": "ui://step1/progress.html",
      "visibility": ["model", "app"]   // 排除 "model" 时工具不进模型工具列表（仅 App 用）
    }
  }
}
```

兼容读取废弃字段 `ui/resourceUri`。`visibility` 不含 `model` 的工具被 `app-only` 处理，不加入 Agent 的工具列表（`packages/opencode/src/session/tools.ts`）。

### 2.3 资源 HTML 注入

pdf2json 侧 `_get_ui_html`（`mcps/pdf2json/mcp_server/duck_implement/_common.py`）在 `<head>` 注入 `window.__MCP_TOOL_NAME__`，供 iframe 在未收到 `ui/notifications/tool-input` 时按工具名路由。

---

## 3. Tool Part 元数据约定（`metadata.mcp`）

后端在 tool part 的 `state.metadata.mcp` 写入 App 身份与结果（`packages/opencode/src/session/tools.ts`）：

**运行中**（进度回调里写入，本仓库修复后行为）：

```jsonc
"mcp": { "server": "remote-server", "tool": "step1", "ui": { "resourceUri": "...", "visibility": [...] } }
```

**完成时**（`completeToolCall` 输出里构建）：

```jsonc
"mcp": {
  "server": "remote-server",
  "tool": "step1",
  "ui": { "resourceUri": "...", "visibility": [...] },
  "meta": { ... },                                        // 可选，来自 result._meta
  "result": { "content": [...], "structuredContent": ... }
}
```

配套字段：

- `state.metadata.mcpProgress`：`{ progress, total, message, time }`，运行期逐级更新。
- 完成时 `metadata.truncated` / `metadata.outputPath`：输出截断标记。

前端解析入口（`packages/session-ui/src/components/mcp-tool.tsx`）：

- `mcpAppFromPart(part)` → `McpAppInfo`（需 `metadata.mcp.ui.resourceUri`）。
- `skillNameFromPart(part)` → skill 名（`tool === "skill"` 时取 `input.name`）。
- `mcpProgressFromPart(part)` → 运行中的进度。

---

## 4. 前端渲染链路

### 4.1 组件职责

| 组件 | 位置 | 职责 |
|---|---|---|
| `McpAppRenderer` | `packages/session-ui/src/context/mcp-app.tsx` | 宿主注入的渲染器接口 |
| `renderMcpApp` | `packages/app/src/pages/directory-layout.tsx` | 把渲染器实现为 `McpAppView` |
| `McpAppView` | `packages/app/src/components/mcp-app-view.tsx` | iframe 挂载、AppBridge 接线、事件转发 |
| `McpTool` | `packages/session-ui/src/components/mcp-tool.tsx` | 对话流工具卡，推送进度/结果事件 |
| `McpAppsPanel` | `packages/app/src/pages/session/v2/mcp-apps-panel.tsx` | 侧栏两级 Tab 面板 |
| `McpAppHost` | `packages/session-ui/src/context/mcp-app-host.tsx` | 进程级事件注册表 |

### 4.2 McpAppView 加载流程

1. `ensureConnected`：查询 `/api/mcp` 状态；未连接则 `POST /api/mcp/:name/connect`，轮询直至 connected。
2. 新建 `Client`，接 `HttpRpcTransport`（`POST /api/mcp/:name/rpc`，携带 `directory` 与认证头）。
3. `readUiResource` 读取 `ui://` HTML。
4. `buildSandboxedHtml`：注入 CSP、`URL.createObjectURL` 生成 blob URL，sandbox 令牌 `allow-scripts`（+ 可选 `allow-clipboard-write`），`allow` 属性映射权限策略。
5. iframe `onLoad` → 新建 `AppBridge` + `PostMessageTransport` → `connect`，握手完成后冲刷缓冲事件。

> **组件复用与重新加载**：`McpAppView` 由 `createEffect` 驱动 `start()`——首次挂载及 `server`/`resourceUri` prop 变化（如侧栏面板在多个 tool tab 间切换复用同一组件实例）时都会重新加载 iframe。若只在 `onMount` 加载一次，切换 tab 会出现"iframe HTML 残留上一个 App、进度内容却按新 key 正确路由"的错位。`start()` 会重置 `appInitialized` 并重建 AppBridge/blob URL。

### 4.3 沙箱策略

- CSP：`default-src 'none'`；`script-src 'unsafe-inline' 'self' data:` + 声明的 scriptDomains；`connect-src` 限声明域名；`frame-ancestors 'self'`。
- iframe sandbox：仅 `allow-scripts`（无 `allow-same-origin`，iframe 无法读写父页面 DOM，且 blob 文档内容不可被父页直接读取）。
- 权限（Permission-Policy allow）：`clipboard-write` / `camera` / `microphone` / `geolocation` 按资源声明启用。

---

## 5. 宿主 ↔ 应用通信协议

iframe 侧走 **AppBridge**（`@modelcontextprotocol/ext-apps/app-bridge`），底层是 `PostMessageTransport`（JSON-RPC over `postMessage`）。

### 5.1 握手（iframe → 宿主）

- `ui/initialize` 请求：`{ protocolVersion, appInfo, appCapabilities }`。
- `ui/notifications/initialized` 通知。
- step-ui 采用**重试握手**：首包可能早于宿主监听窗口被丢弃，故 600ms 超时 + 400ms 间隔重试，直到收到响应再发 initialized。

### 5.2 宿主能力声明（hostCapabilities）

`packages/app/src/lib/mcp-apps/bridge.ts`：

```jsonc
{
  "openLinks": {}, "downloadFile": {}, "message": {}, "sampling": {},
  "serverTools": {}, "serverResources": {}, "logging": {}
}
```

### 5.3 宿主上下文（hostContext）

`packages/app/src/lib/mcp-apps/host-context.ts`：

```jsonc
{
  "theme": "light" | "dark",
  "displayMode": "inline",
  "containerDimensions": { "width": ..., "height": ... },
  "locale": "…", "timeZone": "…",
  "platform": "web",
  "deviceCapabilities": { "touch": false, "hover": true }
}
```

容器尺寸变化（ResizeObserver）与主题变化会实时推送最新 hostContext。

### 5.4 宿主侧 AppBridge 回调

| 回调 | 行为 |
|---|---|
| `oninitialized` | 标记就绪、冲刷 pending、回放 `fallbackData`（tool-result） |
| `onopenlink` | 交 `platform.openExternal` 打开链接 |
| `onmessage` | 以 toast 上屏 |
| `onupdatemodelcontext` | 写入进程级 model context store（`modelContextHost`） |
| `onrequestteardown` | `teardownResource` 后关闭桥 |
| `ondownloadfile` | 下载文件/资源 |
| `onrequestdisplaymode` | 协商显示模式（见 5.5） |
| `onsizechange` | 调整 iframe 高度（autoHeight） |

### 5.5 显示模式协商

`packages/app/src/lib/mcp-apps/display-mode.ts`：`SUPPORTED_DISPLAY_MODES = ["inline"]`。请求 `fullscreen`/`pip` 时回退 `inline`。

---

## 6. 宿主事件分发（McpAppHost 注册表）

`createMcpAppHostRegistry()`（`packages/session-ui/src/context/mcp-app-host.tsx`）为**进程级单例**（`packages/app/src/pages/directory-layout.tsx`）。

- appKey：`` `${sessionID}:${server}/${resourceUri}` ``（`sessionID` 缺失时退化为 `` `${server}/${resourceUri}` ``）。
- **跨 session 隔离**：appKey 携带归属会话。`McpTool` 从 `part.sessionID`、`McpAppView` 从 `sessionID` prop（对话流经 `McpAppRendererInput.sessionID`，侧栏经 `McpAppsPanel.sessionID`）构造同一格式 key；不同会话的同一 `ui://` App 使用不同 key，事件、pending 缓冲、lastProgress 互不串扰。
- **会话切换重注册**：`McpAppView` 以 `createEffect` 跟随 appKey 变化——切换 session 时注销旧 key、清空 pending、注册新 key，只接收当前会话的事件。
- 生产者：`McpTool` 调用 `host.push(appKey, event)`。
- 消费者：每个 `McpAppView` 通过 `createEffect` 跟随 appKey 注册/注销 `host.register(appKey, sink)`。
- **多 sink 广播**：同一 appKey 下所有已注册 sink 都会收到事件（对话流工具卡 + 侧栏面板共享同一 key）。
- **lastProgress 重放**：注册表记住最近一次 `tool-progress`，新 sink 注册（iframe 重挂载）时重放，避免进度回到 "0% / 就绪"。
- **pending 缓冲**：App 未挂载时 push 的事件暂存，首个 sink 注册时冲刷。

事件类型：

| 事件 | 载荷 | 说明 |
|---|---|---|
| `tool-input-partial` | `{ arguments }` | 运行中部分输入 |
| `tool-result` | `{ result: CallToolResult }` | 完成结果（`metadata.mcp.result`） |
| `tool-cancelled` | `{ reason }` | 取消原因 |
| `tool-progress` | `{ progress, total?, message? }` | 实时进度 |

### 6.1 宿主 → iframe 转发（McpAppView.forward）

| 事件 | 转发方式 |
|---|---|
| `tool-input-partial` | `bridge.sendToolInputPartial` |
| `tool-result` | `bridge.sendToolResult` |
| `tool-cancelled` | `bridge.sendToolCancelled` |
| `tool-progress` | 底层 `appTransport.send({ method: "notifications/progress" })`（标准 MCP 进度通知透传） |

---

## 7. 进度推送链路（端到端）

1. **MCP server**：`ctx.report_progress(progress, total, message)` 逐级推送（如 `step1/step2` 默认 5 步、步间 350ms，见 `mcps/pdf2json/mcp_server/tools.py`）。
2. **后端 host**：SDK `onprogress` 回调 → `updateToolCall` 把进度写入 tool part 的 `state.metadata.mcpProgress`（并携带 `mcp:{server,tool,ui}`）→ `session.updatePart` 发 `message.part.updated`。
3. **SSE 事件流**：`/global/event` 或 `/api/event` 推送到前端。
4. **前端 store**：`server-session.ts` 更新 `data.part`；`server-sdk.tsx` 的合并键含 `mcpProgress.progress`，保留 1/5→5/5 中间步骤。
5. **对话流工具卡**：`McpTool` 的 `mcp-tool-progress` 进度条实时渲染；同时 `host.push(tool-progress)`。
6. **注册表广播**：同一 appKey 的所有 `McpAppView` 收到事件 → 各自 `forward` 进 iframe。
7. **iframe（step-ui）**：监听 `notifications/progress` → 更新进度条/百分比/计数/消息。

**uiEvent 扩展字段**：MCP server 可在 `notifications/progress` 的 params 中携带非标准
`uiEvent` 字段（如 pdf2json 的 `content.send_progress_with_data(..., ui_event={...})`），
前端 step-ui 从 `progress.uiEvent.<key>` 读取逐步渲染所需数据。host 用宽松 schema 重注册
`notifications/progress`（`McpCatalog.installUiEventNotificationHandlers`）避免 SDK 剥离
扩展字段，uiEvent 随 `metadata.mcpProgress` 持久化并经 `tool-progress` 事件透传进 iframe；
未注册 method 的非标准通知若携带 `progressToken + uiEvent`，由 `fallbackNotificationHandler`
兜底走同一进度管道。

### 7.1 完成态最终进度持久化与回放（刷新/切会话后恢复）

运行期进度只存在于前端内存与 SSE 事件流中，整页刷新/切换会话后即丢失。为此在**完成时持久化最终进度**：

- **后端**（`packages/opencode/src/session/tools.ts`）：进度回调闭包记忆 `lastProgress`；工具完成写入 part 的 `state.metadata.mcpProgress = lastProgress`（随会话数据持久化到后端存储）。运行期 `mcp`（server/tool/ui）元数据也提前写入，保证刷新后前端仍能解析出 `ui://` 资源并挂载 iframe。
- **前端**（`packages/session-ui/src/components/mcp-tool.tsx`）：`McpTool` 的 `completedProgressFromPart` 从 completed part 提取最终进度，在 completed 时向注册表 `push` 一次 `tool-progress`（最终值）。刷新后新挂载的 `McpAppView` 注册时收到该重放并转发进 iframe，恢复 "100% / 5 / 5 / 步骤一：解析输入 5/5"。

### 7.2 McpAppView 跨 tab 重载时的进度恢复

侧栏面板在 skill 下切换 tool tab（如 step1 ↔ step3）复用同一个 `McpAppView` 组件实例。`McpAppView` 的注册与 iframe 重载逻辑合并为一个 effect：`resourceUri` 变化时**先**同步重载 iframe（清空旧 bridge / `appInitialized`），**再**重注册 sink。这样 `host.register` 重放的 `lastProgress` 会进入新 iframe 的 pending 缓冲，待握手完成后冲刷，避免重放事件被 `forward` 到旧 bridge 而丢失（表现为切 tab 后进度回退 "0% / 就绪"）。

---

## 8. Skill → Tool 两级 Tab

`packages/app/src/pages/session/v2/use-mcp-apps.ts` 遍历会话消息/parts，维护 `currentSkill` 游标：

- `skillNameFromPart`（skill 工具 part 的 `input.name`）切换当前 skill。
- 其后带 `ui://` 的工具归入该 skill 分组；skill 之外为直连分组（`name === undefined`）。
- `buildSkillAppGroups`（`mcp-apps-panel-state.ts`）：按 `skill::server::resourceUri` 去重，保持首次出现顺序。

面板行为（`mcp-apps-panel.tsx`）：

- 一级 skill Tab 带工具数量角标；二级 tool Tab 以 `resourceUri` 为文本，懒挂载只渲染激活项。
- **自动切换焦点**：监听 `latestExecuted`（最近一次执行的 App + 其 partID），新 tool 执行（含同一 `resourceUri` 的重复执行）时自动把焦点切到该 tool 的 UI；同一 part 的进度刷新不触发重复切换。

---

## 9. 支持矩阵与已知限制

| 能力 | 状态 | 说明 |
|---|---|---|
| `ui://` HTML 资源渲染 | ✅ | `text/html`（含 `text/html;profile=mcp-app`）；二进制 `application/pdf` 走 blob 渲染 |
| 工具内联 App（对话流） | ✅ | `McpTool` 工具卡下挂载 iframe |
| 侧栏面板两级 Tab | ✅ | `skill → tool`，自动聚焦最新执行 |
| 运行期进度推送 | ✅ | `notifications/progress` 全链路透传 |
| 完成结果回放 | ✅ | `tool-result` + `fallbackData` |
| 运行中输入流式 | ✅ | `tool-input-partial` |
| 取消通知 | ✅ | `tool-cancelled` |
| 显示模式 | ⚠️ 仅 `inline` | `fullscreen`/`pip` 请求回退 inline |
| 文件下载 / 打开链接 / 消息 | ✅ | `ondownloadfile` / `onopenlink` / `onmessage` |
| 模型上下文更新 | ✅ | `onupdatemodelcontext` → `modelContextHost` |
| 沙箱隔离 | ✅ | CSP + `sandbox="allow-scripts"`，无 `allow-same-origin` |
| 多挂载面事件同步 | ✅ | 注册表多 sink 广播 + lastProgress 重放 |
| iframe 重挂载进度恢复 | ✅ | 注册表重放最近进度；整页刷新/切会话由完成态持久化的 `metadata.mcpProgress` 回放 |

已知限制 / 注意点：

- **iframe 沙箱**：无 `allow-same-origin`，父页面不能直接 `contentDocument` 读取 iframe 内容（调试需借助浏览器 frame 级工具）。
- **完成态持久化仅对修复后执行的工具生效**：历史会话中（修复前）完成的 tool part 没有 `metadata.mcpProgress`，刷新后其 iframe 无法回放最终进度（回退初始 "就绪" 态）。重新执行工具后即恢复。
- **进度事件合并**：正常情况下 5 步完整转发；主线程繁忙时同一 flush 窗口内的同 part 进度可能合并，UI 表现为跳变。
- **握手时序**：iframe 侧 AppBridge 握手晚于工具运行结束时，进度事件先入 pending，初始化后一次性冲刷（显示最终进度而非逐级）。

---

## 10. 关键代码位置索引

| 关注点 | 路径 |
|---|---|
| 资源 MIME 校验 / 沙箱构建 | `packages/app/src/lib/mcp-apps/resource.ts` |
| RPC 中继 Transport | `packages/app/src/lib/mcp-apps/http-rpc-transport.ts` |
| 宿主能力 / 上下文 | `packages/app/src/lib/mcp-apps/bridge.ts`、`host-context.ts` |
| 显示模式 | `packages/app/src/lib/mcp-apps/display-mode.ts` |
| iframe 挂载与转发 | `packages/app/src/components/mcp-app-view.tsx` |
| 事件注册表 | `packages/session-ui/src/context/mcp-app-host.tsx` |
| 工具卡渲染与进度解析 | `packages/session-ui/src/components/mcp-tool.tsx` |
| 渲染器接口 | `packages/session-ui/src/context/mcp-app.tsx` |
| 侧栏两级 Tab | `packages/app/src/pages/session/v2/mcp-apps-panel.tsx`、`use-mcp-apps.ts`、`mcp-apps-panel-state.ts` |
| 后端 metadata.mcp / 进度 | `packages/opencode/src/session/tools.ts`、`packages/opencode/src/mcp/catalog.ts` |
| 前端 store / 事件合并 | `packages/app/src/context/server-session.ts`、`server-sdk.tsx` |
| 演示 MCP server | `mcps/pdf2json/mcp_server/tools.py`、`resources.py` |
| step-ui（iframe 侧） | `mcps/pdf2json/mcp_apps_ui/step-ui/dist/index.html` |
