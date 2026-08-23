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
  return {
    register(key, sink) {
      let set = sinks.get(key)
      if (!set) {
        set = new Set()
        sinks.set(key, set)
      }
      set.add(sink)
      const buffered = pending.get(key)
      if (buffered) {
        pending.delete(key)
        buffered.forEach(sink)
      }
      const progress = lastProgress.get(key)
      if (progress) sink(progress)
      return () => {
        const current = sinks.get(key)
        if (!current) return
        current.delete(sink)
        if (current.size === 0) sinks.delete(key)
      }
    },
    push(key, event) {
      if (event.type === "tool-progress") lastProgress.set(key, event)
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