import { createContext, useContext } from "solid-js"
import type { JSX, ParentProps } from "solid-js"

export type McpAppRendererInput = {
  server: string
  resourceUri: string
  fallbackData?: unknown
}

/** Renders an MCP App (SEP-1865) inline. Provided by hosts that support ui:// app resources. */
export type McpAppRenderer = (input: McpAppRendererInput) => JSX.Element

const McpAppRendererContext = createContext<McpAppRenderer>()

export function McpAppRendererProvider(props: ParentProps<{ render: McpAppRenderer }>) {
  return <McpAppRendererContext.Provider value={props.render}>{props.children}</McpAppRendererContext.Provider>
}

/** Returns the host-provided app renderer, or undefined when the host does not render MCP Apps. */
export function useMcpAppRenderer() {
  return useContext(McpAppRendererContext)
}
