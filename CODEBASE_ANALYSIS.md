# opencode 代码库分析（二次开发辅助文档）

> 用途：供 AI 辅助二次开发时作为权威上下文。所有路径均相对仓库根目录 `d:\项目\AI-For-Redesign\代码库\opencode`。
> 分析基准：当前工作区快照（默认分支 `dev`）。

---

## 1. 项目定位

opencode 是一个开源 AI 编程助手（"AI-powered development tool"），形态为：

- 一个**本地服务端**（`opencode serve`，默认 `http://localhost:4096`），承载 Session 编排、工具执行、LLM 调用、权限控制；
- 多个**客户端**：终端 TUI、Web App、Electron 桌面端、IDE 插件（ACP 协议）、Slack 集成；
- 完整的**插件系统**与 **MCP**（Model Context Protocol）集成。

对二次开发的核心价值：这是一个"agent 编排引擎"——Session 管理、消息持久化（SQLite/Drizzle）、工具调用循环、权限系统、多 Provider LLM 接入、事件推送都已经成熟，可直接在其上构建垂直领域产品（如工业 AI 技改场景的自动诊断/方案生成 agent）。

---

## 2. 技术栈

| 层面 | 技术 |
|---|---|
| 运行时/包管理 | Bun 1.3.14（workspaces monorepo，turbo 编排） |
| 语言 | TypeScript（严格，禁 `any`） |
| 服务端函数式框架 | Effect 4.0.0-beta.83（HttpApi、Layer、Schema） |
| 前端框架 | SolidJS（Web App 与 TUI 共用） |
| 终端 UI | @opentui/solid 0.4.5 |
| 构建 | Vite 7（web）、Bun 脚本（服务端）、Electron（desktop） |
| 持久化 | Drizzle ORM + SQLite（`@effect/sql-sqlite-bun`） |
| LLM 接入 | 自研 `@opencode-ai/llm`（schema-first，多 provider 适配器）+ Vercel AI SDK（`ai` 6.x，见 `core/src/aisdk.ts`、`opencode/src/session/llm/ai-sdk.ts`） |
| 校验 | Effect Schema（服务端）+ Zod（部分外围） |
| 基础设施 | SST 4.x（`infra/`，Cloudflare Worker + Astro 站点） |
| 代码规范 | oxlint + prettier（无分号、120 列）；husky pre-push |
| 测试 | bun test（**禁止从仓库根目录运行**） |

---

## 3. Monorepo 包清单（packages/）

依赖方向硬性规则（来自 AGENTS.md，**必须遵守**）：

```
Schema ──► Core ──► Protocol ──► Server
Client 运行时：可依赖 Schema + Protocol，禁止依赖 Core/Server
sdk-next：组合 Client + Core + Server
```

### 3.1 服务端链路（按依赖顺序）

| 包 | npm 名 | 职责 | 二开关注度 |
|---|---|---|---|
| `packages/schema` | @opencode-ai/schema | 全部跨端数据契约：`session.ts`（Session Info/ListAnchor）、`event.ts`（事件 Definition/Data/Payload）、`agent.ts`（Agent V2）、`llm.ts`、`model.ts`、`prompt.ts`、`skill.ts` 等 | ★★★ 改数据结构先改这里 |
| `packages/core` | @opencode-ai/core | 共享核心：配置加载（`config/`）、工具定义基元（`tool/`：bash/edit/glob/grep/read/write/skill 等）、事件总线（`event/`）、LSP/MCP 配置、大量 util（flock、glob、retry、token…）、`session.ts`/`provider.ts`/`agent.ts` 兼容层 | ★★★ |
| `packages/protocol` | @opencode-ai/protocol | **API 契约层**：`src/api.ts` 用 Effect `HttpApi` 定义全部端点（health/location/agent/session/message/model/provider/event/pty/question 等 group），`errors.ts` 定义错误 | ★★★ 加 API 先改这里 |
| `packages/server` | @opencode-ai/server | **HTTP 服务器壳**：`src/api.ts` 调 `makeDefaultApi()` 实例化 protocol；`src/routes.ts` 用 `HttpApiBuilder.layer(Api, ...)` 挂 handlers/中间件/auth 生成 web handler；`auth.ts`、`cors.ts` | ★★ |
| `packages/opencode` | @opencode-ai/opencode | **主服务包（业务核心）**：CLI 入口 + Session V2 + 工具注册表 + Agent + Provider + server 路由 handlers 实现。详见第 5 节 | ★★★★★ |
| `packages/llm` | @opencode-ai/llm | schema-first LLM 核心：统一 LLMRequest/LLMEvent/Tool 语言，provider 差异收敛在 adapters（OpenAI Chat/Responses、Anthropic、Gemini、Bedrock、OpenAI 兼容）。支持 `generate`/`stream`/`prepare`，内置 prompt caching 策略（`cache: "auto"`）。设计文档见其 `DESIGN.md` | ★★★ 换/接模型看这里 |

