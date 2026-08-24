---
name: "mcp-ui-builder"
description: "为指定 MCP server 中的工具构建交互式 UI。执行后询问 MCP server 文件夹路径和需要构建 UI 的 tool 名，基于内置 ui 模板生成可运行 UI 代码。当用户要求为某个 MCP tool 开发/编写 MCP Apps UI 时调用。"
---

# MCP UI Builder（基于 ui 编写工具业务 UI）

基于 skill 内置的 `ui` 模板项目，为用户的 MCP 工具编写可在宿主(Claude Desktop 等)中渲染的交互式 UI。目标用户是**不懂 MCP Apps 协议的业务同事**，本 skill 负责把"工具的输入/输出/流程"翻译成可运行的 UI 代码。

**skill 内置资源**（路径均相对于本 skill 目录）：
- 三个模板项目（按页面复杂度选其一）：
  - `mcp-apps-ui/simple-ui/`   — `SimpleResultPage`（无进度，同步返回）
  - `mcp-apps-ui/progress-ui/` — `ProgressPage`（进度推送 + 结果）
  - `mcp-apps-ui/review-ui/`   — `ReviewPage`（进度 + 人工审核 + 提交）
- 每个模板项目内含：`ui/`（前端，单工具单项目，`App.tsx` 直接渲染该工具的页面，**无工具名路由**）+ `host/`（测试控制台）
- 完整文档：`mcp-apps-ui/<模板>/ui/README.md`（遇到疑问先查它）
- 服务端示例：`server_example/server.py`（演示三个工具各绑定一个独立 `ui://` 资源）

> 下文用 `<skill_dir>` 代指本 skill 所在目录，`<server_folder>` 代指用户提供的 MCP server 文件夹路径，`<ui_project_name>` 代指复制时根据 tool 含义重命名的项目目录名（如 tool 名为 `extract_report` 则可命名为 `extract-report-ui`），`<template>` 代指 `simple-ui` / `progress-ui` / `review-ui` 三选一。

---

## 一、开始前：收集信息 + 准备项目

### Step 0: 向用户收集 MCP server 文件夹

使用 `AskUserQuestion` 询问用户的 MCP server 代码所在的文件夹路径。

### Step 1: 定位需要构建 UI 的 tool

在 `<server_folder>` 中搜索工具注册（FastMCP `@mcp.tool()`、`@app.tool()` 等），列出找到的工具名称。然后使用 `AskUserQuestion` 让用户选择需要构建 UI 的 tool：

- 若搜到工具：将工具名作为选项供用户选择
- 若没搜到工具：直接询问用户 tool 名称

### Step 2: 深入理解工具执行逻辑

按工具名在 `<server_folder>` 中定位其**完整实现**（如 `Grep`/`SearchCodebase` 搜工具名），**通读工具函数体**，梳理以下要素：

- **参数 schema（inputSchema）**：工具接受的参数及类型
- **返回结构（structuredContent）**：工具返回的数据结构
- **执行阶段**：工具有哪些执行步骤？每步做什么？是否有先后依赖？
- **进度推送**：工具是否调用 `ctx.report_progress()` / `send_progress`？`send_progress_with_data`等notification，在哪些节点推送？progress/total/message 各是什么？是否携带 `uiEvent` 扩展字段？
- **中间数据**：执行过程中产生哪些中间数据？哪些需要展示给用户？
- **错误处理**：哪些环节可能失败？异常如何传递（抛异常 vs 返回 error 字段）？
- **条件分支**：是否有根据输入走不同路径的逻辑？不同路径的 UI 表现是否不同？
- **反向调用**：工具是否依赖 UI 反向调用其它工具（如 `submit_review`）？

**这是 UI 设计的依据，不是可选项。** 不要只看 schema 就动手写 UI——工具的执行逻辑决定了页面类型、进度粒度、数据展示方式和 mock 数据结构。

若代码中找不到该工具（可能是外部服务/尚未接入），向用户索要上述信息后再继续。**不要凭空猜测工具行为。**

### Step 3: 确认工作流类型

基于 Step 2 的执行逻辑分析，使用 `AskUserQuestion` 给出三个选项让用户确认（决定复制哪个模板项目）：

| 工具执行特征 | 选页面 | 复制的模板项目 |
|---|---|---|
| 无 progress 推送，同步返回结果 | SimpleResultPage | `mcp-apps-ui/simple-ui/` |
| 有 progress 推送，需展示执行进度 | ProgressPage | `mcp-apps-ui/progress-ui/` |
| 有 progress 推送 + review_pending 阻塞 + 反向调用提交 | ReviewPage | `mcp-apps-ui/review-ui/` |

