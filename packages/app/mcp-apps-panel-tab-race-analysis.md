# MCP Apps 面板 Tab 闪回 + iframe 卡"等待任务" 深入分析

> 现象：顺序执行 3 个带 `ui://` 的 MCP 工具后，右侧"应用程序"面板里所有 iframe 都停在启动加载态（"等待任务/加载中"）；执行第 3 个工具时，tab 先跳到第 3 个工具，随即"闪回"到第 1 个工具的 iframe。
>
> 结论：这不是单点 bug，而是**面板焦点逻辑**与 **McpAppView iframe 生命周期**两条链路上的多个缺陷叠加。核心是：面板把"最新执行的工具"当成了稳定事实，但事件侧（part 流式更新、skill 游标）是渐进到达的；McpAppView 则依赖一个**跨 tab 复用的单实例 + 未完全加代际保护**的异步 `start()/onIframeLoad()`。

---

## 1. 链路总览

```
MCP server (pdf2json:8000)
   │  notifications/progress (携带 uiEvent / final_result / review_id)
   ▼
opencode 后端 → part.state.metadata.mcp / mcpProgress
   ▼
McpTool (session-ui/components/mcp-tool.tsx)
   │  createEffect 按 appKey push：tool-input-partial / tool-progress / tool-result / tool-cancelled
   ▼
McpAppHost 注册表 (session-ui/context/mcp-app-host.tsx)
   │  key = "sessionID:server/resourceUri:instanceID"
   │  有 sink → 广播；无 sink → 进 pending 缓冲；tool-progress 额外记 lastProgress
   ▼
McpAppView (app/components/mcp-app-view.tsx)  ← 同时有 2 类实例：
   │  ① 对话流内联（McpTool renderApp，timeline）
   │  ② 右侧面板 tab（McpAppsPanel，懒挂载只渲染激活项）
   ▼
AppBridge → iframe postMessage → React 审核 UI（mcpApp.ts 单例）
```

- 面板分组：`useMcpApps` 按 `skill` part 的游标 `currentSkill` 给每个 MCP 工具打上归属 skill，`buildSkillAppGroups` 以 `skill::instanceID` 去重生成两级 tab。
- 面板焦点：`McpAppsPanel` 内两个 `createEffect` 协作——① 组变化时兜底选第一个；② `latestExecuted.partID` 变化时跳到最新工具。
- iframe 渲染：`McpAppsPanel` 只渲染激活项，且 **McpAppView 组件实例在 tab 间复用**（`resourceUri` 变化时由内部 effect 触发 `start()` 重载）。

---

## 2. 问题一：tab 先跳第 3 个工具、又闪回第 1 个 iframe

### 2.1 相关代码

`packages/app/src/pages/session/v2/mcp-apps-panel.tsx`

```ts
// Effect ① 组变化时兜底选第一个 skill / tool
createEffect(() => {
  const list = groups()
  if (list.length === 0) { ...复位... return }
  const activeSkill = state.activeSkill()
  const exists = activeSkill !== undefined && list.some((g) => g.name === activeSkill)
  if (!exists) {
    const first = list[0]
    state.setActiveSkill(first.name)
    state.setActiveTool(first.apps[0] ? toolTabId(first.apps[0]) : undefined) // ← 会强制切到第 1 个
  }
})

// Effect ② 最新执行工具 → 跳 tab
createEffect(() => {
  const latest = props.latestExecuted()
  if (!latest) return
  if (latest.partID === lastExecutedPartID) return   // ← 同一 partID 后续更新不再处理
  lastExecutedPartID = latest.partID
  state.setActiveSkill(latest.app.skill)
  state.setActiveTool(toolTabId(latest.app))
})

// 激活工具（渲染内容）——存在静默兜底：
const activeTool = createMemo(() => {
  const group = activeGroup()
  if (!group) return undefined
  return group.apps.find((app) => toolTabId(app) === state.activeTool()) ?? group.apps[0]  // ← 找不到就回退第 1 个
})
```

`useMcpApps` 里 `latestExecuted` 与 `groups` 虽然同源（同一 memo），但两者都随 **part 流式更新**反复重算：part 的 status / metadata / skill 游标是渐进到达的，同一 `partID` 的标签可能中途改变（skill part 由 pending→running、或工具首次出现时 skill 游标仍是旧值）。

### 2.2 触发机制（两条路径都依赖"焦点状态与 groups 失配"）

**路径 A：`latest.app.skill` 与现有分组不一致 → Effect ① 二次执行把焦点拉回第 1 个**

- 前提：前 2 个工具在某 skill 组（如 `step-12`）内，第 3 个工具是**直连调用**（无 skill）或归属另一个新 skill 组。
- Effect ② 执行：`setActiveSkill(undefined)`（或新 skill）→ activeSkill 发生变化 → 触发 Effect ① 重跑。
- Effect ① 重跑：`activeSkill` 不在分组名集合内（直连组是 `undefined`，或被 Effect ② 设成一个尚不存在的组名）→ 命中 `if (!exists)` → `setActiveTool(first.apps[0])` → **tab 内容闪回第 1 个工具的 iframe**。

