# MCP Apps 协议支持度分析（Host / Web 端）· 更新版

> 分析对象：以 [MCP-Apps-概述.md](./MCP-Apps-%E6%A6%82%E8%BF%B0.md) 与 ext-apps 规范（`2026-01-26`，`@modelcontextprotocol/ext-apps@1.7.5`）为基准。
> "Host" 指 opencode 后端（`packages/opencode`，httpapi 的 `/api/mcp/:name/rpc` relay）；"Web" 指前端（`packages/app`，`McpAppView` / `AppBridge`；以及 `packages/session-ui` 的 `mcp-tool.tsx`）。
> 本版本为逐文件核对源码后的**当前实态**，取代早期基于印象的旧版结论——旧版标注的多项"未实现"（openLink、hostContext、blob/PDF 资源、资源 csp/permissions、sampling relay、teardown/message/updateModelContext、size-change）现已落地。

**结论先行：已覆盖"最小可用宿主"的全部核心链路，并补齐了多项宿主能力，但**仍未达到"完全支持协议所有特性"**。核心渲染 + AppBridge 双向桥接 + 核心工具/资源/提示代理 + 结果回放 + 进度 + 打开外链 + 自动尺寸，均已可用并可跑通演示 App；但以下能力仍缺失或仅占位：sampling 的宿主侧真实实现、`ui/download-file`、`ui/message` 仅打日志不上屏、`ui/update-model-context` 仅打日志不落地、运行中 `tool-input / tool-input-partial / tool-cancelled` 流式推送、teardown 资源级、hostContext 主题/时区/实时更新、camera/mic/geolocation 权限、外部脚本语言域、blob/PDF 的 iframe 渲染。**

---

## 1. 已覆盖的核心链路（逐文件核实，可用）

| 环节 | 实现位置 | 状态 |
|---|---|---|
| 工具声明 `metadata.mcp` + `ui.resourceUri` → 提取 App | `session-ui/src/components/mcp-tool.tsx`（`mcpAppFromPart`） | ✅ |
| 抓取 `ui://` 资源（`resources/read` 经 relay） | `app/src/lib/mcp-apps/resource.ts`（`readUiResource`） | ✅ |
| MIME 校验：`text/html` 与 `text/html;profile=mcp-app`（按 `;` 取 base） | `resource.ts` | ✅ |
| 二进制/blob 资源解析（`text` / `blob` / `application/pdf`） | `resource.ts` | ⚠️ 可读，**渲染**未实现（见 §3.2） |
| CSP 沙箱化 + blob URL | `resource.ts`（`injectCsp` / `buildSandboxedHtml`） | ✅ |
| **遵循资源 `_meta.ui.csp` 与 `_meta.ui.permissions`** | `McpAppView.start` → `buildSandboxedHtml(html.text, { csp, permissions })` | ✅（部分，见 §3.1） |
| iframe 渲染（`sandbox="allow-scripts"`，隔离 opaque origin） | `McpAppView` | ✅ |
| AppBridge 握手 `ui/initialize` + `notifications/initialized` | `McpAppView.onIframeLoad`（ext-apps `AppBridge`） | ✅ |
| **结果回放**（初始化后 H→A 推 `ui/notifications/tool-result`） | `next.oninitialized → sendToolResult(fallbackData)` | ✅ |
| **代理 tools / resources / prompts**（app→host→真实服务器） | `HttpRpcTransport` → 浏览器 `Client` → 后端 `rpcCall` | ✅ |
| **进度**：`metadata.mcpProgress` → UI 进度条 | 后端 `session/tools` + `mcp-tool.tsx`（`mcpProgressFromPart`） | ✅ |
| **打开外链** `ui/open-link` | `next.onopenlink → platform.openExternal(url)` | ✅ |
| **自动尺寸** `ui/notifications/size-changed` | `next.onsizechange → setAutoHeight` | ✅（inline 模式） |
| **hostContext**（locale / 尺寸 / displayMode） | `buildHostContext` + AppBridge `{ hostContext }` | ⚠️ 部分（见 §3.4） |
| Listening（工具运行期 host→app 日志） | `PostMessageTransport.send` 覆写，仅控 `ui/notifications/*` | ⚠️ 诊断用 |
| tool/message 占位 handler（日志，不落地） | `onmessage` / `onupdatemodelcontext` | ⚠️ 解析成功但无实义 |

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
| `ui/download-file` | ❌ | `downloadFile:false`（capability 未声明），无 handler |
| `ui/message` | ⚠️ | `onmessage` 已设，但仅 `console.log` 并返回 `{}`，不上屏到会话 |
| `ui/update-model-context` | ⚠️ | `onupdatemodelcontext` 已设，仅 `console.log` 返回 `{}`，不改变模型上下文 |
| `ui/request-display-mode` | ⚠️ | AppBridge 默认回 `mode:"inline"`，无实际布局切换 |
| `ui/resource-teardown` | ❌ | 未处理 |
| `ui/request-teardown` | ⚠️ | `onrequestteardown → bridge.close()`（关闭桥接，无资源级清理） |

