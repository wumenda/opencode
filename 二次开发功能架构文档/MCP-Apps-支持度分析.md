# MCP Apps 协议支持度分析（Host / Web 端）· 更新版

> 分析对象：以 [MCP-Apps-概述.md](./MCP-Apps-%E6%A6%82%E8%BF%B0.md) 与 ext-apps 规范（`2026-01-26`，`@modelcontextprotocol/ext-apps@1.7.5`）为基准。
> "Host" 指 opencode 后端（`packages/opencode`，httpapi 的 `/api/mcp/:name/rpc` relay）；"Web" 指前端（`packages/app`，`McpAppView` / `AppBridge`；以及 `packages/session-ui` 的 `mcp-tool.tsx`）。
> 本版本为逐文件核对源码后的**当前实态**，取代早期基于印象的旧版结论——旧版标注的多项"未实现"（openLink、hostContext、blob/PDF 资源、资源 csp/permissions、sampling relay、teardown/message/updateModelContext、size-change）现已落地。

**结论先行：核心能力已基本完整，但**仍未"完全支持所有特性"**。核心渲染 + AppBridge 双向桥接 + 核心工具/资源/提示代理 + 结果回放 + 进度 + 打开外链 + 自动尺寸 + 运行中流式 push（tool-input-partial / tool-result）+ 二进制 blob 渲染 + `ui/message` 上屏 + `ui/open-link` + `ui/download-file` + 优雅 teardown + hostContext（主题/时区/locale/尺寸）均已落地并可直接支持常见演示 App；仍缺失或占位：sampling 的宿主侧真实 LLM 实现（capability 未声明）、`ui/update-model-context` 仅日志、camera/mic/geolocation 权限、hostContext 的实时 `setHostContext` 订阅、以及 E2E 需在具备 Playwright 浏览器的环境下跑通。**

---

## 1. 已覆盖的核心链路（逐文件核实，可用）

| 环节 | 实现位置 | 状态 |
|---|---|---|
| 工具声明 `metadata.mcp` + `ui.resourceUri` → 提取 App | `session-ui/src/components/mcp-tool.tsx`（`mcpAppFromPart`） | ✅ |
| 抓取 `ui://` 资源（`resources/read` 经 relay） | `app/src/lib/mcp-apps/resource.ts`（`readUiResource`） | ✅ |
| MIME 校验：`text/html` 与 `text/html;profile=mcp-app`（按 `;` 取 base） | `resource.ts` | ✅ |
| 二进制/blob 资源解析与**渲染**（`text` / `blob` / `application/pdf`） | `resource.ts`（`readUiResource` + `buildBinaryResourceUrl`）+ `McpAppView.start` 分派 | ✅ |
| CSP 沙箱化 + blob URL（**含资源 `scriptDomains` 并入 `script-src`**） | `resource.ts`（`injectCsp` / `buildSandboxedHtml`） | ✅ |
| **遵循资源 `_meta.ui.csp` 与 `_meta.ui.permissions`** | `McpAppView.start` → `buildSandboxedHtml(html.text, { csp, permissions })` | ✅（部分，见 §3.1） |
| iframe 渲染（`sandbox="allow-scripts"`，隔离 opaque origin） | `McpAppView` | ✅ |
| AppBridge 握手 `ui/initialize` + `notifications/initialized` | `McpAppView.onIframeLoad`（ext-apps `AppBridge`） | ✅ |
| **结果回放**（初始化后 H→A 推 `ui/notifications/tool-result`） | `next.oninitialized → sendToolResult(fallbackData)` | ✅ |
| **代理 tools / resources / prompts**（app→host→真实服务器） | `HttpRpcTransport` → 浏览器 `Client` → 后端 `rpcCall` | ✅ |
| **进度**：`metadata.mcpProgress` → UI 进度条 | 后端 `session/tools` + `mcp-tool.tsx`（`mcpProgressFromPart`） | ✅ |
| **打开外链** `ui/open-link` | `next.onopenlink → platform.openExternal(url)` | ✅ |
| **自动尺寸** `ui/notifications/size-changed` | `next.onsizechange → setAutoHeight` | ✅（inline 模式） |
| **hostContext**（主题 / 时区 / locale / 尺寸 / displayMode） | `buildHostContext` + AppBridge `{ hostContext }`（`theme` 由 props 透传、`timeZone` 走 `Intl` 兜底） | ⚠️ 缺实时 `setHostContext`（见 §3.4） |
| **运行中流式 push**（`tool-input-partial` + 完成后 `tool-result`） | `session-ui/context/mcp-app-host.tsx`（宿主注册表）+ `mcp-tool.tsx`（running 预渲染并 push）+ `McpAppView`（注册/冲刷） | ✅ |
| Listening（工具运行期 host→app 日志） | `PostMessageTransport.send` 覆写，仅控 `ui/notifications/*` | ⚠️ 诊断用 |
| `ui/message` 上屏 | `onmessage` 提取文本块 → 宿主 toast | ✅（轻量 toast，未写会话） |
| `ui/open-link` / `ui/download-file` / 优雅 teardown | `onopenlink` / `ondownloadfile` / `onrequestteardown → teardownResource` | ✅ |
| tool 占位 handler（日志，不落地） | `onupdatemodelcontext` | ⚠️ 仅日志 |

