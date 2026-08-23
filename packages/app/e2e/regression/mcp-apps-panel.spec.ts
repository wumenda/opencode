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

const STEP_UI_HTML = `<!doctype html>
<html>
  <head><meta charset="utf-8"><title>Step</title></head>
  <body><h1 data-step-name>step</h1></body>
</html>`

// 一张带进度通知的共享 step-ui，被两/三个不同 resourceUri 复用（供 step1/2/3 演示工具）。
function stepMcpApps(uris: string[]) {
  return {
    servers: [{ name: "ui-server" }],
    rpc: ({ method, params }: { method: string; params: unknown }) => {
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
        if (uris.includes(p.uri)) return { contents: [{ uri: p.uri, mimeType: "text/html", text: STEP_UI_HTML }] }
        return { contents: [] }
      }
      if (method === "tools/list") return { tools: [] }
      return { _meta: {} }
    },
  }
}

function mcpApps() {
  return {
    servers: [{ name: "ui-server" }],
    rpc: ({ method, params }: { method: string; params: unknown }) => {
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
          return { contents: [{ uri: "ui://dashboard", mimeType: "text/html", text: UI_HTML }] }
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
  }
}

test.describe("MCP Apps Panel", () => {
  test("shows Apps tab in the V2 side panel", async ({ page }) => {
    const toolID = "prt_mcp_app"
    await setupTimeline(page, {
      settings: { newLayoutDesigns: true },
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
      mcpApps: mcpApps(),
    })

    // The auto-expand effect opens the panel when the first MCP app appears.
    const panel = page.locator('[data-component="mcp-apps-panel"]')
    await expect(panel).toBeVisible()

    // V2 side panel tab is relabeled to "Apps".
    await expect(page.getByRole("tab", { name: "Apps" })).toBeVisible()
  })

  test("renders MCP app iframe in the panel after tool execution", async ({ page }) => {
    const toolID = "prt_mcp_app"
    await setupTimeline(page, {
      settings: { newLayoutDesigns: true },
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
      mcpApps: mcpApps(),
    })

    const panel = page.locator('[data-component="mcp-apps-panel"]')
    await expect(panel).toBeVisible()
    const iframe = panel.locator('iframe[sandbox="allow-scripts"]')
    await expect(iframe).toBeVisible()
    await expect(iframe).toHaveAttribute("src", /^blob:/)
  })

  test("groups a skill's MCP tools into two-level tabs", async ({ page }) => {
    await setupTimeline(page, {
      settings: { newLayoutDesigns: true },
      messages: [
        userMessage(),
        assistantMessage([
          toolPart("prt_skill_12", "skill", "completed", { name: "step-12" }),
          toolPart("prt_step1", "ui-server_step1", "completed", {}, {
            metadata: {
              mcp: {
                server: "ui-server",
                tool: "step1",
                ui: { resourceUri: "ui://step1/progress.html", visibility: ["model", "app"] },
              },
            },
          }),
          toolPart("prt_step2", "ui-server_step2", "completed", {}, {
            metadata: {
              mcp: {
                server: "ui-server",
                tool: "step2",
                ui: { resourceUri: "ui://step2/progress.html", visibility: ["model", "app"] },
              },
            },
          }),
        ]),
      ],
      mcpApps: stepMcpApps(["ui://step1/progress.html", "ui://step2/progress.html"]),
    })

    const panel = page.locator('[data-component="mcp-apps-panel"]')
    await expect(panel).toBeVisible()

    // 一级：skill 标签（step-12）携带工具数量角标
    const skillTab = panel.getByRole("tab", { name: /step-12/ })
    await expect(skillTab).toBeVisible()
    await expect(skillTab.getByText("2", { exact: true })).toBeVisible()

    // 二级：两个 tool 子标签（以 resourceUri 为文本）
    await expect(panel.getByRole("tab", { name: "ui://step1/progress.html" })).toBeVisible()
    await expect(panel.getByRole("tab", { name: "ui://step2/progress.html" })).toBeVisible()

    // 切换 sub-tab 更新激活态
    await panel.getByRole("tab", { name: "ui://step2/progress.html" }).click()
    await expect(panel.getByRole("tab", { name: "ui://step2/progress.html" })).toHaveAttribute("aria-selected", "true")
  })

  test("shows empty state when no MCP apps", async ({ page }) => {
    await setupTimeline(page, {
      settings: { newLayoutDesigns: true },
      messages: [userMessage(), assistantMessage([toolPart("prt_bash", "bash", "completed", { command: "true" }, { output: "ok", metadata: {} })])],
    })

    await page.getByRole("button", { name: "Toggle review" }).click()

    const panel = page.locator('[data-component="mcp-apps-panel"]')
    await expect(panel).toBeVisible()
    await expect(page.getByText("No MCP apps available")).toBeVisible()
  })
})