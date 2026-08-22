import { expect, test } from "@playwright/test"
import {
  assistantMessage,
  partUpdated,
  setupTimeline,
  toolPart,
  userMessage,
} from "../performance/timeline-stability/fixture"

function mcpProgressTool(step: number) {
  return toolPart("prt_mcp_progress", "ui-server_show_dashboard", "running", {}, {
    metadata: {
      mcp: {
        server: "ui-server",
        tool: "show_dashboard",
        ui: { resourceUri: "ui://dashboard", visibility: ["model", "app"] },
      },
      mcpProgress: { progress: step, total: 5, message: `Rendering dashboard ${step}/5` },
    },
  })
}

// 带 ui:// App 的工具 part：running 承载运行中输入，completed 承载 metadata.mcp.result。
function mcpAppTool(status: "running" | "completed") {
  const base = {
    metadata: {
      mcp: {
        server: "ui-server",
        tool: "show_dashboard",
        ui: { resourceUri: "ui://dashboard", visibility: ["model", "app"] },
      },
    },
  }
  if (status === "running") {
    return toolPart("prt_mcp_app", "ui-server_show_dashboard", "running", { query: "wind" }, {
      title: "Dashboard",
      ...base,
    })
  }
  return toolPart("prt_mcp_app", "ui-server_show_dashboard", "completed", { query: "wind" }, {
    title: "Dashboard",
    metadata: {
      mcp: {
        ...base.metadata.mcp,
        result: { content: [{ type: "text", text: "render-ok" }] },
      },
    },
  })
}

test.describe("MCP tool progress", () => {
  test("renders an advancing progress bar as mcpProgress updates", async ({ page }) => {
    const timeline = await setupTimeline(page, {
      messages: [userMessage(), assistantMessage([mcpProgressTool(1)])],
    })

    const bar = page.locator('[data-slot="mcp-tool-progress"] [data-component="progress"]')
    await expect(bar).toHaveCount(1)
    await expect(bar).toHaveAttribute("aria-valuenow", "20")
    await expect(page.getByText("Rendering dashboard 1/5")).toBeVisible()

    await timeline.send(partUpdated(mcpProgressTool(3)))
    await expect(bar).toHaveAttribute("aria-valuenow", "60")
    await expect(page.getByText("Rendering dashboard 3/5")).toBeVisible()
    // 进度推进期间工具卡不崩溃：卡片容器保持存在且可见（初始断言之后持续验证）。
    await expect(page.locator('[data-slot="mcp-tool-progress"]')).toHaveCount(1)
    await expect(page.locator('[data-slot="mcp-tool-progress"]')).toBeVisible()

    await timeline.send(partUpdated(mcpProgressTool(5)))
    await expect(bar).toHaveAttribute("aria-valuenow", "100")
    await expect(page.getByText("Rendering dashboard 5/5")).toBeVisible()
    await expect(page.locator('[data-slot="mcp-tool-progress"]')).toHaveCount(1)
    await expect(page.locator('[data-slot="mcp-tool-progress"]')).toBeVisible()
  })

  test("mounts an MCP App while running and streams completion without crashing", async ({ page }) => {
    const timeline = await setupTimeline(page, {
      mcpApps: { servers: [{ name: "ui-server", status: "connected" }] },
      messages: [userMessage(), assistantMessage([mcpAppTool("running")])],
    })

    // running 的无 mcp-app 工具卡保留 running；App 宿主已随工具渲染（不因挂载崩溃）。
    const tool = page.locator('[data-component="mcp-tool"]')
    await expect(tool).toHaveCount(1)
    await timeline.send(partUpdated(mcpAppTool("running")))
    await expect(tool).toHaveCount(1)
    await expect(tool).toBeVisible()

    // 发送 completed 且 metadata.mcp.result 的 part，应不抛错、时间线保持挂载的 App 工具卡。
    await timeline.send(partUpdated(mcpAppTool("completed")))
    await expect(tool).toHaveCount(1)
    await expect(tool).toBeVisible()
  })
})