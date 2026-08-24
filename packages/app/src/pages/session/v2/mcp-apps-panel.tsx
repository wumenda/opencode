import { For, Show, createEffect, createMemo, type JSX } from "solid-js"
import { Icon } from "@opencode-ai/ui/icon"
import { useLanguage } from "@/context/language"
import { McpAppView } from "@/components/mcp-app-view"
import type { McpAppInfo } from "@opencode-ai/session-ui/mcp-tool"
import {
  toolTabId,
  type McpAppsPanelState,
  type SkillAppGroup,
} from "./mcp-apps-panel-state"

export type McpAppsPanelProps = {
  groups: () => SkillAppGroup[]
  /** 最近一次执行的 MCP App（含 partID）：partID 变化即新 tool 执行，自动切换 tab 焦点。 */
  latestExecuted: () => { app: McpAppInfo; partID: string } | undefined
  /** 当前会话 ID：传递给 McpAppView 用于 McpAppHost 事件按 session 隔离。 */
  sessionID?: string
  state: McpAppsPanelState
}

export function McpAppsPanel(props: McpAppsPanelProps): JSX.Element {
  const language = useLanguage()
  const groups = props.groups
  const state = props.state

  // groups 变化时自动选中首个 skill（与它的首个 tool）；组件禁用/清空时复位。
  // 注意：undefined 是合法的直连组名，activeSkill=undefined 且存在直连组时不干预焦点，
  // 避免"最新工具是直连调用"时被反复拉回第一个命名分组（tab 闪回根因之一）。
  createEffect(() => {
    const list = groups()
    if (list.length === 0) {
      state.setActiveSkill(undefined)
      state.setActiveTool(undefined)
      return
    }
    const activeSkill = state.activeSkill()
    if (list.some((group) => group.name === activeSkill)) return
    const first = list[0]
    state.setActiveSkill(first.name)
    state.setActiveTool(first.apps[0] ? toolTabId(first.apps[0]) : undefined)
  })

  // 新 tool 执行时（latestExecuted.partID 变化），把右侧展示区 tab 焦点切换到该 tool 的 UI。
  // 同一 part 的进度刷新不会重复切换；同一 resourceUri 的重复执行（新 part）也会切换。
  // 焦点键 = partID + 实际所属分组：skill 标签由 currentSkill 游标随 part 流式更新而渐进
  // 变化（skill part pending→running、或工具先以旧标签出现），partID 未变但分组重排时必须
  // 跟随最新分组，避免"高亮新 tab、内容却闪回第一个 iframe"的错位。
  let lastExecutedFocusKey: string | undefined
  createEffect(() => {
    const latest = props.latestExecuted()
    if (!latest) return
    const group = groups().find((g) => g.apps.some((a) => toolTabId(a) === toolTabId(latest.app)))
    const focusKey = `${latest.partID}:${group?.name ?? ""}`
    if (focusKey === lastExecutedFocusKey) return
    lastExecutedFocusKey = focusKey
    state.setActiveSkill(group?.name)
    state.setActiveTool(toolTabId(latest.app))
  })

  const activeGroup = createMemo(
    () => groups().find((group) => group.name === state.activeSkill()) ?? groups()[0],
  )

  const activeTool = createMemo(() => {
    const group = activeGroup()
    if (!group) return undefined
    return group.apps.find((app) => toolTabId(app) === state.activeTool()) ?? group.apps[0]
  })

  const selectTool = (app: McpAppInfo) => state.setActiveTool(toolTabId(app))

  return (
    <div data-component="mcp-apps-panel" class="flex h-full flex-col overflow-hidden bg-v2-background-bg-base contain-strict">
      <Show
        when={groups().length > 0}
        fallback={
          <div class="flex h-full flex-col items-center justify-center gap-3 text-center">
            <Icon name="mcp" class="size-8 opacity-10" />
            <div class="max-w-56 text-14-regular text-v2-text-text-muted">
              {language.t("mcp.app.panel.empty")}
            </div>
          </div>
        }
      >
        {/* 第一层：skill 标签栏 */}
        <div class="flex shrink-0 items-center gap-1 border-b border-v2-border-border-base px-2">
          <For each={groups()}>
            {(group) => {
              const isActive = () => state.activeSkill() === group.name
              return (
                <button
                  type="button"
                  role="tab"
                  aria-selected={isActive()}
                  class="flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2 text-13-medium transition-colors"
                  classList={{
                    "border-v2-border-border-bold text-v2-text-text-base": isActive(),
                    "border-transparent text-v2-text-text-muted hover:text-v2-text-text-base": !isActive(),
                  }}
                  onClick={() => {
                    state.setActiveSkill(group.name)
                    state.setActiveTool(group.apps[0] ? toolTabId(group.apps[0]) : undefined)
                  }}
                >
                  <Icon name={group.name ? "brain" : "mcp"} class="size-3.5" />
                  <span>{group.name ?? language.t("mcp.app.panel.direct")}</span>
                  <span class="ml-1 rounded-full bg-v2-background-bg-layer-01 px-1.5 text-11-regular text-v2-text-text-muted">
                    {group.apps.length}
                  </span>
                </button>
              )
            }}
          </For>
        </div>

        {/* 第二层：选中 skill 下的 tool 标签栏（懒挂载 iframe，只渲染激活项） */}
        <Show when={(activeGroup()?.apps.length ?? 0) > 0}>
          <div class="flex shrink-0 items-center gap-1 border-b border-v2-border-border-base bg-v2-background-bg-layer-01 px-2">
            <For each={activeGroup()!.apps}>
              {(app, index) => {
                const isActive = () => toolTabId(app) === state.activeTool()
                return (
                  <button
                    type="button"
                    role="tab"
                    aria-selected={isActive()}
                    class="flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-1.5 text-13-regular transition-colors"
                    classList={{
                      "border-v2-border-border-bold text-v2-text-text-base": isActive(),
                      "border-transparent text-v2-text-text-muted hover:text-v2-text-text-base": !isActive(),
                    }}
                    onClick={() => selectTool(app)}
                  >
                    <Icon name="mcp" class="size-3" />
                    <span>{app.toolName ?? app.resourceUri}</span>
                    <span class="ml-1 rounded-full bg-v2-background-bg-layer-01 px-1.5 text-11-regular text-v2-text-text-muted">
                      #{index() + 1}
                    </span>
                  </button>
                )
              }}
            </For>
          </div>
        </Show>

        {/* 激活 tool 的 iframe 渲染；skill 下暂无带 UI 工具时显示占位 */}
        <div class="min-h-0 flex-1 overflow-hidden p-2">
          <Show
            when={activeTool()}
            fallback={
              <div class="flex h-full flex-col items-center justify-center gap-2 text-center">
                <div class="max-w-64 text-14-regular text-v2-text-text-muted">
                  {language.t("mcp.app.panel.noUiTools")}
                </div>
              </div>
            }
          >
            {(app) => (
              <McpAppView
                server={app().server}
                resourceUri={app().resourceUri}
                sessionID={props.sessionID}
                instanceID={app().instanceID}
                fillHeight
              />
            )}
          </Show>
        </div>
      </Show>
    </div>
  )
}