**路径 B：同 partID 被重新打标 → `activeTool` memo 的 `?? group.apps[0]` 静默兜底**

- 前提：第 3 个工具先以旧 skill 标签出现（skill part 还没切到 running），`groups` 形如 `[{step-12:[t1,t2,t3]}]`，Effect ② 把焦点设到 tab3。
- 随后 skill part 更新 → 第 3 个工具被改标到新组 → `groups` 变成 `[{step-12:[t1,t2]}, {newSkill:[t3]}]`。
- Effect ② 因 `partID` 未变**不再执行**（`lastExecutedPartID === p3`），activeSkill / activeTool 停留在旧值。
- `activeTool` memo：`activeGroup`（step-12）里找不到 tab3 → **回退 `group.apps[0]` = t1** → 内容渲染第 1 个工具，而 `state.activeTool` 仍是 tab3。

两条路径的共同根因：**面板把"焦点跟随最新执行"建立在"latest 的 skill 分组稳定且始终存在于 groups"这一隐含假设上，但 skill 标签由 `currentSkill` 游标 + 流式 part 更新决定，是渐进变化的；失配时没有任何兜底/纠偏，反而被 `?? group.apps[0]` 和 Effect ① 的 `first.apps[0]` 放大成"回到第一个"。**

> 单 skill 分组下不触发（activeSkill 一致、无重标），现有 E2E（`mcp-apps-panel.spec.ts`）全部是单 skill + 一次性下发完整 part，所以未覆盖到。

---

## 3. 问题二：三个 iframe 全部停在"等待任务"

App（React 审核 UI）在 iframe 内的数据来源只有一个：McpAppView 转发的三类事件（`ui/notifications/tool-input-partial`、`notifications/progress`、`ui/notifications/tool-result`）。全部卡在启动加载，说明 **这些事件没有到达 iframe**。三层原因叠加：

### 3.1 根因 A：`McpAppView.start()` 与 `onIframeLoad()` 的代际保护不对称（竞态丢事件）

`packages/app/src/components/mcp-app-view.tsx`

- `start()` 用 `startGeneration` 令牌保护了 `client` / `blobUrl` 的写入，防止旧 tab 的加载结果覆盖新 tab。
- 但 **`onIframeLoad()` / `oninitialized` / `bridge` / `appTransport` 的赋值完全没有代际保护**：

```ts
async function onIframeLoad(iframe) {
  ...
  await next.connect(transport)
  bridge = next                       // ← 旧 tab 的 bridge 可能在这里覆盖新 tab 的 bridge
  if (appInitialized) drainPending()
}
```

- 快速切换（第 3 个工具 tab → 闪回第 1 个工具 tab）时，第 3 个工具的 `onIframeLoad` 可能**晚于**第 1 个工具的 `start()` 完成，把 `bridge` 写成旧 iframe 的 bridge；此后新 tab 的事件经 `handleEvent → forward` 发向**已销毁的旧 iframe** → 丢失。
- 同理，`start()` 只重置了 `bridge`，**没有重置 `appTransport`**。tab 切换后、新 iframe 加载完成前，`handleEvent` 的 tool-progress 分支仍用旧 `appTransport.send(...)`，把进度发到已销毁的旧 iframe。

后果：闪回发生后，目标工具（尤其第 3 个）的 progress / tool-result 要么进 local pending 后经错乱的 bridge 丢失，要么发向已销毁 iframe，iframe 永远等不到任务 → 停在启动加载态。

### 3.2 根因 B：Host 注册表只重放 `tool-progress`，不重放 `tool-result`

`packages/session-ui/src/context/mcp-app-host.tsx`

```ts
push(key, event) {
  if (event.type === "tool-progress") lastProgress.set(key, event)  // ← 只记 progress
  ...
}
register(key, sink) {
  ...
  const progress = lastProgress.get(key)
  if (progress) sink(progress)          // ← 重挂载时只回放最近一次 progress
}
```

- 面板 tab 是**懒挂载**：工具完成后再切到它的 tab，`McpAppView` 重新 `host.register`，只会回放 `lastProgress`（最后一次 tool-progress），**`tool-result` 不在重放范围**。
- 若工具执行期间的 `tool-result` 事件已被对话流内联 McpAppView（同 key 的另一 sink）消费，或该 key 当时无 sink 而 pending 又因中间态被消费，面板 iframe 重挂载后拿不到最终结果，只能停在进度态。
- 此外，App 端（`mcpApp.ts`）的 `useNormalizedToolResult` 优先 `progress.uiEvent.final_result`、`toolResult.structuredContent` 兜底；重放只给最后一次 progress，若最后一次 progress 恰好不是携带 `final_result` 的那条（如审核通过后另发的进度），即使有进度也渲染不出最终数据。