### 2.2 A→H 通知

| 通知 | 现状 |
|---|---|
| `ui/notifications/initialized` | ✅ 触发结果回放 |
| `ui/notifications/size-changed` | ✅ `onsizechange` 驱动 iframe 自动高度 |
| `ui/notifications/sandbox-proxy-ready` | — 本实现用 blob，不相关 |
| `ui/notifications/tool-input` / `tool-input-partial` | ❌ 宿主不消费 |
| `ui/notifications/tool-result` | ✅ 由 App 上报时宿主订阅（但主路径是 H→A 回放） |
| `ui/notifications/tool-cancelled` | ❌ 宿主不消费 |
| `ui/notifications/host-context-changed` | — hostContext 静态，未走变更上报 |
| 普通 MCP `notifications/progress`（工具进度） | ✅ `metadata.mcpProgress` → UI 进度条 |

### 2.3 H→A 通知（宿主 push 到 App）

| 通知 | 现状 |
|---|---|
| `ui/notifications/tool-result` | ✅ 仅 App 初始化后回放**上次完成**的工具结果 |
| `ui/notifications/tool-input` / `tool-input-partial` | ❌ 运行中不流式推送（`pushToolInput` 已有实现但**未接入任何触发源**） |
| `ui/notifications/tool-cancelled` | ❌ |
| `ui/notifications/host-context-changed` | ❌（hostContext 仅初始化设置，无 `setHostContext`） |
| `ui/notifications/sandbox-resource-ready` | ❌（用 blob） |
| `notifications/tools \| resources \| prompts list_changed` | ✅ AppBridge 监听服务器变更并转发 |

---

## 3. 关键缺口细节（逐条说明，含部分实现的反证）

### 3.1 沙箱 CSP / 权限：**部分**遵循，非全量
`resource.ts` 的 `injectCsp` 现已把资源 `_meta.ui.csp` 的 `connectDomains / resourceDomains / frameDomains` 并入 CSP；`buildSandboxedHtml` 也据此在 iframe `sandbox` 上追加令牌。
但仍有硬限制：
- `script-src` **固定为** `'unsafe-inline' 'self' data:`，且 `SandboxOptions.csp` 类型**没有 `scriptDomains` 字段** → 官方 `https://.../ext-apps/client.js` 之类**外部脚本仍会被拦截**（`connect-src` 放行了但脚本不放行）。依赖外部 JS 的 App 仍不能工作。
- `permissions` 仅落实了 `clipboard-write`；**camera / microphone / geolocation 不授予**（源码注释明确：需宿主端授权策略，此处不静默放行）。
- 影响："查看富媒体（外部源）""实时监控（外部数据/外部脚本）"类 App 仍受限。

### 3.2 仅 text 真正渲染，二进制/blob 只"读取不渲染"
`readUiResource` 已能返回 `blob` 内容并接受 `application/pdf` MIME，但 `McpAppView.start` 里 `buildSandboxedHtml(html.text ?? "", ...)` **只用 `html.text`**——若资源是 blob-only（如 pdf-server、video-resource），`html.text` 为 `undefined`，会渲染成一个空 HTML 文档。**没有走 blob URL 直接当 iframe 源的路径**。

### 3.3 缺少"UI 预加载 / 工具输入流式 push"（核心商业模式缺口）
`McpAppView.pushToolInput` 方法存在且会幂等地发出 `ui/notifications/tool-input-partial`，但**调用点只有它自己，没有从后端运行中事件接进来**。宿主只在工具**完成后**、App 初始化后回放一次 `tool-result`。运行中的 `tool-input / tool-input-partial / tool-cancelled` 均不推送。`McpAppRenderer`（`session-ui/context/mcp-app.tsx`）也只接收 `{server, resourceUri, fallbackData}`，不接收运行期流。

### 3.4 hostContext 部分可用，缺主题/时区/实时
`buildHostContext`（`host-context.ts`）产出：`displayMode:"inline"`、`locale`、`containerDimensions`、`platform:"web"`、`deviceCapabilities`。但：
- `theme` 与 `timeZone` **未从宿主真实值传入**（调用处只传了 width/height/locale）。
- `setHostContext` / `ui/notifications/host-context-changed` 未使用 → App 无法感知宿主主题与布局切换（默认走 inline、无明暗主题）。