Host 侧核心代理源：
- 浏览器 `Client` 走 `HttpRpcTransport`（`app/src/lib/mcp-apps/http-rpc-transport.ts`）POST `/api/mcp/:name/rpc?directory=`。
- 后端 relay `rpcCall`（`packages/opencode/src/server/routes/instance/httpapi/handlers/mcp.ts`）现支持 10 个方法：`initialize / ping / tools/list / tools/call / resources/list / resources/read / resources/templates/list / prompts/list / prompts/get / sampling/createMessage`。
- `initialize` 对 `instructions === undefined` 时省略该字段，避免 `Schema.Unknown` 序列化失败（已修）。

---

## 2. 协议特性矩阵（当前实态）

> H→A = Host 发给 App；A→H = App 发给 Host；`—` = 未涉及/无处理；`⚠️` = 有入口或占位但未到生产可用。

### 2.1 A→H 请求（App 请求宿主能力）

| 方法 | 宿主处理 | 现状 |
|---|---|---|
| `ui/initialize` | ✅ | AppBridge `_oninitialize`；返回协议 `2026-01-26`；hostContext 含 locale/尺寸 |
| `ping` | ✅ | 返回 `{}` |
| `tools/list`、`tools/call` | ✅ | 代理 → 浏览器 Client → 后端 `rpcCall` → 真实服务器 |
| `resources/read` / `list` / `templates/list` | ✅ | 同上；text 与 blob 均可读取 |
| `prompts/list`、`prompts/get` | ✅ | 同上 |
| `sampling/createMessage` | ⚠️ | 后端 relay 已代理该方法，但前端**未声明 sampling 能力**、未接 LLM 实现 → App 实际拿不到采样 |
| `ui/open-link` | ✅ | `onopenlink → platform.openExternal(params.url)` |
| `ui/download-file` | ✅ | `ondownloadfile` 触发浏览器下载（EmbeddedResource / ResourceLink 两种分支） |
| `ui/message` | ✅ | `onmessage` 提取文本块 → 宿主 toast 上屏（未写会话存储） |
| `ui/update-model-context` | ⚠️ | `onupdatemodelcontext` 仅 `console.log`，不改变模型上下文 |
| `ui/request-display-mode` | ⚠️ | AppBridge 默认回 `mode:"inline"`，无实际布局切换 |
| `ui/resource-teardown` | ✅ | `onrequestteardown → teardownResource`（向视图发 resource-teardown） |
| `ui/request-teardown` | ✅ | 优雅 teardown 后关桥 |

### 2.2 A→H 通知

| 通知 | 现状 |
|---|---|
| `ui/notifications/initialized` | ✅ 触发结果回放 |
| `ui/notifications/size-changed` | ✅ `onsizechange` 驱动 iframe 自动高度 |
| `ui/notifications/sandbox-proxy-ready` | — 本实现用 blob，不相关 |
| `ui/notifications/tool-input` / `tool-input-partial` | ✅ App 主动上报时宿主可订阅（主路径是 Host 经注册表 H→A 推送） |
| `ui/notifications/tool-result` | ✅ 由 App 上报时宿主订阅（但主路径是 H→A 回放） |
| `ui/notifications/tool-cancelled` | ❌ 宿主不消费 |
| `ui/notifications/host-context-changed` | — hostContext 静态，未走变更上报 |
| 普通 MCP `notifications/progress`（工具进度） | ✅ `metadata.mcpProgress` → UI 进度条 |

