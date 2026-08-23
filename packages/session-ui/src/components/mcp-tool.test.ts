import { describe, expect, test } from "bun:test"
import type { ToolPart } from "@opencode-ai/sdk/v2"
import { mcpAppFromPart, mcpProgressFromPart, skillNameFromPart } from "./mcp-tool"

function part(input: {
  id?: string
  status?: "pending" | "running" | "completed" | "error"
  tool?: string
  inputValue?: Record<string, unknown>
  stateMetadata?: Record<string, unknown>
}): ToolPart {
  const status = input.status ?? "completed"
  return {
    id: input.id ?? "part_1",
    sessionID: "ses_1",
    messageID: "msg_1",
    type: "tool",
    callID: "call_1",
    tool: input.tool ?? "weather_show_dashboard",
    state: {
      status,
      input: input.inputValue ?? {},
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
      instanceID: "part_1",
      toolName: "show_dashboard",
      // 结果改由宿主注册表推送，fallbackData 恒为 undefined，避免与注册表推送重复。
      fallbackData: undefined,
    })
  })

  test("returns app info while tool is running (no fallbackData)", () => {
    const info = mcpAppFromPart(part({ status: "running", stateMetadata: { mcp: mcpMeta } }))
    expect(info).toEqual({
      server: "weather",
      resourceUri: "ui://dashboard",
      instanceID: "part_1",
      toolName: "show_dashboard",
      fallbackData: undefined,
    })
  })

  test("returns app info for a cancelled (error) tool so it stays mounted", () => {
    const info = mcpAppFromPart(part({ status: "error", stateMetadata: { mcp: { server: "ui", ui: { resourceUri: "ui://x" } } } }))
    expect(info).toEqual({ server: "ui", resourceUri: "ui://x", instanceID: "part_1", toolName: undefined, fallbackData: undefined })
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

  test("uses the part id as the per-call instance id", () => {
    const info = mcpAppFromPart(part({ id: "prt_call_2", stateMetadata: { mcp: mcpMeta } }))
    expect(info).toEqual({
      server: "weather",
      resourceUri: "ui://dashboard",
      instanceID: "prt_call_2",
      toolName: "show_dashboard",
      fallbackData: undefined,
    })
  })

  test("omits toolName when the mcp metadata has no tool", () => {
    const info = mcpAppFromPart(part({ stateMetadata: { mcp: { server: "ui", ui: { resourceUri: "ui://x" } } } }))
    expect(info).toEqual({ server: "ui", resourceUri: "ui://x", instanceID: "part_1", toolName: undefined, fallbackData: undefined })
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

describe("skillNameFromPart", () => {
  test("returns the skill name for a completed skill tool", () => {
    expect(skillNameFromPart(part({ tool: "skill", inputValue: { name: "refinery" } }))).toBe("refinery")
  })

  test("returns the skill name for a running skill tool", () => {
    expect(skillNameFromPart(part({ tool: "skill", status: "running", inputValue: { name: "refinery" } }))).toBe("refinery")
  })

  test("returns undefined for non-skill tools", () => {
    expect(skillNameFromPart(part({}))).toBeUndefined()
  })

  test("returns undefined when the skill input has no name", () => {
    expect(skillNameFromPart(part({ tool: "skill", inputValue: {} }))).toBeUndefined()
  })

  test("returns undefined while the skill tool is still pending", () => {
    expect(skillNameFromPart(part({ tool: "skill", status: "pending", inputValue: { name: "x" } }))).toBeUndefined()
  })
})
