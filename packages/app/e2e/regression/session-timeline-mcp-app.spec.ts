import { expect, test } from "@playwright/test"
import {
  assistantMessage,
  setupTimeline,
  toolPart,
  userMessage,
} from "../performance/timeline-stability/fixture"

const UI_HTML = `<!doctype html>
<html>
  <head><meta charset="utf-8"><title>E2E Dashboard</title></head>
  <body>
    <h1>Steam dashboard</h1>
    <p>Live reactor data</p>
  </body>
</html>`

test.describe("mcp app inline render", () => {
  test("renders an MCP App iframe for a tool part with ui:// metadata", async ({ page }) => {
    const toolID = "prt_mcp_app"
    await setupTimeline(page, {
      messages: [
        userMessage(),
        assistantMessage([
          toolPart(toolID, "ui-server_show_dashboard", "completed", {}, {
            metadata: {
              mcp: {
                server: "ui-server",
                tool: "show_dashboard",
                ui: { resourceUri: "ui://dashboard", visibility: ["model", "app"] },
                result: { content: [{ type: "text", text: "dashboard ok" }] },
              },
            },
          }),
        ]),
      ],
      mcpApps: {
        servers: [{ name: "ui-server" }],
        rpc: ({ method, params }) => {
          if (method === "initialize") {
            const p = params as { protocolVersion?: string }
            return {
              protocolVersion: p.protocolVersion ?? "2025-06-18",
              capabilities: {},
              serverInfo: { name: "ui-server", version: "1.0.0" },
            }
          }
          if (method === "resources/read") {
            const p = params as { uri: string }
            if (p.uri === "ui://dashboard") {
              return {
                contents: [{ uri: "ui://dashboard", mimeType: "text/html", text: UI_HTML }],
              }
            }
            return { contents: [] }
          }
          if (method === "tools/list") {
            return {
              tools: [
                {
                  name: "show_dashboard",
                  description: "Show the dashboard",
                  inputSchema: { type: "object", properties: {} },
                },
              ],
            }
          }
          return { _meta: {} }
        },
      },
    })

    const wrapper = page.locator(`[data-timeline-part-id="${toolID}"]`)
    await expect(wrapper).toHaveCount(1)
    await expect(wrapper.locator('[data-component="mcp-tool"]')).toHaveCount(1)

    const iframe = wrapper.locator("iframe")
    await expect(iframe).toBeVisible()
    await expect(iframe).toHaveAttribute("sandbox", "allow-scripts")
    await expect(iframe).toHaveAttribute("src", /^blob:/)
  })

  test("keeps non-MCP tools on the plain tool card", async ({ page }) => {
    const toolID = "prt_mcp_plain"
    await setupTimeline(page, {
      messages: [
        userMessage(),
        assistantMessage([
          toolPart(toolID, "bash", "completed", { command: "true" }, { output: "ok", metadata: {} }),
        ]),
      ],
    })

    const wrapper = page.locator(`[data-timeline-part-id="${toolID}"]`)
    await expect(wrapper.locator('[data-component="mcp-tool"]')).toHaveCount(0)
    await expect(wrapper.locator("iframe")).toHaveCount(0)
    await expect(wrapper).toContainText("ok")
  })
})