> **判断依据是代码，不是直觉。** 检查工具函数体：有 `ctx.report_progress()` 选 ProgressPage；有 `review_pending`/`asyncio.Event` 阻塞选 ReviewPage；都没有选 SimpleResultPage。

> **使用模型：一个工具 = 一个独立项目 = 一个 `ui://` 资源。** 宿主执行一个工具时创建 iframe 展示该工具的 view，所以每个工具用独立的 ui 项目，项目内 `App.tsx` 直接渲染该工具的页面（无工具名路由），服务端为该工具绑定一个独立的 `ui://` 资源。多个工具共用一个项目，仅当它们连续执行且内容需整合在同一页面时。

### Step 4: 复制对应模板到用户 server 目录（重命名）

根据 tool 含义确定项目目录名 `<ui_project_name>`（如 tool 名为 `extract_report` 则可命名为 `extract-report-ui`），将 Step 3 选中的 `<skill_dir>/mcp-apps-ui/<template>/` 中的 `ui/` 和 `host/` 复制到 `<server_folder>/<ui_project_name>/`（排除 `node_modules/`、`dist/`、`tsconfig.tsbuildinfo`、`__tests__/`）。

```bash
# Windows PowerShell（<template> 替换为 simple-ui / progress-ui / review-ui）
robocopy "<skill_dir>\mcp-apps-ui\<template>\ui" "<server_folder>\<ui_project_name>\ui" /E /XD node_modules dist __tests__ /XF tsconfig.tsbuildinfo
robocopy "<skill_dir>\mcp-apps-ui\<template>\host" "<server_folder>\<ui_project_name>\host" /E /XD node_modules dist /XF tsconfig.tsbuildinfo

# 安装依赖
cd <server_folder>/<ui_project_name>/ui && npm install
cd <server_folder>/<ui_project_name>/host && npm install
```

> 后续所有修改都在复制后的 `<server_folder>/<ui_project_name>/` 中进行，**不要直接修改 skill 目录下的模板**。

---

## 二、实施步骤

> 以下 `src/...` 路径均相对于 `<server_folder>/<ui_project_name>/ui/`，`host/src/...` 相对于 `<server_folder>/<ui_project_name>/host/`。

### Step 1: 梳理执行逻辑 -> UI 映射

动手写代码前，先把第一节 Step 2 分析到的工具执行逻辑映射到 UI 元素。**UI 必须契合工具的实际执行流程，不能脱离代码臆造页面。**

| 工具执行逻辑 | UI 对应 |
|---|---|
| 执行阶段 A -> B -> C | ProgressPage 的 progress steps，每步 message 对应阶段描述 |
| progress 携带 `uiEvent` 扩展 | UI 中通过 `useMcpApp().progressEvents` 读取并展示中间数据 |
| 返回 `structuredContent` | 结果展示区的字段、布局、交互 |
| 异常/错误 | `ErrorBanner` 展示错误信息，区分可重试 vs 不可重试 |
| `review_pending` 阻塞 | ReviewPage 审核界面 + `submit_review` 反向调用 |
| 条件分支（输入不同走不同路径） | 不同路径的条件渲染，确保所有路径都有对应 UI |
| 中间产物（文件、图片等） | 对应展示组件（`TaskWithImage` / 下载链接等） |

**输出一份简要映射清单**：进度步骤数 + 每步 message/中间数据、结果展示字段、错误处理方式、是否需反向调用。这份清单同时指导 Step 4 的 mock 数据编写。

### Step 2: 创建业务页面（基于复制的模板）

复制来的模板 `src/pages/` 下已经有对应复杂度的页面文件（`SimpleResultPage.tsx` / `ProgressPage.tsx` / `ReviewPage.tsx`）。

1. 把示例页面文件改名为 `YourPage.tsx`（或直接在原文件上改）
2. 替换页面顶部注释里的示例说明
3. 把示例结果类型（`SimpleResult` / `ProgressResult` / `ReviewResult`）改成你的工具返回结构：
   ```typescript
   interface YourResult {
     // 改成你的工具 structuredContent 字段
     items?: Array<{ id?: string; name?: string; value?: string }>;
     warnings?: string[];
   }
   ```
4. **按 Step 1 的映射清单替换渲染逻辑**：用你的字段展示数据，进度阶段对齐工具实际执行步骤，中间数据在对应阶段展示（可复用组件见"关键 API 速查"）。

**各模板用到的 hooks 对照（别抄错）**：

