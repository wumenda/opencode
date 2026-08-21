/**
 * Minimal MCP Apps (SEP-1865) stdio server used as an end-to-end fixture.
 *
 * Run it as the `command` of a local MCP server entry (e.g. via bun):
 *
 * ```json
 * { "type": "local", "command": ["bun", "run", "test/mcp/fixtures/ui-server.ts"] }
 * ```
 *
 * Exposes:
 * - tool `show_dashboard` whose `_meta.ui.resourceUri` points at `ui://dashboard`;
 * - resource `ui://dashboard` returning a minimal HTML document with a button
 *   that calls `tools/list` through the app bridge to prove bidirectional comms.
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js"
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js"
import {
  CallToolRequestSchema,
  ListResourcesRequestSchema,
  ListToolsRequestSchema,
  ReadResourceRequestSchema,
} from "@modelcontextprotocol/sdk/types.js"

const HTML = `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Dashboard</title>
    <style>
      body { font-family: system-ui, sans-serif; padding: 16px; }
      button { padding: 8px 12px; }
      #out { margin-top: 12px; white-space: pre-wrap; font-size: 12px; }
    </style>
  </head>
  <body>
    <h1>Dashboard</h1>
    <button id="list">List tools</button>
    <pre id="out"></pre>
    <script src="https://modelcontextprotocol.io/ext-apps/client.js"></script>
    <script>
      const out = document.getElementById("out")
      document.getElementById("list").addEventListener("click", async () => {
        try {
          const res = await window.app.call("tools/list", {})
          out.textContent = JSON.stringify(res.result, null, 2)
        } catch (err) {
          out.textContent = "Error: " + err
        }
      })
    </script>
  </body>
</html>`

const DASHBOARD_URI = "ui://dashboard"

const server = new Server(
  { name: "ui-server", version: "1.0.0" },
  { capabilities: { tools: {}, resources: {} } },
)

server.setRequestHandler(ListToolsRequestSchema, () =>
  Promise.resolve({
    tools: [
      {
        name: "show_dashboard",
        description: "Show the dashboard app UI",
        inputSchema: { type: "object", properties: {}, additionalProperties: false },
        _meta: {
          ui: {
            resourceUri: DASHBOARD_URI,
            visibility: modelVisibility(),
          },
        },
      },
    ],
  }),
)

server.setRequestHandler(CallToolRequestSchema, (request) => {
  if (request.params.name !== "show_dashboard") {
    return Promise.resolve({
      content: [{ type: "text", text: `Unknown tool: ${request.params.name}` }],
      isError: true,
    })
  }
  return Promise.resolve({
    content: [{ type: "text", text: "Dashboard rendered." }],
    _meta: { ui: { resourceUri: DASHBOARD_URI } },
  })
})

server.setRequestHandler(ListResourcesRequestSchema, () =>
  Promise.resolve({ resources: [{ uri: DASHBOARD_URI, name: "Dashboard", mimeType: "text/html" }] }),
)

server.setRequestHandler(ReadResourceRequestSchema, (request) => {
  if (request.params.uri !== DASHBOARD_URI) {
    return Promise.reject(new Error(`Unknown resource: ${request.params.uri}`))
  }
  return Promise.resolve({ contents: [{ uri: DASHBOARD_URI, mimeType: "text/html", text: HTML }] })
})

await server.connect(new StdioServerTransport())

function modelVisibility() {
  // Both model and app by default; toggle to ["app"] to keep the tool out of the
  // agent's tool list and render it only as inline app UI.
  return ["model", "app"]
}