### 3.2 客户端 SDK 链路

| 包 | 职责 |
|---|---|
| `packages/client` | 从 protocol 自动生成的类型化客户端。`src/generated`、`src/generated-effect` **禁止手改**；改了 protocol/server 后在 `packages/client` 下运行 `bun run generate` 重新生成。`src/index.ts` 提供手写 fetch 封装（baseUrl/query/headers/JSON body） |
| `packages/sdk/js` | 旧版 JS SDK（OpenAPI → @hey-api/openapi-ts 生成，含 SSE 类型）。重新生成：`./packages/sdk/js/script/build.ts` |
| `packages/sdk-next` | 新一代 SDK，组合 Client+Core+Server |
| `packages/cli` | `@opencode-ai/cli`（bin 名 `lildax`），独立 CLI 壳，依赖 core/sdk/server/tui |

### 3.3 UI / 多端

| 包 | 技术栈 | 与后端连接方式 |
|---|---|---|
| `packages/tui` | SolidJS + @opentui/solid，终端渲染 | `src/context/sdk.tsx` 用 `createOpencodeClient({ baseUrl: props.url })` 连 server |
| `packages/app` | SolidJS + Vite + @tanstack/solid-query + @solidjs/router，Web 应用 | `src/entry.tsx`：生产连 `http://localhost:4096`，开发用 `VITE_OPENCODE_SERVER_HOST/PORT`；`ServerSDKProvider`/`ServerSyncProvider` 注入 |
| `packages/desktop` | **Electron**（`bun dev` / `bun run build && bun run package`） | 包装 web/本地 server |
| `packages/ui` | 共享 UI 库：主题（`theme/`）、60+ 语言 i18n（`i18n/`）、tailwind 配置 | 被 app/tui/desktop 复用 |
| `packages/web` | Astro 官网 + SST 部署 | — |
| `packages/session-ui`、`packages/storybook` | 会话 UI 组件 / 组件展示 | — |

### 3.4 其他

| 包/目录 | 职责 |
|---|---|
| `packages/plugin` | 插件 API 类型定义（详见第 11 节） |
| `packages/codemode` | Code Mode：在隔离 runtime 中以 JS 编排工具的执行模式 |
| `packages/function` | 云函数（SST api） |
| `packages/slack` | Slack 集成 |
| `packages/opencode/src/acp` | ACP（Agent Client Protocol，IDE 接入） |
| `infra/` | SST 云基础设施（app/console/enterprise/lake/monitoring/stats） |
| `script/` | 仓库级脚本：`generate.ts`（代码生成总入口）、`publish.ts`、`changelog.ts`、`translate-app.ts` 等 |
| `.opencode/` | 仓库自用配置：agent（triage）、command、主题、glossary（术语表，含 zh-cn） |

---

## 4. 启动链路（用户运行 `opencode` 后发生什么）

