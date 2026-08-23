import { describe, expect, test } from "bun:test"
import type { McpAppInfo } from "@opencode-ai/session-ui/mcp-tool"
import { buildSkillAppGroups, toolTabId } from "./mcp-apps-panel-state"

function app(partial: { server?: string; resourceUri?: string; skill?: string; instanceID?: string; toolName?: string }): McpAppInfo {
  return {
    server: partial.server ?? "s",
    resourceUri: partial.resourceUri ?? "u",
    instanceID: partial.instanceID ?? "i_1",
    toolName: partial.toolName,
    skill: partial.skill,
    fallbackData: undefined,
  }
}

describe("buildSkillAppGroups", () => {
  test("groups apps under their skill, preserving first-appearance order", () => {
    const groups = buildSkillAppGroups([
      app({ skill: "skillA", server: "a", resourceUri: "ui://x", instanceID: "p1", toolName: "step1" }),
      app({ skill: "skillA", server: "b", resourceUri: "ui://y", instanceID: "p2", toolName: "step2" }),
      app({ skill: undefined, server: "c", resourceUri: "ui://z", instanceID: "p3", toolName: "step3" }),
    ])
    expect(groups).toEqual([
      {
        name: "skillA",
        apps: [
          { server: "a", resourceUri: "ui://x", instanceID: "p1", toolName: "step1", skill: "skillA", fallbackData: undefined },
          { server: "b", resourceUri: "ui://y", instanceID: "p2", toolName: "step2", skill: "skillA", fallbackData: undefined },
        ],
      },
      {
        name: undefined,
        apps: [{ server: "c", resourceUri: "ui://z", instanceID: "p3", toolName: "step3", skill: undefined, fallbackData: undefined }],
      },
    ])
  })

  test("keeps the same resource under different call instances as separate apps", () => {
    const groups = buildSkillAppGroups([
      app({ skill: "s", server: "a", resourceUri: "ui://x", instanceID: "p1" }),
      app({ skill: "s", server: "a", resourceUri: "ui://x", instanceID: "p2" }),
    ])
    expect(groups).toHaveLength(1)
    expect(groups[0]!.apps.map((a) => a.instanceID)).toEqual(["p1", "p2"])
  })

  test("merges same-part updates (running -> completed) into one app", () => {
    const groups = buildSkillAppGroups([
      app({ skill: "s", server: "a", resourceUri: "ui://x", instanceID: "p1" }),
      app({ skill: "s", server: "a", resourceUri: "ui://x", instanceID: "p1" }),
    ])
    expect(groups).toHaveLength(1)
    expect(groups[0]!.apps).toEqual([
      { server: "a", resourceUri: "ui://x", instanceID: "p1", toolName: undefined, skill: "s", fallbackData: undefined },
    ])
  })

  test("keeps the same resource under different skills as separate groups", () => {
    const groups = buildSkillAppGroups([
      app({ skill: "s1", server: "a", resourceUri: "ui://x", instanceID: "p1" }),
      app({ skill: "s2", server: "a", resourceUri: "ui://x", instanceID: "p2" }),
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
  test("uses server::resourceUri::instanceID as the key", () => {
    expect(toolTabId({ server: "a", resourceUri: "ui://x", instanceID: "p1", fallbackData: undefined })).toBe("a::ui://x::p1")
  })
})
