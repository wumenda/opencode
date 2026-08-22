import { describe, expect, test } from "bun:test"
import { createMcpAppHostRegistry, type McpAppEvent } from "./mcp-app-host"

describe("createMcpAppHostRegistry", () => {
  test("routes events to the registered sink", () => {
    const reg = createMcpAppHostRegistry()
    const received: McpAppEvent[] = []
    const un = reg.register("a/ui://x", (e) => received.push(e))
    reg.push("a/ui://x", { type: "tool-input-partial", arguments: { axis: "x" } })
    expect(received).toEqual([{ type: "tool-input-partial", arguments: { axis: "x" } }])
    un()
  })

  test("buffers pushes before registration and flushes on register", () => {
    const reg = createMcpAppHostRegistry()
    const received: McpAppEvent[] = []
    reg.push("a/ui://x", { type: "tool-result", result: { content: [{ type: "text", text: "ok" }] } })
    reg.register("a/ui://x", (e) => received.push(e))
    expect(received).toHaveLength(1)
  })

  test("drops pushes for an unregistered key after unregister", () => {
    const reg = createMcpAppHostRegistry()
    const received: McpAppEvent[] = []
    const un = reg.register("a/ui://x", (e) => received.push(e))
    un()
    reg.push("a/ui://x", { type: "tool-input-partial", arguments: {} })
    expect(received).toHaveLength(0)
  })
})