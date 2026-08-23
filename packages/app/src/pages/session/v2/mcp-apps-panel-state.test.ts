import { describe, expect, test } from "bun:test"
import type { McpAppInfo } from "@opencode-ai/session-ui/mcp-tool"
import { buildSkillAppGroups, toolTabId } from "./mcp-apps-panel-state"

function app(partial: { server?: string; resourceUri?: string; skill?: string }): McpAppInfo {
  return { server: partial.server ?? "s", resourceUri: partial.resourceUri ?? "u", skill: partial.skill, fallbackData: undefined }
}

describe("buildSkillAppGroups", () => {
  test("groups apps under their skill, preserving first-appearance order", () => {
    const groups = buildSkillAppGroups([
      app({ skill: "skillA", server: "a", resourceUri: "ui://x" }),
      app({ skill: "skillA", server: "b", resourceUri: "ui://y" }),
      app({ skill: undefined, server: "c", resourceUri: "ui://z" }),
    ])
    expect(groups).toEqual([
      {
        name: "skillA",
        apps: [
          { server: "a", resourceUri: "ui://x", skill: "skillA", fallbackData: undefined },
          { server: "b", resourceUri: "ui://y", skill: "skillA", fallbackData: undefined },
        ],
      },
      {
        name: undefined,
        apps: [{ server: "c", resourceUri: "ui://z", skill: undefined, fallbackData: undefined }],
      },
    ])
  })

  test("dedupes the same tool app within one skill", () => {
    const groups = buildSkillAppGroups([
      app({ skill: "s", server: "a", resourceUri: "ui://x" }),
      app({ skill: "s", server: "a", resourceUri: "ui://x" }),
    ])
    expect(groups).toHaveLength(1)
    expect(groups[0]!.apps).toEqual([{ server: "a", resourceUri: "ui://x", skill: "s", fallbackData: undefined }])
  })

  test("keeps the same resource under different skills as separate apps", () => {
    const groups = buildSkillAppGroups([
      app({ skill: "s1", server: "a", resourceUri: "ui://x" }),
      app({ skill: "s2", server: "a", resourceUri: "ui://x" }),
    ])
    expect(groups).toHaveLength(2)
    expect(groups[0]!.apps).toHaveLength(1)
    expect(groups[1]!.apps).toHaveLength(1)
  })

  test("empty input yields empty groups", () => {
    expect(buildSkillAppGroups([])).toEqual([])
  })
})

describe("toolTabId", () => {
  test("uses server::resourceUri as the key", () => {
    expect(toolTabId({ server: "a", resourceUri: "ui://x", fallbackData: undefined })).toBe("a::ui://x")
  })
})