### 2.3 H→A 通知（宿主 push 到 App）

| 通知 | 现状 |
|---|---|
| `ui/notifications/tool-result` | ✅ App 初始化后回放结果 / 完成后经注册表 `tool-result` 推送 |
| `ui/notifications/tool-input` / `tool-input-partial` | ✅ 运行中经宿主注册表 `tool-input-partial` 流式推送（running 预渲染） |
| `ui/notifications/tool-cancelled` | ❌ 未实现 |
| `ui/notifications/host-context-changed` | ❌（hostContext 仅初始化设置，无 `setHostContext`） |
| `ui/notifications/sandbox-resource-ready` | ❌（用 blob） |
| `notifications/tools \| resources \| prompts list_changed` | ✅ AppBridge 监听服务器变更并转发 |

---

## 3. 关键缺口细节（逐条说明，含部分实现的反证）

### 3.1 沙箱 CSP / 权限：**较大**遵循，camera/mic/geo 仍缺
`injectCsp` 已把资源 `_meta.ui.csp` 的 `connectDomains / resourceDomains / frameDomains / scriptDomains` 并入 CSP；`buildSandboxedHtml` 据此在 iframe `sandbox` 上追加令牌。
残余硬限制：
- `permissions` 仅落实了 `clipboard-write`；**camera / microphone / geolocation 不授予**（源码注释明确：需宿主端授权策略，此处不静默放行）。
- `connect-src` 若读完 `connectDomains/resourceDomains` 为空仍回退 `'none'`，依赖外部 XHR/WS 且未声明域的应用受限（此即规范要求的声明式白名单，非缺陷）。

### 3.2 二进制/blob 已可渲染
`readUiResource` 返回 `blob`（base64）后，`McpAppView.start` 通过 `buildBinaryResourceUrl` 解码为 mime 型 blob URL 直接作为 iframe 源，pdf/video blob 资源现已可看（Task 2）。

### 3.3 运行中流式 push 已实现（tool-input-partial / tool-result）
新增宿主注册表 `session-ui/context/mcp-app-host.tsx`：McpAppView 按 `${server}/${resourceUri}` 注册 sink，McpTool 在 running 预渲染 App 并推送 `tool-input-partial`，completed 推送 `tool-result`；McpAppView 在 `bridge` 就绪后统一冲刷 pending（Task 4）。`tool-cancelled` 仍未推送。

### 3.4 hostContext 主题/时区已补齐，缺实时推送
`buildHostContext` 现透传 `theme`（props 传入）并用 `Intl.DateTimeFormat().resolvedOptions().timeZone` 兜底 `timeZone`（Task 3）。仍缺：随宿主变化的 `setHostContext` 实时订阅（`host-context-changed`），因仓库暂无现成 `useTheme` 钩子，未做投机性主题订阅。

### 3.5 sampling：后端能 relay，前端不成能力
后端 `rpcCall` 已支持 `sampling/createMessage`，但前端 `hostCapabilities` **未声明 sampling**，`AppBridge` 未接 `oncreatesamplingmessage` 到真实 LLM → App 侧不请求采样（capability 未虚报，语义一致）。

### 3.6 `ui/message` 已上屏，`update-model-context` 仍占位
`onmessage` 现提取文本块经宿主 toast 呈现（Task 5，轻量上屏，未写会话存储）；**`update-model-context` 仍仅打日志**，未落模型上下文。

### 3.7 teardown 已优雅化
`onrequestteardown` 现先 `await bridge.teardownResource({})`（向视图发 `ui/resource-teardown` 等待确认）再关桥（Task 6）；`revoke` 释放 blob URL。