### 3.5 sampling：后端能 relay，前端不成能力
后端 `rpcCall` 已新增 `sampling/createMessage`（走 `client.request` + `CreateMessageResultSchema` 校验）。但前端 `hostCapabilities`（`bridge.ts`）**未声明 sampling**，`AppBridge` 也未接 `oncreatesamplingmessage` 到任何真实 LLM/provider。因此：
- capability 层面 App 不会认为宿主支持采样 → 不会发起请求；
- 即便直接 `client.request("sampling/createMessage")`，后端也只是把它 relay 到连接的 MCP 服务器，而采集响应仍需 App 侧处理，宿主无基于自身 provider 的采样回话。

### 3.6 `ui/message` / `ui/update-model-context` 占位
两者 handler 存在但不产生实义：`message` 仅打日志不上屏到会话；`update-model-context` 仅打日志不修改上下文。capability 中 `message:true` 已声明但 App 发送的内容无处落地。

### 3.7 teardown 仅请求级
`ui/request-teardown` 关闭 bridge；**`ui/resource-teardown`**（资源级、App 主动释放）未处理；关闭时也未做 iframe 资源回收（仅 revoke blob URL / close bridge）。

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
| 打开外链 `ui/open-link` | 🟢 高 | 可用 |
| 自动尺寸 `size-changed` | 🟢 中高 | inline 模式可用 |
| 资源 `csp` / `permissions` 遵循 | 🟡 中 | connect/frame/clipboard 可，外部脚本/camera·mic·geo 不行 |
| 二进制/blob 资源（读取） | 🟡 中 | 可读，**渲染**未实现 |
| hostContext（locale/尺寸） | 🟡 中 | 缺 theme/timeZone/实时更新 |
| sampling | 🔴/🟡 | 后端 relay 有；前端不成能力、无 LLM 实现 → 实为无 |
| `ui/download-file` | 🔴 无 | 未声明未实现 |
| `ui/message` / `ui/update-model-context` | 🟡 占位 | 解析成功、仅日志，不落地 |
| Teardown（request / resource） | 🟡 弱 | 仅 request 级关 bridge |
| 运行中流式 push（tool-input·partial·cancelled） | 🔴 无 | 仅完成后单次回放 |
| hostContext 主题/时区/实时 & 显示模式切换 | 🔴/🟡 | 静态 inline，缺主题 |
| 协议版本 / SDK 契约对齐 | 🟡 中 | `2026-01-26`；靠 workaround 支撑 |

---

## 5. 结论与建议

**是否"完全支持所有特性"：否，已'核心可用但未完整'。**
现状是一个**功能较全的最小宿主**：能渲染 HTML App、经 AppBridge 代理核心 MCP 工具/资源/提示、回放结果、显示进度、打开外链、随内容自适应高度，足以跑通 `ui-server`、`pfd_topology` 等演示 App，且相较旧版已新增 openLink/hostContext/blob 读取/csp-permissions/sampling-relay/teardown/size-change 等。

要覆盖规范"所有特性"，按性价比建议补齐：

1. **运行中流式 push（最高价值缺口）**：把后端工具运行期事件（`tool-input` / `tool-input-partial` / `tool-cancelled` / 结果）接入 `pushToolInput` 触发源，并让 `session-ui` 的 renderer 携带实时输入。这直接兑现概述强调的"UI 预加载 + 运行中数据流"。
2. **sampling 成为真实能力**：在 `hostCapabilities` 声明 sampling，并让 AppBridge 的 `oncreatesamplingmessage` 走宿主既有 provider 回话；或至少明确降级"不支持"以消除二义。
3. **沙箱补全**：给 `SandboxOptions` 增加 `scriptDomains` 并放入 `script-src`；权限（camera/mic/geolocation）在宿主授权策略就绪后透传 `allow-*`。
4. **二进制渲染**：`readUiResource` 返回 blob 时，`McpAppView` 走"blob URL 直接作为 iframe 源 + 相应 MIME"路径，让 pdf/video blob 资源真正可看。
5. **hostContext 完整化**：传入真实 `theme` / `timeZone`，并用 `setHostContext` 随宿主变化推送 `host-context-changed`。
6. **`ui/message` 上屏、`update-model-context` 落地、`resource-teardown`、`download-file`**：视产品需要再接 handler；未接前保持 capability 与实现一致，避免"声明了却无实义"。
7. **契约对齐**：逐步用新版 `@opencode-ai/client` 替代前端 workaround（双形状 / 204 / fetch-bind），把 relay 从补丁态收敛到规范对齐态。

> 附注：以上"未实现/占位"多可基于已接入的 ext-apps `AppBridge` 增量补齐，无需重写基础设施。