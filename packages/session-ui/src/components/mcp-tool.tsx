import { createMemo, Show } from "solid-js"
import type { ToolPart } from "@opencode-ai/sdk/v2"
import { useI18n } from "@opencode-ai/ui/context/i18n"
import { Progress } from "@opencode-ai/ui/progress"
import { BasicTool } from "./basic-tool"
import { useMcpAppRenderer } from "../context/mcp-app"

export type McpAppInfo = {
  server: string
  resourceUri: string
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

/** Extracts the inline MCP App (SEP-1865) to render for a completed tool part, if any. */
export function mcpAppFromPart(part: ToolPart): McpAppInfo | undefined {
  if (part.state.status !== "completed") return
  const mcp = record(toolMetadata(part)?.mcp)
  if (!mcp) return
  const server = mcp.server
  const resourceUri = record(mcp.ui)?.resourceUri
  if (typeof server !== "string" || !server) return
  if (typeof resourceUri !== "string" || !resourceUri) return
  return { server, resourceUri, fallbackData: mcp.result }
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
  const app = createMemo(() => mcpAppFromPart(props.part))
  const progress = createMemo(() => mcpProgressFromPart(props.part))
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
        <Show when={app()}>{(info) => renderApp?.(info())}</Show>
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
