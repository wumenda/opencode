import { createEffect, createMemo, Show } from "solid-js"
import type { ToolPart } from "@opencode-ai/sdk/v2"
import { useI18n } from "@opencode-ai/ui/context/i18n"
import { Progress } from "@opencode-ai/ui/progress"
import { BasicTool } from "./basic-tool"
import { useMcpAppRenderer } from "../context/mcp-app"
import { useMcpAppHost, type CallToolResult } from "../context/mcp-app-host"

export type McpAppInfo = {
  server: string
  resourceUri: string
  skill?: string
  fallbackData?: unknown
}

export type McpProgressInfo = {
  progress: number
  total?: number
  message?: string
}

function record(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : undefined
}

function toolMetadata(part: ToolPart) {
  return "metadata" in part.state ? part.state.metadata : undefined
}

/** Extracts the inline MCP App (SEP-1865) to render for a running, completed, or cancelled (error) tool part, if any. */
export function mcpAppFromPart(part: ToolPart): McpAppInfo | undefined {
  // running / completed / error 才可能承载 ui:// App；error（取消）需保持 App 挂载以便推送取消原因。
  if (part.state.status !== "running" && part.state.status !== "completed" && part.state.status !== "error") return
  const mcp = record(toolMetadata(part)?.mcp)
  if (!mcp) return
  const server = mcp.server
  const resourceUri = record(mcp.ui)?.resourceUri
  if (typeof server !== "string" || !server) return
  if (typeof resourceUri !== "string" || !resourceUri) return
  // 结果不再经 fallbackData 注入，改由宿主注册表（McpAppHost）把运行中/最终事件推送给已挂载的 App。
  return { server, resourceUri, fallbackData: undefined }
}

/** Extracts the skill name from a `skill` tool part's input, if any. */
export function skillNameFromPart(part: ToolPart): string | undefined {
  if (part.tool !== "skill") return undefined
  if (part.state.status !== "running" && part.state.status !== "completed") return undefined
  const input = part.state.input
  if (input && typeof input === "object" && typeof (input as Record<string, unknown>).name === "string")
    return (input as Record<string, unknown>).name as string
  return undefined
}

/** Extracts live MCP progress for a running tool part, if any. */
export function mcpProgressFromPart(part: ToolPart): McpProgressInfo | undefined {
  if (part.state.status !== "running") return
  const value = record(toolMetadata(part)?.mcpProgress)
  if (!value) return
  const progress = value.progress
  if (typeof progress !== "number") return
  const total = value.total
  const message = value.message
  return {
    progress,
    total: typeof total === "number" ? total : undefined,
    message: typeof message === "string" ? message : undefined,
  }
}

export function McpTool(props: {
  part: ToolPart
  hideDetails?: boolean
  defaultOpen?: boolean
  open?: boolean
  onOpenChange?: (open: boolean) => void
  deferContent?: boolean
}) {
  const i18n = useI18n()
  const renderApp = useMcpAppRenderer()
  const host = useMcpAppHost()
  const app = createMemo(() => mcpAppFromPart(props.part))
  const progress = createMemo(() => mcpProgressFromPart(props.part))
  // McpAppHost 事件按 sessionID 隔离：key 带上 part 归属会话，避免跨 session 串扰。
  const appKey = (info: McpAppInfo) => `${props.part.sessionID}:${info.server}/${info.resourceUri}`

  // 当前 running 状态的输入，作为流式部分输入推送给已挂载的 App。
  const runningInput = createMemo<Record<string, unknown> | undefined>(() => {
    if (props.part.state.status !== "running") return undefined
    const input = props.part.state.input
    // 仅接受纯对象输入，非纯对象则跳过推送。
    return typeof input === "object" && input !== null ? (input as Record<string, unknown>) : undefined
  })

  // 工具运行中且已渲染 App 时，把部分输入推送给宿主注册表（由 McpAppView 转发进 iframe）。
  createEffect(() => {
    const info = app()
    const input = runningInput()
    if (!info || !input) return
    host.push(appKey(info), { type: "tool-input-partial", arguments: input })
  })

  // 工具 completed 且携带 metadata.mcp.result 时，把最终结果推送给已挂载的 App。
  createEffect(() => {
    const info = app()
    if (!info) return
    if (props.part.state.status !== "completed") return
    const mcp = record(toolMetadata(props.part)?.mcp)
    const result = mcp?.result
    if (result === undefined) return
    host.push(appKey(info), { type: "tool-result", result: result as CallToolResult })
  })

  // 工具 running 且已渲染 App 时，把流式 progress 推送给宿主注册表（由 McpAppView 转发进 iframe）。
  createEffect(() => {
    const info = app()
    const value = progress()
    if (!info || !value) return
    host.push(appKey(info), {
      type: "tool-progress",
      progress: value.progress,
      total: value.total,
      message: value.message,
    })
  })

  // 工具 error（取消）且已渲染 App 时，把取消原因推送给已挂载的 App，使其保持挂载并展示取消态。
  createEffect(() => {
    const info = app()
    if (!info) return
    if (props.part.state.status !== "error") return
    const err = (props.part.state as { error?: string }).error
    host.push(appKey(info), { type: "tool-cancelled", reason: err ?? "cancelled" })
  })

  const percent = createMemo(() => {
    const value = progress()
    if (!value?.total || value.total <= 0) return
    return Math.min(100, Math.max(0, Math.round((value.progress / value.total) * 100)))
  })

  return (
    <div data-component="mcp-tool">
      <BasicTool
        icon="mcp"
        status={props.part.state.status}
        trigger={{ title: i18n.t("ui.basicTool.called", { tool: props.part.tool }) }}
        hideDetails={props.hideDetails}
        defaultOpen={props.defaultOpen ?? app() !== undefined}
        open={props.open}
        onOpenChange={props.onOpenChange}
        defer={props.deferContent}
      >
        {/* Non-keyed on purpose: part updates must not remount the sandboxed app iframe. */}
        <Show when={app()}>
          {(info) => renderApp?.({ ...info(), sessionID: props.part.sessionID })}
        </Show>
      </BasicTool>
      <Show when={progress()}>
        {(value) => (
          <div data-slot="mcp-tool-progress">
            <Show when={percent() !== undefined} fallback={<span data-slot="mcp-tool-progress-label">{value().message}</span>}>
              <Progress value={percent()} minValue={0} maxValue={100}>
                {value().message}
              </Progress>
            </Show>
          </div>
        )}
      </Show>
    </div>
  )
}
