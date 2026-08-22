import { createContext, useContext, type ParentProps } from "solid-js"

export type ModelContextUpdate = {
  content?: unknown[]
  structuredContent?: Record<string, unknown>
}

export type ModelContextHost = {
  set: (update: ModelContextUpdate) => void
  latest: () => ModelContextUpdate | undefined
}

export function createModelContextStore(): ModelContextHost {
  let value: ModelContextUpdate | undefined
  return {
    set(update) {
      value = update
    },
    latest() {
      return value
    },
  }
}

const McpModelContextContext = createContext<ModelContextHost>()

export function McpModelContextProvider(props: ParentProps<{ host: ModelContextHost }>) {
  return <McpModelContextContext.Provider value={props.host}>{props.children}</McpModelContextContext.Provider>
}

export function useMcpModelContext(): ModelContextHost {
  const host = useContext(McpModelContextContext)
  if (!host) throw new Error("McpModelContextProvider missing")
  return host
}