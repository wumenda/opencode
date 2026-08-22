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
})