1. `packages/opencode/bin/opencode` → `packages/opencode/src/index.ts`：yargs 注册 CLI 命令：`generate`、`run`、`serve`、`debug`、`tui`、`mcp`、`acp`、`export`、`import`、`github`、`pr`、`models`、`providers`、`stats`、`upgrade`、`uninstall` 等（命令实现在 `src/cli/cmd/`，每个命令一个文件）。
2. `opencode`（无参数）→ TUI：`src/cli/cmd/tui.ts` → 拉起本地 server + `packages/tui` 渲染。
3. `opencode serve` → `src/cli/cmd/serve.ts` → `src/server/server.ts` 启动 HTTP 服务：根路由、事件路由、PTY 路由、实例路由分层；实例路由通过 `HttpApiBuilder.layer(InstanceHttpApi)` 挂载 `sessionHandlers`、`providerHandlers`、`questionHandlers` 等（实现在 `src/server/routes/instance/httpapi/handlers/`）。
4. 开发模式：仓库根 `bun dev` = `bun run --cwd packages/opencode --conditions=browser src/index.ts`。
5. Web 端开发：`bun dev:web`（packages/app，vite）；桌面端：`bun dev:desktop`。

---

## 5. 核心包 `packages/opencode/src/` 目录详解

| 目录 | 职责 |
|---|---|
| `session/` | **Session V2 核心**（见第 6 节）。`session.ts`（V2 实现，Drizzle SessionTable/PartTable 持久化，行记录↔业务对象互转）、`prompt.ts`、`message-v2.ts`、`tools.ts`（执行期工具解析）、`llm/`（LLM 调用：ai-sdk.ts / native-request.ts）、`prompt/*.txt`（各模型系统提示词：anthropic/gpt/gemini/kimi/plan…）、`compaction.ts`、`summary.ts`、`run-state.ts`、`status.ts`、`revert.ts` |
| `server/` | HTTP 层：`routes/instance/httpapi/groups/`（API group 定义：config/control-plane/control/event/experimental/file/global/instance/mcp/metadata/permission/project/provider/pty/question/session/sync/tui/workspace）、`handlers/`（对应实现）、`middleware/`（authorization/cors/fence/instance-context/proxy/schema-error/workspace-routing）；`server.ts`（服务器装配）、`event.ts`、`projectors.ts`、`websocket-tracker.ts`、`mdns.ts` |
| `tool/` | 内置工具实现 + `registry.ts`（注册表）。内置：shell、read、grep、glob、edit、write、task（子代理）、todo、webfetch、websearch、lsp、plan、apply_patch、skill、question、code-mode；每个工具配 `*.txt` 提示词 |
| `agent/` | Agent 定义 `agent.ts` + `prompt/*.txt`（compaction/explore/summary/title）+ `subagent-permissions.ts` |
| `provider/` | Provider 抽象：provider.ts、auth.ts、transform.ts、model-status.ts、error.ts |
| `config/` | 配置系统：config.ts、agent.ts、command.ts、parse.ts、paths.ts、plugin.ts、tui.ts（遵循 self-export 模式） |
| `cli/` | CLI 命令实现：`cmd/`（各命令）、`cmd/run/`（headless run 的完整运行时：runtime/stream/footer/permission…）、`tui/`（worker/layer）、`bootstrap.ts` |
| `storage/` | SQLite/Drizzle 存储层（schema.ts、storage.ts） |
| `permission/` | 权限系统：evaluate.ts、arity.ts |
| `mcp/` | MCP 集成：index.ts、auth.ts、catalog.ts、browser.ts、oauth-* |
| `lsp/` | LSP 客户端：client.ts、launch.ts、diagnostic.ts |
| `plugin/` | 内置插件：github-copilot、openai/codex、modal、azure、cerebras、cloudflare、xai 等 + `loader.ts` |
| `acp/` | ACP 协议（IDE 接入）实现 |
| `control-plane/` | 工作区编排（workspace.ts、workspace-adapter-runtime.ts、adapters/worktree.ts） |
| `project/` | 项目实例生命周期（bootstrap、instance-context、instance-store、vcs） |
| `effect/` | Effect 运行时装配（app-runtime.ts、bootstrap-runtime.ts、runner.ts、instance-registry.ts） |
| `skill/` | Skill 发现与加载（discovery.ts） |
| `share/`、`sync/`、`snapshot/`、`worktree/`、`git/` | 会话分享 / 同步 / 快照 / git worktree / git 操作 |
| `question/`、`background/`、`bus/`、`format/`、`image/`、`patch/`、`ide/`、`installation/`、`env/`、`id/` | 问答、后台任务、事件总线、格式化、图片、补丁、IDE 集成、安装、环境、ID 生成 |
| `index.ts` | CLI 总入口（yargs） |
| `event-manifest.ts`、`event-v2-bridge.ts` | 事件清单与 V1/V2 事件桥接 |

