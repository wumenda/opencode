import { createContext, useContext, type ParentProps } from "solid-js"

/**
 * MCP CallToolResult 的宿主侧最小结构。session-ui 无法解析 @modelcontextprotocol/sdk
 * （该依赖仅存在于 app 包），故在此本地声明等效结构；宿主（app）在推送给 iframe 时
 * 再 cast 回 SDK 的完整类型。
 */
export type CallToolResult = {
  content: Array<Record<string, unknown>>
  isError?: boolean
  structuredContent?: unknown
}

export type AppKey = string

export type McpAppEvent =
  | { type: "tool-input"; arguments: Record<string, unknown> }
  | { type: "tool-input-partial"; arguments: Record<string, unknown> }
  | { type: "tool-result"; result: CallToolResult }
  | { type: "tool-cancelled"; reason: string }
  | { type: "tool-progress"; progress: number; total?: number; message?: string; uiEvent?: unknown }

export type McpAppSink = (event: McpAppEvent) => void

export type McpAppHost = {
  register: (key: AppKey, sink: McpAppSink) => () => void
  push: (key: AppKey, event: McpAppEvent) => void
}

/** 路由 + 预注册缓冲：App 尚未挂载时 push 的事件暂存，注册时冲刷。 */
export function createMcpAppHostRegistry(): McpAppHost {
  const sinks = new Map<AppKey, Set<McpAppSink>>()
  const pending = new Map<AppKey, McpAppEvent[]>()
  // 记住每个 App 最近一次的 tool-progress：iframe 因 timeline 重渲染/虚拟化被重挂载时，
  // 重放该进度让 step-ui 恢复最终进度，而不是重置回 "0% / 就绪"。
  const lastProgress = new Map<AppKey, McpAppEvent>()
  // 记住每个 App 最近一次的 tool-result：懒挂载的 tab（面板）在工具完成后再注册 sink 时，
  // 重放最终结果，否则重挂载的 iframe 永远等不到 tool-result（卡在加载/等待任务）。
  const lastResult = new Map<AppKey, McpAppEvent>()
  // 记住每个 App 最近一次的完整版 tool-input（ui/notifications/tool-input）：UI 模板只
  // 监听完整版，晚挂载的 App 依赖它兜底拿到入参，否则懒挂载的 iframe 因 toolInput
  // 缺失卡"等待任务"。流式 partial 是瞬时片段，不记录。
  const lastToolInput = new Map<AppKey, McpAppEvent>()
  return {
    register(key, sink) {
      let set = sinks.get(key)
      if (!set) {
        set = new Set()
        sinks.set(key, set)
      }
      set.add(sink)
      // 重放顺序：lastToolInput → pending 缓冲 → lastResult → lastProgress。
      // tool-input 必须先于 tool-result（App 状态机 processing -> result_ready）；
      // pending 已含对应事件时跳过 last*，避免重复投递。
      const buffered = pending.get(key)
      if (buffered) pending.delete(key)
      const replay: McpAppEvent[] = [...(buffered ?? [])]
      const toolInput = lastToolInput.get(key)
      if (toolInput && !replay.some((ev) => ev.type === "tool-input")) replay.unshift(toolInput)
      const result = lastResult.get(key)
      if (result && !replay.some((ev) => ev.type === "tool-result")) replay.push(result)
      const progress = lastProgress.get(key)
      if (progress) replay.push(progress)
      for (const ev of replay) sink(ev)
      return () => {
        const current = sinks.get(key)
        if (!current) return
        current.delete(sink)
        if (current.size === 0) sinks.delete(key)
      }
    },
    push(key, event) {
      if (event.type === "tool-progress") lastProgress.set(key, event)
      if (event.type === "tool-result") lastResult.set(key, event)
      if (event.type === "tool-input") lastToolInput.set(key, event)
      const set = sinks.get(key)
      if (set && set.size > 0) {
        // 广播到同一 App 的所有挂载面（对话流工具卡 + 侧栏 skill tab 面板共用同一 key）。
        set.forEach((sink) => sink(event))
        return
      }
      const buf = pending.get(key) ?? []
      buf.push(event)
      pending.set(key, buf)
    },
  }
}

const McpAppHostContext = createContext<McpAppHost>()

export function McpAppHostProvider(props: ParentProps<{ host: McpAppHost }>) {
  return <McpAppHostContext.Provider value={props.host}>{props.children}</McpAppHostContext.Provider>
}

export function useMcpAppHost(): McpAppHost {
  const host = useContext(McpAppHostContext)
  if (!host) throw new Error("McpAppHostProvider missing")
  return host
}