| 模板 | 核心 hooks |
|---|---|
| SimpleResultPage | `useMcpApp` + `useNormalizedToolResult` |
| ProgressPage | 同上 + `TaskProgress` 组件 |
| ReviewPage | `useReviewStatus` + `useReviewResult` + `useEditedData` + `useDirtyGuard` + `submitReview` + `ReviewToolbar`/`TaskWithImage`/`JsonDrawer` |

### Step 3: 改 App.tsx 指向你的页面

模板的 `src/App.tsx` 已经直接渲染该模板对应的页面（无工具名路由）。改名后只需更新 import：

```typescript
// 模板默认（以 simple-ui 为例）：
import { SimpleResultPage } from '@/pages/SimpleResultPage';

// 改成你的页面名：
import { YourPage } from '@/pages/YourPage';

export default function App() {
  // ...
  return (
    <ErrorBoundary>
      <div className="h-full animate-fade-in">
        <YourPage />   {/* 改成你的页面 */}
      </div>
    </ErrorBoundary>
  );
}
```

> **无 `PAGES` / `resolveToolName` / `window.__MCP_TOOL_NAME__`。** 单工具单项目，UI 直接渲染该工具的页面，工具名不再参与 UI 路由。宿主通过 `ui/notifications/tool-input` 通知的 `toolName` 仅用于日志展示，不影响页面选择。

### Step 4: 更新 mock 数据（镜像工具真实执行流程）

编辑 `host/src/mockData.ts`，按 `ToolGroup` 结构添加你的工具场景，**删掉与本工具无关的演示场景**（一个工具一个项目，host 只测你自己的工具）。

**mock 数据必须镜像工具的真实执行流程**--steps 的数量、progress/total/message 对齐代码中的 `ctx.report_progress()` 调用，uiEvent 字段对齐工具实际推送的扩展数据，结果结构对齐 `structuredContent`：

```typescript
export const MOCK_TOOLS: ToolGroup[] = [
  {
    name: 'your_tool_name',
    label: '你的工具',
    page: 'YourPage',
    scenarios: [
      {
        id: 'your-normal',
        label: '正常:执行 + 返回',
        toolName: 'your_tool_name',
        args: { input_path: 'example://data' },
        // steps 对齐工具函数中实际 report_progress 的调用次数和顺序
        steps: [
          { progress: 0, total: 2, message: '启动工具' },
          { progress: 1, total: 2, message: '处理完成', uiEvent: { event_type: 'parsed', item_count: 3 } },
        ],
        review: { reviewId: 'review-001', finalResult: <你的结果>, result: <你的结果> },
        skipReview: true, // 不需要审核就设 true；需要审核就不设（进入 review_pending）
      },
    ],
  },
];
```

> 若工具有条件分支，应为每个分支创建一个 scenario（正常/异常/边界），确保所有执行路径都在 mock 中覆盖。

### Step 5: 反向调用工具（如有）

若 UI 需要反向调用其它 MCP 工具（如 `submit_review`、`read_image`），必须**同步**在 `host/src/hostProtocol.ts` 的 `handleToolCall` 加 mock 分支，否则返回"未实现工具 xxx"：

```typescript
case 'your_call_tool': {
  this.respond(id, { structuredContent: { /* mock 返回 */ }, content: [] });
  break;
}
```

### Step 6: 服务端注册该工具的 UI 资源

在用户的 MCP server 中，为该工具注册一个独立的 `ui://` 资源（一个工具一个资源），并让工具通过 `AppConfig(resource_uri=...)` 绑定该资源：

```python
@mcp.resource("ui://mcp-app-ui/your_tool/index.html")
def get_your_tool_ui_html() -> str:
    """返回 your_tool 的 UI HTML（your_tool_ui 项目的构建产物）。"""
    with open("<path/to/your_tool_ui>/dist/index.html", "r", encoding="utf-8") as f:
        return f.read()

@mcp.tool(app=AppConfig(resource_uri="ui://mcp-app-ui/your_tool/index.html"))
async def your_tool(ctx: Context, ...): ...
```

参考 `server_example/server.py` 的三个工具实现（simple/progress/review 各绑定一个 `ui://` 资源）。

### Step 7: 验证

```bash
cd <server_folder>/<ui_project_name>/ui
npm run build        # 必须！host 加载的是 dist/index.html 构建产物，不 build 改动不生效
cd ../host
npm run dev          # 打开 http://localhost:5184
```

在控制台选择你的工具 -> 点击"自动播放"，确认完整流程无报错、无白屏。