---

## 6. Session V2 架构（最重要，二开必须先懂）

### 6.1 关键设计（来自 AGENTS.md 硬性约束，违反即错）

1. **持久化准入与模型执行分离**：`SessionV2.prompt(...)` 先写一条 durable `session_input` 行，再调度 advisory 的 `SessionExecution.wake(sessionID)`（除非 `resume: false` 请求 admit-only）。序列化 runner 在**安全边界**把准入输入提升为可见用户消息。
2. **幂等重试**：复用 Session ID = 采纳既有 Session；复用 prompt message ID 仅在 Session+prompt+delivery mode 完全一致时按精确重试对账，冲突则失败。
3. **SessionExecution 进程全局**、按 Session ID 寻址：本地实现持有进程级 Session coordinator，drain 启动时经 `SessionStore` + `LocationServiceMap.get(session.location)` 发现放置位置。
4. **SessionRunner / 模型解析 / 工具注册表 / 权限 / 文件系统全部 Location-scoped**。省略 `Location.workspaceID` = 隐式本地放置。
5. **每个 provider turn 恰好一次 `llm.stream(request)`**，durable 续跑前重新加载投影历史。**禁止**桥接 legacy `SessionPrompt.loop(...)` 或用内存工具循环编排。
6. **本地 drain 保持进程本地**（集群化另行设计）。`SessionRunCoordinator` 合并同 Session 显式 resume、合并 prompt 唤醒、允许不同 Session 并发。
7. **投递词汇**：默认 steer（下一安全 provider-turn 边界提升）；显式 `queue` 输入在 Session 即将空闲时逐条提升。任何新用户输入提升会重置 agent 的 provider-turn 配额（一批 steer 只重置一次）。
8. **System Context 代数/注册表/内建**在 `src/system-context`（注意：工作区快照中该目录尚未落地，属规划中）；Context Source producer 随观测域放置；Session History 选择与 Context Epoch 持久化归 Session 所有。

### 6.2 Session 生命周期（prompt → 完成）

```
Client(POST prompt) → server/routes handlers/session.ts
  → SessionV2.prompt() 写 session_input（durable）
  → SessionExecution.wake(sessionID)
  → SessionRunCoordinator 串行化同 Session drain
  → SessionRunner（Location-scoped）:
       读投影历史 → 组装 system prompt(agent) + tools(经 session/tools.ts 从 ToolRegistry 解析)
       → llm.stream(request)（session/llm/，每 turn 一次）
       → 流式 LLMEvent → tool call → ToolRegistry 执行 → 结果回填
       → 循环直至 turn 结束 → 事件/消息持久化（Drizzle: SessionTable/PartTable）
  → 事件经 bus → server/event.ts（SSE/WebSocket，websocket-tracker.ts）推给所有客户端
```

### 6.3 关键文件

