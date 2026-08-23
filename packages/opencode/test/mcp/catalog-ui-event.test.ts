import { describe, expect, test } from "bun:test"
import { Client } from "@modelcontextprotocol/sdk/client/index.js"
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js"
import { Server } from "@modelcontextprotocol/sdk/server/index.js"
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js"
import { McpCatalog } from "@/mcp/catalog"

const options = { toolCallId: "call_step", abortSignal: new AbortController().signal } as any

/** 构造一个在工具执行中发送带 uiEvent 扩展字段的 progress 通知的 MCP server。 */
function uiEventServer(method: string) {
  const server = new Server({ name: "ui-event-server", version: "1.0.0" }, { capabilities: { tools: {} } })
  server.setRequestHandler(ListToolsRequestSchema, () =>
    Promise.resolve({
      tools: [{ name: "step", description: "step", inputSchema: { type: "object", properties: {} } }],
    }),
  )
  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const token = request.params._meta?.progressToken
    if (token !== undefined) {
      await server.notification({
        method,
        params: {
          progressToken: token,
          progress: 1,
          total: 2,
          message: "working",
          uiEvent: { event_type: "images_loaded", image_paths: ["a.png"] },
        },
      })
    }
    return { content: [{ type: "text", text: "done" }] }
  })
  return server
}

async function run(method: string) {
  const server = uiEventServer(method)
  const client = new Client({ name: "test", version: "1.0.0" })
  McpCatalog.installUiEventNotificationHandlers(client)
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair()
  await Promise.all([client.connect(clientTransport), server.connect(serverTransport)])

  const received: McpCatalog.McpProgress[] = []
  const tool = McpCatalog.convertTool(
    { name: "step", description: "", inputSchema: { type: "object", properties: {} } } as any,
    client,
    undefined,
    (progress) => received.push(progress),
  )
  await tool.execute?.({}, options)

  await Promise.all([client.close(), server.close()])
  return received
}

describe("MCP non-standard uiEvent notifications", () => {
  test("preserves uiEvent from notifications/progress instead of stripping it", async () => {
    const received = await run("notifications/progress")
    expect(received).toHaveLength(1)
    expect(received[0]).toMatchObject({ progress: 1, total: 2, message: "working" })
    expect(received[0].uiEvent).toEqual({ event_type: "images_loaded", image_paths: ["a.png"] })
  })

  test("routes uiEvent-carrying custom notification methods through the progress pipeline", async () => {
    const received = await run("ui/notifications/step-update")
    expect(received).toHaveLength(1)
    expect(received[0]).toMatchObject({ progress: 1, total: 2, message: "working" })
    expect(received[0].uiEvent).toEqual({ event_type: "images_loaded", image_paths: ["a.png"] })
  })
})
