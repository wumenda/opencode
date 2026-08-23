import { expect, test } from "@playwright/test"
import {
  assistantMessage,
  partUpdated,
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

// 功能自包含的 step-ui（配置面），模拟真实 step-ui/dist/index.html：完成 AppBridge iframe 侧
// 握手，并监听 notifications/progress 把 message + "进度 / 总量" 渲染进 body。
const STEP_UI_HTML = `<!doctype html>
<html>
  <head><meta charset="utf-8"><title>Step</title></head>
  <body>
    <div id="out">就绪</div>
    <script>
      var out = document.getElementById("out")
      function render(params) {
        var msg = (params && params.message) ? String(params.message) : ""
        var progress = (params && typeof params.progress === "number") ? params.progress : 0
        var total = (params && typeof params.total === "number") ? params.total : 0
        // uiEvent 扩展字段：iframe 侧直接从 progress.uiEvent.<key> 读取逐步渲染数据。
        if (params && params.uiEvent && params.uiEvent.event_type) {
          out.textContent = "uiEvent:" + params.uiEvent.event_type
          return
        }
        if (msg) out.textContent = msg
        else out.textContent = progress + " / " + total
      }
      var initId = null
      var initiated = false
      function send(o) { window.parent.postMessage(o, "*") }
      function tryHandshake() {
        if (initiated) return
        // 复用同一 initId 直到握手成功（真实 step-ui 行为）：若每轮重新生成，
        // host 回复的 id 可能匹配不上最新一轮，导致 initiated 永远为 false、握手永不完成。
        if (initId === null) initId = Date.now() + Math.floor(Math.random() * 1e5)
        send({ jsonrpc: "2.0", id: initId, method: "ui/initialize",
               params: { protocolVersion: "2025-06-18",
                         appInfo: { name: "step", version: "1.0.0" },
                         appCapabilities: {} } })
      }
      window.addEventListener("message", function (e) {
        var d = e.data
        if (!d || typeof d !== "object" || d.jsonrpc !== "2.0") return
        if (d.id != null && d.id === initId && !initiated) {
          initiated = true
          send({ jsonrpc: "2.0", method: "ui/notifications/initialized", params: {} })
          return
        }
        // 工具入参/结果也渲染进 #out，用于断言宿主透传（载荷均为 JSON 数据）。
        if (d.method === "ui/notifications/tool-input-partial" && d.params && d.params.arguments) {
          out.textContent = "input:" + JSON.stringify(d.params.arguments)
          return
        }
        if (d.method === "ui/notifications/tool-result" && d.params) {
          out.textContent = "result:" + (d.params.isError ? "error" : "ok")
          return
        }
        if (d.method === "notifications/progress" && d.params) render(d.params)
      })
      setInterval(tryHandshake, 300)
      tryHandshake()
    </script>
  </body>
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

    // 二级：两个 tool 子标签（工具名 + 调用序号）
    await expect(panel.getByRole("tab", { name: /step1 #1/ })).toBeVisible()
    await expect(panel.getByRole("tab", { name: /step2 #2/ })).toBeVisible()

    // 切换 sub-tab 更新激活态
    await panel.getByRole("tab", { name: /step2 #2/ }).click()
    await expect(panel.getByRole("tab", { name: /step2 #2/ })).toHaveAttribute("aria-selected", "true")
  })

  test("forwards running tool progress into the step-ui iframe", async ({ page }) => {
    await setupTimeline(page, {
      settings: { newLayoutDesigns: true },
      messages: [
        userMessage(),
        assistantMessage([
          toolPart("prt_skill_run", "skill", "completed", { name: "step-12" }),
          toolPart("prt_step1_run", "ui-server_step1", "running", { iterations: 5 }, {
            metadata: {
              mcp: { server: "ui-server", tool: "step1", ui: { resourceUri: "ui://step1/progress.html", visibility: ["model", "app"] } },
              mcpProgress: { progress: 3, total: 5, message: "步骤一 3/5" },
            },
          }),
        ]),
      ],
      mcpApps: stepMcpApps(["ui://step1/progress.html"]),
    })

    const panel = page.locator('[data-component="mcp-apps-panel"]')
    await expect(panel).toBeVisible()

    // 进度 UI iframe 挂载后，握手完成 -> host 冲刷待转发事件 -> 进度应渲染进 iframe。
    const iframe = panel.locator('iframe[sandbox="allow-scripts"]')
    await expect(iframe).toBeVisible()
    const frame = iframe.contentFrame()
    await expect(frame.getByText("步骤一 3/5")).toBeVisible()
  })

  test("forwards uiEvent extension data into the step-ui iframe", async ({ page }) => {
    page.on("console", (msg) => {
      if (msg.text().includes("[mcp-app]") || msg.text().includes("progress")) console.log("PAGE:", msg.text())
    })
    await setupTimeline(page, {
      settings: { newLayoutDesigns: true },
      messages: [
        userMessage(),
        assistantMessage([
          toolPart("prt_skill_topology", "skill", "completed", { name: "pfd-topology" }),
          toolPart("prt_topology_run", "ui-server_pfd_topology", "running", { pdf_path: "PFD.pdf" }, {
            metadata: {
              mcp: {
                server: "ui-server",
                tool: "pfd_topology",
                ui: { resourceUri: "ui://pfd-topology/review.html", visibility: ["model", "app"] },
              },
              mcpProgress: {
                progress: 0,
                total: 10,
                message: "PDF 解析完成，共 2 页",
                uiEvent: { event_type: "images_loaded", image_paths: ["page-0.png", "page-1.png"] },
              },
            },
          }),
        ]),
      ],
      mcpApps: stepMcpApps(["ui://pfd-topology/review.html"]),
    })

    const panel = page.locator('[data-component="mcp-apps-panel"]')
    await expect(panel).toBeVisible()

    // MCP server 通过 notifications/progress 携带的 uiEvent 扩展字段必须透传到 iframe，
    // step-ui 从 progress.uiEvent.event_type 读取并渲染（如 pfd_topology 的 images_loaded）。
    const iframe = panel.locator('iframe[sandbox="allow-scripts"]')
    await expect(iframe).toBeVisible()
    await page.waitForTimeout(3000)
    const frame = iframe.contentFrame()
    const body = await frame.locator("body").textContent().catch((e) => "ERR " + (e as Error).message)
    console.log("DEBUG iframe body=", body)
    await expect(frame.getByText("uiEvent:images_loaded")).toBeVisible()
  })

  test("forwards tool input arguments into the step-ui iframe", async ({ page }) => {
    await setupTimeline(page, {
      settings: { newLayoutDesigns: true },
      messages: [
        userMessage(),
        assistantMessage([
          toolPart("prt_skill_in", "skill", "completed", { name: "pfd-topology" }),
          toolPart("prt_in", "ui-server_pfd_topology", "running", { pdf_path: "PFD.pdf", dpi: 150 }, {
            metadata: {
              mcp: {
                server: "ui-server",
                tool: "pfd_topology",
                ui: { resourceUri: "ui://pfd-topology/review.html", visibility: ["model", "app"] },
              },
            },
          }),
        ]),
      ],
      mcpApps: stepMcpApps(["ui://pfd-topology/review.html"]),
    })

    const panel = page.locator('[data-component="mcp-apps-panel"]')
    await expect(panel).toBeVisible()

    // running 工具的入参经 ui/notifications/tool-input-partial 透传进 iframe，step-ui 渲染 arguments。
    const iframe = panel.locator('iframe[sandbox="allow-scripts"]')
    await expect(iframe).toBeVisible()
    const frame = iframe.contentFrame()
    await expect(frame.getByText('input:{"pdf_path":"PFD.pdf","dpi":150}')).toBeVisible()
  })

  test("forwards tool result into the step-ui iframe", async ({ page }) => {
    await setupTimeline(page, {
      settings: { newLayoutDesigns: true },
      messages: [
        userMessage(),
        assistantMessage([
          toolPart("prt_skill_res", "skill", "completed", { name: "pfd-topology" }),
          toolPart("prt_res", "ui-server_pfd_topology", "completed", { pdf_path: "PFD.pdf" }, {
            metadata: {
              mcp: {
                server: "ui-server",
                tool: "pfd_topology",
                ui: { resourceUri: "ui://pfd-topology/review.html", visibility: ["model", "app"] },
                result: { content: [{ type: "text", text: "done" }] },
              },
            },
          }),
        ]),
      ],
      mcpApps: stepMcpApps(["ui://pfd-topology/review.html"]),
    })

    const panel = page.locator('[data-component="mcp-apps-panel"]')
    await expect(panel).toBeVisible()

    // completed 工具的 metadata.mcp.result 经 ui/notifications/tool-result 透传进 iframe。
    const iframe = panel.locator('iframe[sandbox="allow-scripts"]')
    await expect(iframe).toBeVisible()
    const frame = iframe.contentFrame()
    await expect(frame.getByText("result:ok")).toBeVisible()
  })

  test("switches the panel tab to the newest tool when a new tool executes", async ({ page }) => {
    const timeline = await setupTimeline(page, {
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
        ]),
      ],
      mcpApps: stepMcpApps(["ui://step1/progress.html", "ui://step2/progress.html"]),
    })

    const panel = page.locator('[data-component="mcp-apps-panel"]')
    await expect(panel).toBeVisible()

    // 初始只有 step1：面板选中 step1 的 tab。
    await expect(panel.getByRole("tab", { name: /step1 #1/ })).toHaveAttribute(
      "aria-selected",
      "true",
    )

    // 新 tool（step2）执行完成 → 面板自动把 tab 焦点切换到 step2 的 UI。
    await timeline.send(
      partUpdated(
        toolPart("prt_step2", "ui-server_step2", "completed", {}, {
          metadata: {
            mcp: {
              server: "ui-server",
              tool: "step2",
              ui: { resourceUri: "ui://step2/progress.html", visibility: ["model", "app"] },
            },
          },
        }),
      ),
    )

    await expect(panel.getByRole("tab", { name: /step2 #2/ })).toHaveAttribute(
      "aria-selected",
      "true",
    )
  })

  test("reloads the app iframe when switching between tool tabs", async ({ page }) => {
    // step1 / step3 各自返回不同标识文本的 UI HTML，用于断言切换后 iframe 确实重新加载了对应资源。
    const stepOneHtml = STEP_UI_HTML.replace("<title>Step</title>", "<title>Step One</title>").replace(
      '<div id="out">就绪</div>',
      '<div id="out">Step One 就绪</div>',
    )
    const stepThreeHtml = STEP_UI_HTML.replace("<title>Step</title>", "<title>Step Three</title>").replace(
      '<div id="out">就绪</div>',
      '<div id="out">Step Three 就绪</div>',
    )

    await setupTimeline(page, {
      settings: { newLayoutDesigns: true },
      messages: [
        userMessage(),
        assistantMessage([
          toolPart("prt_skill_13", "skill", "completed", { name: "step-13" }),
          toolPart("prt_step1", "ui-server_step1", "completed", {}, {
            metadata: {
              mcp: {
                server: "ui-server",
                tool: "step1",
                ui: { resourceUri: "ui://step1/progress.html", visibility: ["model", "app"] },
              },
            },
          }),
          toolPart("prt_step3", "ui-server_step3", "completed", {}, {
            metadata: {
              mcp: {
                server: "ui-server",
                tool: "step3",
                ui: { resourceUri: "ui://step3/progress.html", visibility: ["model", "app"] },
              },
            },
          }),
        ]),
      ],
      mcpApps: {
        servers: [{ name: "ui-server" }],
        rpc: ({ method, params }: { method: string; params: { uri?: string } }) => {
          if (method === "initialize") {
            return {
              protocolVersion: "2025-06-18",
              capabilities: {},
              serverInfo: { name: "ui-server", version: "1.0.0" },
            }
          }
          if (method === "resources/read") {
            const uri = params.uri
            const text = uri === "ui://step1/progress.html" ? stepOneHtml : uri === "ui://step3/progress.html" ? stepThreeHtml : ""
            return { contents: [{ uri, mimeType: "text/html", text }] }
          }
          if (method === "tools/list") return { tools: [] }
          return { _meta: {} }
        },
      },
    })

    const panel = page.locator('[data-component="mcp-apps-panel"]')
    await expect(panel).toBeVisible()

    // 初始选中最新执行的 step3 → iframe 渲染 Step Three。
    await expect(panel.getByRole("tab", { name: /step3 #2/ })).toHaveAttribute("aria-selected", "true")
    const iframe = panel.locator('iframe[sandbox="allow-scripts"]')
    await expect(iframe.contentFrame().getByText("Step Three")).toBeVisible()

    // 切换到 step1 → iframe 必须重新加载出 Step One，而不是残留 Step Three 的 HTML。
    await panel.getByRole("tab", { name: /step1 #1/ }).click()
    await expect(iframe.contentFrame().getByText("Step One")).toBeVisible()
    await expect(iframe.contentFrame().getByText("Step Three")).not.toBeVisible()
  })

  test("replays persisted final progress after switching back to a tool tab", async ({ page }) => {
    await setupTimeline(page, {
      settings: { newLayoutDesigns: true },
      messages: [
        userMessage(),
        assistantMessage([
          toolPart("prt_skill_13", "skill", "completed", { name: "step-13" }),
          toolPart("prt_step1", "ui-server_step1", "completed", {}, {
            metadata: {
              mcp: {
                server: "ui-server",
                tool: "step1",
                ui: { resourceUri: "ui://step1/progress.html", visibility: ["model", "app"] },
              },
              mcpProgress: { progress: 5, total: 5, message: "步骤一：解析输入 5/5" },
            },
          }),
          toolPart("prt_step3", "ui-server_step3", "completed", {}, {
            metadata: {
              mcp: {
                server: "ui-server",
                tool: "step3",
                ui: { resourceUri: "ui://step3/progress.html", visibility: ["model", "app"] },
              },
              mcpProgress: { progress: 5, total: 5, message: "步骤三：结果汇总 5/5" },
            },
          }),
        ]),
      ],
      mcpApps: stepMcpApps(["ui://step1/progress.html", "ui://step3/progress.html"]),
    })

    const panel = page.locator('[data-component="mcp-apps-panel"]')
    await expect(panel).toBeVisible()

    // 初始选中最新执行的 step3：iframe 必须回放完成态持久化的最终进度。
    await expect(panel.getByRole("tab", { name: /step3 #2/ })).toHaveAttribute("aria-selected", "true")
    const iframe = panel.locator('iframe[sandbox="allow-scripts"]')
    await expect(iframe.contentFrame().getByText("步骤三：结果汇总 5/5")).toBeVisible()

    // 切回 step1 tab：iframe 重载后必须回放 step1 的最终进度，而非回退到 "就绪"。
    await panel.getByRole("tab", { name: /step1 #1/ }).click()
    await expect(iframe.contentFrame().getByText("步骤一：解析输入 5/5")).toBeVisible()
  })

  test("shows each call instance as its own tab with isolated progress", async ({ page }) => {
    await setupTimeline(page, {
      settings: { newLayoutDesigns: true },
      messages: [
        userMessage(),
        assistantMessage([
          toolPart("prt_skill_dup", "skill", "completed", { name: "step-12" }),
          toolPart("prt_step1_first", "ui-server_step1", "running", {}, {
            metadata: {
              mcp: { server: "ui-server", tool: "step1", ui: { resourceUri: "ui://step1/progress.html", visibility: ["model", "app"] } },
              mcpProgress: { progress: 2, total: 5, message: "首次调用 2/5" },
            },
          }),
          toolPart("prt_step1_second", "ui-server_step1", "running", {}, {
            metadata: {
              mcp: { server: "ui-server", tool: "step1", ui: { resourceUri: "ui://step1/progress.html", visibility: ["model", "app"] } },
              mcpProgress: { progress: 4, total: 5, message: "二次调用 4/5" },
            },
          }),
        ]),
      ],
      mcpApps: stepMcpApps(["ui://step1/progress.html"]),
    })

    const panel = page.locator('[data-component="mcp-apps-panel"]')
    await expect(panel).toBeVisible()

    // 同一 tool 两次调用 → 两个带序号的二级 tab（调用链）
    await expect(panel.getByRole("tab", { name: /step1 #1/ })).toBeVisible()
    await expect(panel.getByRole("tab", { name: /step1 #2/ })).toBeVisible()

    // 面板自动聚焦最新执行的实例（#2）：其 iframe 定格二次调用的进度（与 #1 隔离，互不串扰）。
    const iframe = panel.locator('iframe[sandbox="allow-scripts"]')
    await expect(iframe).toBeVisible()
    await expect(iframe.contentFrame().getByText("二次调用 4/5")).toBeVisible()

    // 切到第一个实例：同一 iframe 容器重注册为该实例 sink，回放首次调用的进度（隔离生效）。
    await panel.getByRole("tab", { name: /step1 #1/ }).click()
    await expect(iframe.contentFrame().getByText("首次调用 2/5")).toBeVisible()

    // 再切回第二个实例：进度互不串扰。
    await panel.getByRole("tab", { name: /step1 #2/ }).click()
    await expect(iframe.contentFrame().getByText("二次调用 4/5")).toBeVisible()
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