### 3.3 根因 C：面板焦点闪回（问题一）使 `McpAppView` 的 `start()` 反复作废

- 闪回 = 同一 McpAppView 实例在 1s 内经历 `resourceUri: ui3 → ui1`，`start()` 代际 +1，ui3 的 iframe 在加载中途被丢弃，其 local pending 被 `pending.length = 0` 清空。
- ui3 的工具事件在面板侧没有稳定 sink，只能依赖 host pending/lastProgress 兜底；而兜底又受根因 B 限制（无 tool-result 重放）。
- 三个工具逐个执行时，若每个工具完成时焦点都不在它身上，则每个面板 iframe 重挂载后都只拿到 lastProgress（可能缺 final_result / 缺 tool-result）→ 全部卡"等待任务"。

---

## 4. 修复建议（按优先级）

> 实施状态：P0 与 P1 已全部修复（见各条目内"已实施"标注），P2 验证用例已补。

### P0（阻断）
1. **给 `onIframeLoad` / `oninitialized` / `bridge` / `appTransport` 全部挂上 `startGeneration` 代际校验**（✅ 已实施，见 `packages/app/src/components/mcp-app-view.tsx`）：
   - `onIframeLoad` 进入时记录 `const generation = startGeneration`，在 `await next.connect(...)` 后、`bridge = next` 前检查 `gen === startGeneration`，不等则 `close` 丢弃。
   - `oninitialized` 里同样先校验代际再置 `appInitialized`、再 `drainPending()`。
   - `start()` 开头把 `appTransport = undefined` 一并重置，`appTransport` 只在代际校验通过后赋值。

2. **面板焦点逻辑去失配**（✅ 已实施，见 `packages/app/src/pages/session/v2/mcp-apps-panel.tsx`）：
   - Effect ① 的 exists 判断改为 `list.some((group) => group.name === activeSkill)`（不再把 `undefined` 直连组排除），避免"最新工具是直连调用"时被拉回第一个命名分组。
   - Effect ② 焦点键从 `partID` 升级为 `partID + 实际所属分组名`：从 `groups` 里解析 `latest` 真实所在分组，分组重排（skill part 渐进生效）时跟随新组，不再因 partID 未变而停留在旧组。

### P1（体验/完整）
3. **Host 注册表把 `tool-result` 也纳入重放**（✅ 已实施，见 `packages/session-ui/src/context/mcp-app-host.tsx`）：
   - `push` 时把 `tool-result` 记入 `lastResult`；`register` 重放顺序为 pending 缓冲 → lastResult → lastProgress，pending 已含 tool-result 时跳过 lastResult 去重。
   - 懒挂载 tab 在工具完成后重挂载时，iframe 能拿到最终结果，不再卡"等待任务"。
4. 从 part 的 `metadata.mcp.result` 构造 tool-result 重放：**无需实施**——`McpTool` 在工具完成且 `metadata.mcp.result` 存在时必然 push tool-result，host `lastResult` 已覆盖该路径。

### P2（验证）
5. `packages/app/e2e/regression/mcp-apps-panel.spec.ts` 已补两个回归用例，**14/14 通过**，且均验证过"无修复时失败"：
   - "分组重标后焦点跟随"：skill part 渐进生效把最新工具重标到新组，焦点跟随、内容不闪回第一个 iframe（覆盖 P0-2）。
   - "tool-result 重放"：工具完成后切回其 tab，iframe 渲染最终结果 `result:ok`（覆盖 P1-3）。
   - 另补 `packages/session-ui/src/context/mcp-app-host.test.ts` 单测：重注册 sink 时重放 `lastResult`（8/8 通过）。

---

## 5. 附：关键文件索引

| 文件 | 职责 |
| --- | --- |
| `packages/app/src/pages/session/v2/mcp-apps-panel.tsx` | 两级 tab 渲染 + 焦点效果（问题一所在） |
| `packages/app/src/pages/session/v2/use-mcp-apps.ts` | 按 skill 分组 + `latestExecuted` 计算 |
| `packages/app/src/pages/session/v2/mcp-apps-panel-state.ts` | `buildSkillAppGroups` / `toolTabId` |
| `packages/app/src/components/mcp-app-view.tsx` | iframe 生命周期、`start()` 代际、事件转发（问题二所在） |
| `packages/session-ui/src/context/mcp-app-host.tsx` | 事件注册表 / pending / lastProgress 重放 |
| `packages/session-ui/src/components/mcp-tool.tsx` | 从 part 提取事件并 push 到 host |
| `mcps/pdf2json/mcp_apps_ui/*/src/core/mcpApp.ts` | iframe 侧接收 / final_result 归一化 |