| 文件 | 作用 |
|---|---|
| `packages/opencode/src/session/session.ts` | V2 核心 + 持久化映射 |
| `packages/opencode/src/session/tools.ts` | 从 ToolRegistry 解析工具 → 结合 agent/model/permission 生成 LLM tool schema，包装 execute/completeToolCall/附件/插件事件 |
| `packages/opencode/src/session/llm.ts` + `session/llm/*` | LLM 调用（ai-sdk 路径与 native 路径） |
| `packages/opencode/src/tool/registry.ts` | ToolRegistry：`ids/all/named/tools(...)`，按 model/provider/agent/permission 过滤 |
| `packages/opencode/src/server/routes/instance/httpapi/handlers/session.ts` | Session HTTP handler 组（挂 Session.Service、SessionPrompt、SessionRunState、Agent.Service、Permission.Service、SessionStatus、Todo、SessionSummary） |
| `packages/schema/src/session.ts` / `event.ts` | Session 与事件数据契约 |

---

## 7. 工具系统（扩展点 1：加新工具）

- **注册表**：`packages/opencode/src/tool/registry.ts`（L91-L120 初始化内置工具列表）。
- **Tool 接口基元**：`packages/core/src/tool/tool.ts`（bash/edit/glob/grep/read/write/skill 定义在 `packages/core/src/tool/`）；服务端重量级实现在 `packages/opencode/src/tool/`。
- **每个工具** = 一个 TS 模块 + 同名 `.txt` 提示词（工具描述），如 `read.ts` + `read.txt`。
- **加新工具步骤**（例如加一个"工艺流程图查询"工具）：
  1. 在 `packages/opencode/src/tool/` 新建 `mytool.ts` + `mytool.txt`（参考 `read.ts`/`read.txt` 最简范式）；
  2. 在 `tool/registry.ts` 的初始化列表注册；
  3. 如需出现在 schema/类型层，更新 `packages/core/src/tool/tools.ts` 相关定义；
  4. 若工具结果影响 API 展示，检查 `session/tools.ts` 的包装链路与 schema 事件定义；
  5. 在 `packages/opencode` 目录跑 `bun typecheck`，测试也在包目录跑。

---

## 8. Agent / Provider / LLM 抽象

- **Agent**：`packages/schema/src/agent.ts`（V2 schema：ID/model/provider request/system prompt/mode/permissions）+ `packages/opencode/src/agent/agent.ts`（服务端）+ `packages/opencode/src/config/agent.ts`（用户自定义 agent 配置）。子代理工具：`tool/task.ts`。
- **Provider**：`packages/opencode/src/provider/provider.ts`（注册各云端厂商）、`packages/core/src/provider.ts`。第三方登录类 provider 走插件（`plugin/github-copilot`、`plugin/openai/codex` 等）。
- **LLM 调用**：
  - 新路径 `packages/llm`：`LLM.request()` 构建统一请求 → `LLMClient.generate/stream`；provider 适配器（`@opencode-ai/llm/providers`）负责差异；事件流 provider 中立（textDelta/toolCall/finish…）。
  - 旧路径 `session/llm/ai-sdk.ts`（Vercel AI SDK）。
  - **接自建/私有模型**：优先在 `packages/llm` 增加/复用 OpenAI 兼容 adapter，或在 `provider/provider.ts` 注册自定义 provider + models。
- **系统提示词**：`session/prompt/*.txt` 按模型家族分文件；agent 级提示在 `agent/` 与用户配置。

---

## 9. HTTP API 与事件系统（扩展点 2：加 API）

### 9.1 一次 API 请求的数据流

```
packages/client (generated fetch 封装)
  → HTTP → packages/server/src/routes.ts (HttpApiBuilder.layer)
  → protocol 定义的端点（packages/protocol/src/api.ts, makeDefaultApi）
  → packages/opencode/src/server/routes/instance/httpapi/handlers/*.ts (业务实现)
  → core 服务 (session/tool/...)
```