### 3.8 版本/API 对齐——早期补丁已大部分固化且可用
曾经的代差补丁多数已沉淀为稳定实现，但仍是"workaround 而非契约对齐"：
- `mcp.list` 兼容 `{data:Array}` 与 Record 两种形状（`mcp-status.ts` `mcpServerStatus`）。
- `mcp.connect` 改用原生 fetch + `directory` + 轮询，不再依赖 SDK 的 204/`location`（`ensureConnected`）。
- `HttpRpcTransport` 的 `fetch` `.bind(globalThis)` 防止 `Illegal invocation`。
- relay `initialize` 对 `undefined` 的 `instructions` 做省略。
这些让功能可用，但本质是"前端迁就当前后端 contract"，协议/新版 SDK 契约仍未严格对齐，属长期风险。

---

## 4. 支持度评分（当前实态）

| 维度 | 支持度 | 说明 |
|---|---|---|
| 核心渲染（工具→HTML→沙箱 iframe） | 🟢 高 | 可用 |
| 双向桥接 / 代理 tools·resources·prompts | 🟢 高 | 可用（10 方法） |
| 结果回放 + 工具进度 | 🟢 高 | 可用 |
| **运行中流式 push（tool-input-partial / tool-result）** | 🟢 高 | 宿主注册表 + running 预渲染（Task 4） |
| **二进制/blob 资源（读取+渲染）** | 🟢 高 | blob URL 直接渲染（Task 2） |
| 打开外链 `ui/open-link` | 🟢 高 | 可用 |
| **`ui/download-file`** | 🟢 高 | ondownloadfile（Task 6） |
| **优雅 teardown（request→resource）** | 🟢 中高 | teardownResource（Task 6） |
| **`ui/message` 上屏** | 🟡 中 | toast 轻量呈现（Task 5），未写会话 |
| **hostContext（主题/时区/locale/尺寸）** | 🟡 中 | theme/timeZone 已透传；缺实时 setHostContext |
| 自动尺寸 `size-changed` | 🟢 中高 | inline 模式可用 |
| 资源 `csp` / `permissions` 遵循 | 🟡 中 | connect/frame/script/clipboard 可；camera·mic·geo 不行 |
| sampling（真实 LLM） | 🔴 无 | 后端 relay 有；前端不成能力（语义一致，未虚报） |
| `ui/update-model-context` | 🟡 占位 | 仅日志 |
| hostContext 实时推送 & 显示模式切换 | 🔴/🟡 | 静态 inline，无 setHostContext 订阅 |
| 协议版本 / SDK 契约对齐 | 🟡 中 | `2026-01-26`；靠 workaround 支撑 |

---

## 5. 结论与建议

**是否"完全支持所有特性"：接近完善，但非完全。**
现状已从"最小可用宿主"升级为**功能较全的宿主**：能渲染 HTML App（含 blob/pdf）、经 AppBridge 代理核心工具/资源/提示、回放结果、显示进度、打开外链、随内容自适应高度、运行中流式推送工具输入与结果、上屏 `ui/message`、支持下载与优雅 teardown、透传 hostContext 主题/时区。本轮（Task 1–7）已把运行中流式 push、二进制渲染、`scriptDomains`、hostContext 主题/时区、`ui/message`、`ui/download-file`、优雅 teardown 从"缺失/占位"补齐。

仍建议按性价比跟进：

1. **sampling 真实实现（产品/基础设施决策）**：让 `hostCapabilities` 声明 `sampling`，并把 `oncreatesamplingmessage` 接到宿主既有 provider 回话。当前语义一致（未虚报），但协议特性未兑现。
2. **hostContext 实时订阅**：接入宿主 `setHostContext`（如主题/容器尺寸变化时推送 `host-context-changed`），依赖引入现成 `useTheme` 类钩子。
3. **`ui/update-model-context` 落地**：把 App 提交的上下文并入下一轮模型请求。
4. **权限补全**：camera/mic/geolocation 在宿主授权策略就绪后透传 `allow-*`；`tool-cancelled` 运行中推送。
5. **E2E 实测**：在具备 Playwright 浏览器的环境中运行新增用例（当前因浏览器缺失未执行）。
6. **契约对齐**：逐步用新版 `@opencode-ai/client` 替代前端 workaround（双形状 / 204 / fetch-bind），把 relay 从补丁态收敛到规范对齐态。

> 附注：剩余"未实现/占位"均可基于已接入的 ext-apps `AppBridge` 增量补齐，无需重写基础设施。