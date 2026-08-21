import { describe, expect, test } from "bun:test"
import type { Tool as MCPToolDef } from "@modelcontextprotocol/sdk/types.js"
import { toolUi } from "@/mcp/catalog"

function def(_meta: unknown): MCPToolDef {
  return {
    name: "show_dashboard",
    description: "Show dashboard",
    inputSchema: { type: "object", properties: {} },
    ...(typeof _meta === "undefined" ? {} : { _meta: _meta as MCPToolDef["_meta"] }),
  } as MCPToolDef
}

describe("McpCatalog.toolUi", () => {
  test("reads _meta.ui.resourceUri (new format)", () => {
    const ui = toolUi(def({ ui: { resourceUri: "ui://dashboard", visibility: ["model", "app"] } }))
    expect(ui).toEqual({ resourceUri: "ui://dashboard", visibility: ["model", "app"] })
  })

  test("reads deprecated flat _meta[\"ui/resourceUri\"]", () => {
    const ui = toolUi(def({ "ui/resourceUri": "ui://legacy" }))
    expect(ui).toEqual({ resourceUri: "ui://legacy", visibility: ["model", "app"] })
  })

  test("returns undefined when there is no _meta", () => {
    expect(toolUi(def(undefined))).toBeUndefined()
  })

  test("app-only visibility excludes the model", () => {
    const ui = toolUi(def({ ui: { resourceUri: "ui://dashboard", visibility: ["app"] } }))
    expect(ui).toEqual({ resourceUri: "ui://dashboard", visibility: ["app"] })
  })
})