### 9.2 加一个新端点（必须按序改 4 处）

1. `packages/protocol/src/api.ts`：在对应 group（或新 group）用 Effect HttpApi 添加端点定义；
2. `packages/opencode/src/server/routes/instance/httpapi/groups/`：新 group 文件或扩展现有 group；
3. `packages/opencode/src/server/routes/instance/httpapi/handlers/`：实现 handler 并挂到 `server.ts` 的 handler 组；
4. 在 `packages/client` 运行 **`bun run generate`** 重新生成客户端（禁止手改 `src/generated*`）；如需旧 SDK，跑 `./packages/sdk/js/script/build.ts`（全流程也可用根 `script/generate.ts`）。

### 9.3 事件推送

- 事件契约：`packages/schema/src/event.ts`（`Definition`/`Data`/`Payload`，`define()` 包装 type+schema → 带 ID/metadata/location/data 的 payload）。
- 服务端：`packages/opencode/src/server/event.ts` + `websocket-tracker.ts` + `event-manifest.ts`（V1/V2 桥接在 `event-v2-bridge.ts`）。客户端订阅走 SSE（旧 SDK 有 SSE 类型）/WebSocket。
- 加新事件：在 `packages/schema/src/event.ts`（或对应事件模块）`define()` → 服务端 `bus` 发布 → 客户端消费。

---

## 10. 客户端多端连接速查

| 端 | 入口 | 连接 |
|---|---|---|
| TUI | `packages/tui/src/index.tsx` / `app.tsx` | `context/sdk.tsx` → `createOpencodeClient({ baseUrl })` |
| Web | `packages/app/src/entry.tsx` / `app.tsx` | 生产 `http://localhost:4096`；开发 `VITE_OPENCODE_SERVER_HOST/PORT`；`ServerSDKProvider` + `ServerSyncProvider` |
| Desktop | `packages/desktop`（Electron） | `bun dev` / `build && package` |
| IDE | `packages/opencode/src/acp/` | ACP 协议 |
| 编程接入 | `packages/sdk/js`（旧）/ `packages/client` + `packages/sdk-next`（新） | fetch + SSE |

---

## 11. 插件系统（扩展点 3：不改核心代码的定制）

- 类型定义：`packages/plugin/src/index.ts`。`PluginInput` 提供 `client/project/directory/serverUrl` 等；插件 = `(input) => Hooks`。
- 可用 Hooks：`auth`、`provider`、`chat.message`、`chat.params`、`chat.headers`、`permission.ask`、`tool.execute.before`、`tool.execute.after`、`tool.definition`、`tool.permission` 等。
- 插件加载：`packages/opencode/src/plugin/loader.ts` + `config/plugin.ts`；用户插件经 opencode.json 配置加载。
- **二开建议**：优先用插件做"拦截/增强类"需求（自定义权限策略、注入上下文、第三方认证），避免 fork 核心代码。

---

## 12. 常用命令（务必在正确目录执行）

```bash
# 安装
bun install                      # 根目录（postinstall 自动 fix-node-pty）

# 开发
bun dev                          # 根：跑 opencode CLI（TUI）
bun dev:web                      # Web App (packages/app, vite)
bun dev:desktop                  # Electron
bun dev:console / dev:stats      # 控制台 / 统计站

# 质量检查
bun typecheck                    # 根：turbo 全量
bun typecheck                    # 单包：进入 packages/opencode 等包目录执行（禁止直接跑 tsc）
bun run lint                     # oxlint（根）

# 测试（禁止从根目录跑！）
cd packages/opencode && bun test # 或各包目录内

# 代码生成（改了 protocol 或 server 的 HttpApi 之后必须执行）
cd packages/client && bun run generate
./packages/sdk/js/script/build.ts   # 重新生成旧 JS SDK（或根 script/generate.ts 全流程）
```

---

## 13. 二次开发常见任务导航