**验证时对照工具代码检查**：进度步骤数是否与 `report_progress` 调用一致？中间数据展示是否对应 `uiEvent`？结果字段是否与 `structuredContent` 匹配？服务端 `resource_uri` 是否与 `@mcp.resource` 路径一致？

---

## 三、关键 API 速查（改页面时最常用）

**core 层** `@/core/mcpApp`：

| API | 用途 |
|---|---|
| `useMcpApp()` | 订阅全局状态(status/toolInput/toolResult/progress/progressEvents/error/callToolLoading) |
| `useToolInput()` | 工具入参(toolName + args) |
| `useNormalizedToolResult()` | 归一化结果(toolResult 优先) |
| `useCallToolLoading()` | 反向调用进行中 |
| `useMcpInitialize()` | 握手(放 App 根组件，别动) |
| `mcpApp.callTool(name, args)` | 反向调用工具 |
| `mcpApp.cancelCurrentTool()` | 请求取消当前工具 |

**业务模式层**：审核走 `@/patterns/review`（`useReviewStatus` / `useReviewId` / `useReviewResult` / `submitReview`），图片走 `@/patterns/image`（`useToolImage` / `useSourceImage`）。**业务专属逻辑放 `patterns/<领域>/`，不要塞 core。**

**通用组件**：`Layout` / `PageHeader` / `ProgressBanner` / `TaskProgress` / `TaskWithImage` / `ReviewToolbar` / `ErrorBanner` / `ErrorBoundary`（防白屏，别删）/ `Toast` / `JsonDrawer` / `JsonViewer` / `common/SectionCard` / `common/InfoCell`。

---

## 四、后端契约（ReviewPage 必读，别忘告诉用户）

审核流程依赖后端通过 progress 通知推送**非标准扩展字段 `uiEvent`**（标准 progress 只有 progress/total/message，不足以支撑审核）：

```
review 工具执行中 -> 推送 progress.uiEvent = {
  review_pending: true,   # 进入审核阻塞态(必需)
  review_id: "...",       # 审核会话 id，提交时回传(必需)
  final_result: {...},    # 审核编辑器展示的结果(必需)
  tool_name: "xxx"        # 可选
}
```

硬性约定：
1. 后端必须推 `uiEvent.review_pending`，否则 UI 卡在"执行中"
2. 用户提交后 UI 反向调用 `submit_review` 工具(参数含 review_id/approved/edited_data/reason)，服务端唤醒阻塞工具并回发 tool-result
3. **每个新会话必须重推新的 `review_id`**（core 收到新 tool-input 会清空旧 uiEvent）

---

## 五、常见坑（照 README"常见坑"章节排查）

1. 改 UI 不生效 -> 先 `npm run build` 再刷新控制台
2. 审核卡在"执行中" -> 后端没推 `uiEvent.review_pending`
3. `useEditedData(initial)` -> initial 建议 `useMemo` 保持引用稳定（已内置深比较防死循环，但稳定引用省性能）
4. 页面显示空白或错页面 -> `src/App.tsx` 的 import 指向了已删除的页面文件；检查 import 是否指向当前 `pages/` 下实际存在的文件
5. 反向调用报"未实现工具 xxx" -> 在 `host/src/hostProtocol.ts` 加 mock 分支
6. `structuredContent` 是可选字段 -> 渲染前必须判空
7. UI 与工具实际逻辑脱节 -> 没有通读工具函数体就写 UI，导致进度步骤/中间数据/结果展示与工具实际行为不一致。**必须先完成第二节 Step 1 的执行逻辑映射再写代码。**
8. 服务端 resource_uri 不匹配 -> 工具的 `AppConfig(resource_uri=...)` 必须与对应的 `@mcp.resource("ui://...")` 完全一致，且指向该工具对应的 ui 项目构建产物

---

## 六、完成标准（全部满足才算完成）

- [ ] 页面文件已创建，类型/渲染替换为你的业务
- [ ] 已通读工具函数体，UI 进度步骤/中间数据/结果展示与工具实际执行逻辑一致
- [ ] `src/App.tsx` 的 import 已指向你的页面（无 `PAGES` / `resolveToolName`）
- [ ] mock 数据已改成你的工具场景（只保留你的工具），host 控制台"自动播放"流程完整（进度->结果/审核->提交->完成）
- [ ] 后端为该工具注册了独立的 `ui://` 资源，`resource_uri` 与 `@mcp.resource` 路径一致，资源函数返回该工具对应 ui 项目的 `dist/index.html`
- [ ] 后端 uiEvent 契约已同步给用户（ReviewPage 必需）
- [ ] `npm run build` 通过
- [ ] 控制台无报错、无白屏
