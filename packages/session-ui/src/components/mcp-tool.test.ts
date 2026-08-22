import { describe, expect, test } from "bun:test"
import type { ToolPart } from "@opencode-ai/sdk/v2"
import { mcpAppFromPart, mcpProgressFromPart } from "./mcp-tool"

function part(input: {
  status?: "pending" | "running" | "completed" | "error"
  stateMetadata?: Record<string, unknown>
}): ToolPart {
  const status = input.status ?? "completed"
  return {
    id: "part_1",
    sessionID: "ses_1",
    messageID: "msg_1",
    type: "tool",
    callID: "call_1",
    tool: "weather_show_dashboard",
    state: {
      status,
      input: {},
      output: "done",
      title: "Show dashboard",
      metadata: input.stateMetadata ?? {},
      time: { start: 1, end: 2 },
    },
  } as ToolPart
}

const mcpMeta = {
  server: "weather",
  tool: "show_dashboard",
  ui: { resourceUri: "ui://dashboard", visibility: ["model", "app"] },
  result: { content: [{ type: "text", text: "hello" }] },
}

describe("mcpAppFromPart", () => {
  test("returns app info for completed tool with mcp ui resourceUri", () => {
    const info = mcpAppFromPart(part({ stateMetadata: { mcp: mcpMeta } }))
    expect(info).toEqual({
      server: "weather",
      resourceUri: "ui://dashboard",
      // 结果改由宿主注册表推送，fallbackData 恒为 undefined，避免与注册表推送重复。
      fallbackData: undefined,
    })
  })

  test("returns app info while tool is running (no fallbackData)", () => {
    const info = mcpAppFromPart(part({ status: "running", stateMetadata: { mcp: mcpMeta } }))
    expect(info).toEqual({
      server: "weather",
      resourceUri: "ui://dashboard",
      fallbackData: undefined,
    })
  })

  test("returns undefined for error status even with mcp metadata", () => {
    expect(mcpAppFromPart(part({ status: "error", stateMetadata: { mcp: mcpMeta } }))).toBeUndefined()
  })

  test("returns undefined without mcp metadata", () => {
    expect(mcpAppFromPart(part({}))).toBeUndefined()
  })

  test("returns undefined when mcp metadata has no resourceUri", () => {
    const info = mcpAppFromPart(
      part({ stateMetadata: { mcp: { server: "weather", tool: "show_dashboard", ui: {} } } }),
    )
    expect(info).toBeUndefined()
  })

  test("returns undefined when server is not a string", () => {
    const info = mcpAppFromPart(part({ stateMetadata: { mcp: { server: 42, ui: { resourceUri: "ui://x" } } } }))
    expect(info).toBeUndefined()
  })
})

describe("mcpProgressFromPart", () => {
  test("returns progress for running tool with mcpProgress metadata", () => {
    const progress = mcpProgressFromPart(
      part({ status: "running", stateMetadata: { mcpProgress: { progress: 5, total: 10, message: "Loading" } } }),
    )
    expect(progress).toEqual({ progress: 5, total: 10, message: "Loading" })
  })

  test("returns undefined once tool completed even if metadata lingers", () => {
    const progress = mcpProgressFromPart(
      part({ status: "completed", stateMetadata: { mcpProgress: { progress: 5, total: 10 } } }),
    )
    expect(progress).toBeUndefined()
  })

  test("returns undefined without mcpProgress metadata", () => {
    expect(mcpProgressFromPart(part({ status: "running" }))).toBeUndefined()
  })

  test("returns undefined when progress is not a number", () => {
    const progress = mcpProgressFromPart(part({ status: "running", stateMetadata: { mcpProgress: { progress: "5" } } }))
    expect(progress).toBeUndefined()
  })
})
