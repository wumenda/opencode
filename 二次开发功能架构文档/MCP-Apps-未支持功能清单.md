# MCP Apps 未支持 / 占位功能清单

> 依据：对照 [MCP-Apps-概述.md](./MCP-Apps-概述.md) 与 ext-apps 规范（`2026-01-26`），以当前源码实态为准（详见 [MCP-Apps-支持度分析.md](./MCP-Apps-%E6%94%AF%E6%8C%81%E5%BA%A6%E5%88%86%E6%9E%90.md)）。
> 状态图例：🔴 未支持（App 请求会失败/无能力）；🟡 占位或半支持（有入口但无实义或强制 downgrade）；✅ 本轮已实现（[MCP-Apps-未实现功能-执行计划.md](./MCP-Apps-%E6%9C%AA%E5%AE%9E%E7%8E%B0%E5%8A%9F%E8%83%BD-%E6%89%A7%E8%A1%8C%E8%AE%A1%E5%88%92.md)）。

---

## 1. 未支持功能总览

| 功能 | 状态 | 现状（实现位置 / 行为） | 宿主集成边界 |
|---|---|---|---|
| **LLM 采样 `sampling/createMessage`** | ✅ 机制已实现 | `hostCapabilities` 现支持 `sampling`，`McpAppView` 提供可插拔 `onSampling` 并接通 AppBridge `oncreatesamplingmessage`；未提供 handler 时不声明（不虚报） | **真实 LLM 由宿主注入**：在 Provider/渲染处传 `onSampling`（限流/成本/用户同意由实现方负责） |
| **更新模型上下文 `ui/update-model-context`** | ✅ 机制已实现 | 新增宿主 store `session-ui/context/mcp-model-context.tsx`；`onupdatemodelcontext` 写 `modelCtx.set({ content, structuredContent })`（Provider 已包裹） | **合并进下一轮模型请求**由宿主读 `modelContextHost.latest()` 消费 |
| **敏感权限 camera / microphone / geolocation** | ✅ 已实现 | `buildAllow` 把资源声明的 `camera/microphone/geolocation/clipboard-write` 映射为 iframe `allow` 属性（`resource.ts` + `McpAppView`） | 无（按资源声明透传） |
| **hostContext 实时推送 `setHostContext` / `host-context-changed`** | ✅ 已实现 | `McpAppView` 订阅 `useTheme().mode()` + ResizeObserver 容器尺寸，变化时 `bridge.setHostContext` 推送（`host-context-utils.ts`） | 无 |
| **工具取消推送 `ui/notifications/tool-cancelled`** | ✅ 已实现 | `McpAppEvent` 增 `tool-cancelled`；error 状态保持 App 挂载并推 `reason`（`mcp-tool.tsx` + `mcp-app-view.tsx` forward 调 `sendToolCancelled`） | 无 |
| **显示模式切换 `ui/request-display-mode`** | ✅ 已实现 | `display-mode.ts` `resolveDisplayMode` 显式协商；当前仅 `inline`（不支持 fullscreen/pip 时回退 inline） | 如需 fullscreen/pip 布局，需扩展宿主布局体系并扩充 `SUPPORTED_DISPLAY_MODES` |

---

## 2. 次要 / 半支持项（本轮未变）

| 项 | 状态 | 说明 |
|---|---|---|
| hostContext 富字段（`styles` / `availableDisplayModes` / `toolInfo`） | 🟡 | 未填充；当前只提供 theme/timeZone/locale/尺寸/displayMode |
| `ui/message` 上屏 | 🟡 | 仅经宿主 toast 轻量呈现，未写入会话存储（文本来自 App 动态内容） |

---

## 3. 架构性差异（非缺口，按本实现设计）

| 项 | 说明 |
|---|---|
| **沙箱单 iframe + blob** | 本实现用 CSP 沙箱 blob 单 iframe；未采用规范里可选的"双 iframe sandbox-proxy"内部架构，故 `sandbox-proxy-ready` / `sandbox-resource-ready` 能力不适用（用 blob 直载）。 |
| **SDK/后端契约代差 workaround** | 前端为迁就当前后端 contract 保留了补丁（`mcp.list` 双形状、`mcp.connect` 原生 fetch、`fetch.bind`、relay `initialize` 省略 `undefined`）。属技术债，非协议功能缺失。 |

---

## 4. 剩余宿主集成 / 产品决策项

> 以下不再是"前端能力缺失"，而是需要宿主/后端在既有机制之上注入实现的点：

1. **sampling 真实 LLM**：供应商层接入（Provider 传入 `onSampling`，含限流/成本/用户同意）。
2. **update-model-context 并入模型上下文**：宿主在下一轮模型请求前读 `modelContextHost.latest()` 拼入上下文。
3. **fullscreen / pip 布局**：扩展宿主布局体系并扩充 `SUPPORTED_DISPLAY_MODES`。
4. **hostContext 富字段**（`styles` / `availableDisplayModes` / `toolInfo`）按需填充。

> 以上四项不阻塞常见演示 App；其余机制均已实现，无需重写基础设施。