| 需求 | 改动位置 |
|---|---|
| 加内置工具 | `packages/opencode/src/tool/`（新 ts+txt）+ `tool/registry.ts` 注册 |
| 加自定义 Agent | 用户侧：opencode.json / `config/agent.ts`；代码侧：`packages/opencode/src/agent/` + `schema/src/agent.ts` |
| 接私有/新模型 | `packages/llm`（adapter）或 `provider/provider.ts`；提示词适配加 `session/prompt/*.txt` |
| 改系统提示词 | `packages/opencode/src/session/prompt/*.txt`（按模型家族）、`agent/prompt/*.txt` |
| 加 HTTP API | protocol → groups → handlers → client generate（见 9.2） |
| 加事件类型 | `packages/schema/src/event.ts` + bus 发布 + 客户端消费 |
| 改 Session 行为 | `packages/opencode/src/session/`（**先读第 6 节约束**） |
| 定制权限 | `packages/opencode/src/permission/` + 插件 `permission.ask` |
| 做 Web 界面定制 | `packages/app`（SolidJS）+ `packages/ui`（主题/i18n，含 zh.ts） |
| 集成 MCP 服务 | `packages/opencode/src/mcp/`（auth/catalog）+ `packages/core/src/config/mcp.ts` |
| 做行业垂直能力（如化工技改知识库） | 建议：自定义 agent + skill（`skill/discovery.ts`）+ 自定义工具（查库/检索）+ 插件注入上下文，尽量不动 Session 核心 |

---

## 14. 开发规范硬性规则（摘自 AGENTS.md，AI 修改代码时必须遵守）

- 分支名 ≤3 个单词、连字符分隔，不带 `feat/`、`fix/` 前缀；默认分支 `dev`（本地可能无 `main`）。
- Commit/PR 标题：`type(scope): summary`，type ∈ feat/fix/docs/chore/refactor/test。
- 风格：无 `try/catch`（尽量）、无 `any`、用 Bun API（`Bun.file()`）、依赖类型推断、`const` 优先、早返回禁 `else`、函数式数组方法优先、**禁止 import 别名**（`import { foo as bar }`）、**禁止 star import**（用 `import { Project } from "@opencode-ai/core/project"` 后 `Project.ID`）、不必要的解构、单次使用的变量要内联。
- Drizzle schema 字段用 snake_case，不写字符串列名。
- `src/config` 新模块遵循 self-export 模式（`export * as ConfigAgent from "./agent"`）。
- Effect 生成器中先绑定服务变量再调用，禁止嵌套 `yield* (yield* Foo.Service).bar()`。
- 重模块用动态 import 且保持在最小作用域内。

---

## 15. 已知注意事项

1. **generated 目录禁止手改**：`packages/client/src/generated*`、`packages/sdk/js/src/gen*` 一律走 generate 命令。
2. **测试/类型检查的目录限制**：根目录有 `do-not-run-tests-from-root` 守卫；typecheck 用包内 `bun typecheck` 不用 `tsc`。
3. **Effect 4 beta**：API 与稳定版差异较大，写服务端代码时参考邻近实现，勿凭 3.x 记忆编码。
4. **大量 patchedDependencies**（effect、ai-sdk 系列等，见根 package.json）：升级依赖时注意 `patches/` 目录补丁可能失效。
5. **V2 迁移中**：`session/message.ts`（V1）与 `message-v2.ts` 并存；`event-v2-bridge.ts` 做桥接；AGENTS.md 提到的 `src/system-context` 目录在当前快照尚未落地，属演进中设计——二开以现存代码为准。
6. **catalog 依赖管理**：workspace 内统一版本走根 `package.json` 的 `catalog:`，新增依赖优先入 catalog。
7. Windows 环境：部分脚本（`dev:console` 的 ulimit 等）为 POSIX 习惯，Windows 下可能需适配；`node-pty` 相关 postinstall 已有 fix 脚本。
