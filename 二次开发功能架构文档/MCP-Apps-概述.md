# MCP Apps

> 交互式 UI 应用，可在 Claude Desktop 等 MCP 宿主中渲染。

完整的 API 文档、高级模式和完整规范请访问[官方 MCP Apps 文档](https://apps.extensions.modelcontextprotocol.io/)。

文本回复的能力有限。有时用户需要与数据交互，而不仅仅是阅读。MCP Apps 允许服务器返回交互式 HTML 界面（数据可视化、表单、仪表板），直接在聊天中渲染。

---

## 为什么不直接构建 Web 应用？

你可以构建一个独立的 Web 应用并发送链接给用户。但 MCP Apps 提供了独立页面无法比拟的关键优势：

- **上下文保持**：应用存在于对话内部。用户无需切换标签页、不会丢失位置，也不会困惑哪个聊天线程有那个仪表板。UI 就在那里，紧挨着引发它的讨论。

- **双向数据流**：你的应用可以调用 MCP 服务器上的任何工具，宿主也可以将最新结果推送到你的应用。独立的 Web 应用需要自己的 API、认证和状态管理，而 MCP Apps 通过现有的 MCP 模式即可实现。

- **与宿主能力集成**：应用可以将操作委托给宿主，宿主随后可以调用用户已连接的能力和工具（需经用户同意）。应用无需直接实现和维护每个集成（如邮件提供商），而是请求一个结果（如"安排这个会议"），由宿主通过用户现有的已连接能力来路由。

- **安全保障**：MCP Apps 在宿主控制的沙盒 iframe 中运行。它们无法访问父页面、窃取 cookie 或逃逸出容器。这意味着宿主可以安全地渲染第三方应用，而无需完全信任服务器作者。

如果你的用例不能从这些特性中受益，普通的 Web 应用可能更简单。但如果你希望与基于 LLM 的对话紧密集成，MCP Apps 是更好的工具。

---

## MCP Apps 的工作原理

传统的 MCP 工具返回文本、图像、资源或结构化数据，由宿主作为对话的一部分显示。MCP Apps 扩展了这一模式，允许工具在其描述中声明对交互式 UI 的引用，由宿主原地渲染。

核心模式结合了两个 MCP 原语：一个在描述中声明 UI 资源的工具，加上一个将数据渲染为交互式 HTML 界面的 UI 资源。

当 LLM 决定调用支持 MCP Apps 的工具时，流程如下：

1. **UI 预加载**：工具描述中包含 `_meta.ui.resourceUri` 字段，指向 `ui://` 资源。宿主可以在工具被调用之前就预加载该资源，从而实现将流式工具输入传送到应用等功能。

2. **资源获取**：宿主从服务器获取 UI 资源。该资源包含一个 HTML 页面，通常为了简便会将 JavaScript 和 CSS 打包在一起。应用也可以从 `_meta.ui.csp` 指定的来源加载外部脚本和资源。

3. **沙盒渲染**：Web 宿主通常将 HTML 渲染在对话中的沙盒 [iframe](https://developer.mozilla.org/zh-CN/docs/Web/HTML/Element/iframe) 内。沙盒限制应用对父页面的访问，确保安全。资源的 `_meta.ui` 对象可以包含 `permissions` 以请求额外能力（如麦克风、摄像头），以及 `csp` 以控制应用可以从哪些外部来源加载资源。

4. **双向通信**：应用与宿主通过 JSON-RPC 协议通信，该协议构成 MCP 的一个方言。部分请求和通知与核心 MCP 协议共享（如 `tools/call`），部分相似（如 `ui/initialize`），大部分是带有 `ui/` 方法名前缀的新方法。应用可以请求工具调用、发送消息、更新模型上下文，以及接收来自宿主的数据。

### 交互流程

```
MCP Server  <-->  MCP App iframe  <-->  Agent  <-->  User
```

- 在聊天中渲染交互式应用
- 应用随新数据更新
- 用户："显示分析数据"
- `tools/call` → 工具输入/结果 → 工具结果推送到应用
- 用户交互 → `tools/call` 请求 → `tools/call`（转发）→ 新数据 → 上下文更新

应用与宿主保持隔离，但仍然可以通过安全的 postMessage 通道调用 MCP 工具。

---

## 何时使用 MCP Apps

以下场景适合使用 MCP Apps：

**探索复杂数据。** 用户问"按地区显示销售额"。文本回复可能只是列出数字，但 MCP App 可以渲染一个交互式地图，用户点击区域下钻，悬停查看详情，切换指标——所有这些都不需要额外的提示。

**多选项配置。** 设置部署涉及数十个相互依赖的选择。与其来回对话（"哪个区域？""什么实例规格？""启用自动伸缩？"），MCP App 呈现一个表单，用户一次看到所有选项，带有验证和默认值。

**查看富媒体。** 当用户要求查看 PDF、查看 3D 模型或预览生成的图像时，文本描述力不从心。MCP App 将实际的查看器（平移、缩放、旋转）直接嵌入对话中。

**实时监控。** 显示实时指标、日志或系统状态的仪表板需要持续更新。MCP App 维持持久连接，随着数据变化更新显示，而不需要用户反复问"现在状态如何？"

**多步骤工作流。** 审批费用报告、审查代码变更或分类问题涉及逐项检查。MCP App 提供导航控件、操作按钮和跨交互持久的状态。

---

## 安全模型

MCP Apps 在沙盒 [iframe](https://developer.mozilla.org/zh-CN/docs/Web/HTML/Element/iframe) 中运行，提供与宿主应用程序的强隔离。沙盒阻止你的应用：

- 访问父窗口的 [DOM](https://developer.mozilla.org/zh-CN/docs/Web/API/Document_Object_Model)
- 读取宿主的 cookie 或本地存储
- 导航父页面
- 在父上下文中执行脚本

应用与宿主之间的所有通信都通过 [postMessage API](https://developer.mozilla.org/zh-CN/docs/Web/API/Window/postMessage) 进行。宿主控制你的应用可以访问哪些能力。例如，宿主可能限制应用可以调用哪些工具，或禁用 `sendOpenLink` 能力。

沙盒旨在防止应用逃逸以访问宿主或用户数据。

---

## 框架支持

MCP Apps 使用自己的 MCP 方言，像核心协议一样基于 JSON-RPC 构建。一些消息与常规 MCP 共享（如 `tools/call`），而其他则是应用专有的（如 `ui/initialize`）。传输方式是 [postMessage](https://developer.mozilla.org/zh-CN/docs/Web/API/Window/postMessage)，而不是 stdio 或 HTTP。由于这些都是标准的 Web 原语，你可以使用任何框架，也可以不使用框架。

`@modelcontextprotocol/ext-apps` 中的 `App` 类是一个便捷封装，不是必需的。如果你希望避免依赖或需要更精细的控制，可以直接实现 [postMessage 协议](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx)。

[示例目录](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples)包含 React、Vue、Svelte、Preact、Solid 和原生 JavaScript 的入门模板。这些展示了每个框架系统的推荐模式，但它们是示例而非要求。你可以选择最适合你用例的方案。

---

## 客户端支持

MCP Apps 是[核心 MCP 规范](https://modelcontextprotocol.io/specification/latest)的扩展。宿主支持因客户端而异。

目前支持 MCP Apps 的客户端包括：

| 客户端 | 链接 |
|--------|------|
| Claude | https://claude.ai/ |
| Claude Desktop | https://claude.ai/download |
| VS Code GitHub Copilot | https://code.visualstudio.com/ |
| Microsoft 365 Copilot | https://www.microsoft.com/microsoft-365-copilot |
| Goose | https://block.github.io/goose/ |
| Postman | https://postman.com/ |
| MCPJam | https://www.mcpjam.com/ |
| Archestra.AI | https://www.archestra.ai/ |

完整的扩展支持列表请参见[客户端矩阵](https://modelcontextprotocol.io/extensions/client-matrix)。

### 为 MCP 客户端添加 MCP Apps 支持

如果你正在构建 MCP 客户端并希望支持 MCP Apps，有两个选项：

1. **使用框架**：[`@mcp-ui/client`](https://github.com/MCP-UI-Org/mcp-ui) 包提供 React 组件，用于在宿主应用中渲染和交互 MCP Apps 视图。用法详见 [MCP-UI 文档](https://mcpui.dev/)。

2. **基于 AppBridge 构建**：SDK 包含 [App Bridge](https://apps.extensions.modelcontextprotocol.io/api/modules/app-bridge.html) 模块，处理在沙盒 iframe 中渲染应用、消息传递、工具调用代理和安全策略执行。[basic-host 示例](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/basic-host)展示了如何集成。

实现详情请参见 [API 文档](https://apps.extensions.modelcontextprotocol.io/api/)。

---

## 示例

[ext-apps 仓库](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples)包含可直接运行的示例，展示不同用例：

### 3D 与可视化
- [map-server](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/map-server) — CesiumJS 地球仪
- [threejs-server](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/threejs-server) — Three.js 场景
- [shadertoy-server](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/shadertoy-server) — 着色器效果

### 数据探索
- [cohort-heatmap-server](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/cohort-heatmap-server)
- [customer-segmentation-server](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/customer-segmentation-server)
- [wiki-explorer-server](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/wiki-explorer-server)

### 商业应用
- [scenario-modeler-server](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/scenario-modeler-server)
- [budget-allocator-server](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/budget-allocator-server)

### 媒体
- [pdf-server](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/pdf-server)
- [video-resource-server](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/video-resource-server)
- [sheet-music-server](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/sheet-music-server)
- [say-server](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/say-server) — 文字转语音

### 工具
- [qr-server](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/qr-server)
- [system-monitor-server](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/system-monitor-server)
- [transcript-server](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/transcript-server) — 语音转文字

### 入门模板
- [React](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/basic-server-react)
- [Vue](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/basic-server-vue)
- [Svelte](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/basic-server-svelte)
- [Preact](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/basic-server-preact)
- [Solid](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/basic-server-solid)
- [原生 JavaScript](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/basic-server-vanillajs)

---

## 下一步

要开始构建你自己的 MCP App，请参阅[构建指南](https://modelcontextprotocol.io/extensions/apps/build)。
