import { For, Show, createEffect, createMemo, type JSX } from "solid-js"
import { Icon } from "@opencode-ai/ui/icon"
import { useLanguage } from "@/context/language"
import { McpAppView } from "@/components/mcp-app-view"
import { appTabId, type McpAppsPanelState } from "./mcp-apps-panel-state"
import type { McpAppInfo } from "@opencode-ai/session-ui/mcp-tool"
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js"

export type McpAppsPanelProps = {
  apps: () => McpAppInfo[]
  state: McpAppsPanelState
}

export function McpAppsPanel(props: McpAppsPanelProps): JSX.Element {
  const language = useLanguage()
  const apps = props.apps
  const state = props.state

  // 当 apps 列表变化时，自动选中第一个 Tab（如果当前没有选中项或选中项已不存在）
  createEffect(() => {
    const list = apps()
    const active = state.activeTabId()
    if (list.length === 0) {
      state.setActiveTabId(undefined)
      return
    }
    const exists = active && list.some((app) => appTabId(app) === active)
    if (!exists) state.setActiveTabId(appTabId(list[0]))
  })

  const activeApp = createMemo(() => {
    const active = state.activeTabId()
    if (!active) return undefined
    return apps().find((app) => appTabId(app) === active)
  })

  return (
    <div data-component="mcp-apps-panel" class="flex h-full flex-col overflow-hidden bg-v2-background-bg-base contain-strict">
      <Show
        when={apps().length > 0}
        fallback={
          <div class="flex h-full flex-col items-center justify-center gap-3 text-center">
            <Icon name="mcp" class="size-8 opacity-10" />
            <div class="max-w-56 text-14-regular text-v2-text-text-muted">
              {language.t("mcp.app.panel.empty")}
            </div>
          </div>
        }
      >
        {/* Tab 栏 */}
        <div class="flex shrink-0 items-center gap-1 border-b border-v2-border-border-base px-2">
          <For each={apps()}>
            {(app) => {
              const id = appTabId(app)
              const isActive = () => state.activeTabId() === id
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
                  onClick={() => state.setActiveTabId(id)}
                >
                  <Icon name="mcp" class="size-3.5" />
                  <span>{app.server}</span>
                </button>
              )
            }}
          </For>
        </div>

        {/* 活跃 App 的 iframe 渲染 */}
        <div class="min-h-0 flex-1 overflow-hidden">
          <Show when={activeApp()}>
            {(app) => (
              <McpAppView
                server={app().server}
                resourceUri={app().resourceUri}
                fallbackData={
                  typeof app().fallbackData === "object" && app().fallbackData !== null
                    ? (app().fallbackData as CallToolResult)
                    : undefined
                }
              />
            )}
          </Show>
        </div>
      </Show>
    </div>
  )
}