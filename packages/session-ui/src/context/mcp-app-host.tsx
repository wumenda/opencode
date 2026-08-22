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

export type McpAppSink = (event: McpAppEvent) => void

export type McpAppHost = {
  register: (key: AppKey, sink: McpAppSink) => () => void
  push: (key: AppKey, event: McpAppEvent) => void
}

/** 路由 + 预注册缓冲：App 尚未挂载时 push 的事件暂存，注册时冲刷。 */
export function createMcpAppHostRegistry(): McpAppHost {
  const sinks = new Map<AppKey, McpAppSink>()
  const pending = new Map<AppKey, McpAppEvent[]>()
  return {
    register(key, sink) {
      sinks.set(key, sink)
      const buffered = pending.get(key)
      if (buffered) {
        pending.delete(key)
        buffered.forEach(sink)
      }
      return () => {
        if (sinks.get(key) === sink) sinks.delete(key)
      }
    },
    push(key, event) {
      const sink = sinks.get(key)
      if (sink) {
        sink(event)
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