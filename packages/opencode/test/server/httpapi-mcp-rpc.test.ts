import { describe, expect } from "bun:test"
import { Server } from "@modelcontextprotocol/sdk/server/index.js"
import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js"
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  ReadResourceRequestSchema,
} from "@modelcontextprotocol/sdk/types.js"
import { Context, Effect, Layer } from "effect"
import { HttpApiApp } from "../../src/server/routes/instance/httpapi/server"
import { resetDatabase } from "../fixture/db"
import { TestInstance } from "../fixture/fixture"
import { testEffect } from "../lib/effect"

const context = Context.empty() as Context.Context<unknown>
const testStateLayer = Layer.effectDiscard(
  Effect.gen(function* () {
    yield* Effect.promise(() => resetDatabase())
    yield* Effect.addFinalizer(() => Effect.promise(() => resetDatabase()).pipe(Effect.ignore))
  }),
)
const it = testEffect(testStateLayer)

const request = Effect.fnUntraced(function* (route: string, directory: string, init?: RequestInit) {
  const headers = new Headers(init?.headers)
  headers.set("x-opencode-directory", directory)
  const handler = HttpApiApp.webHandler()
  return yield* Effect.promise(() =>
    Promise.resolve(
      handler.handler(new Request(`http://localhost${route}`, { ...init, headers }), context),
    ),
  )
})

const json = <A>(response: Response) => Effect.promise(() => response.json() as Promise<A>)

const serve = Effect.acquireRelease(
  Effect.promise(async () => {
    const protocol = new Server(
      { name: "ui-server", version: "1.0.0" },
      { capabilities: { tools: {}, resources: {} } },
    )
    protocol.setRequestHandler(ListToolsRequestSchema, () =>
      Promise.resolve({
        tools: [
          {
            name: "show_dashboard",
            description: "Show dashboard",
            inputSchema: { type: "object", properties: {} },
          },
        ],
      }),
    )
    protocol.setRequestHandler(CallToolRequestSchema, () =>
      Promise.resolve({ content: [{ type: "text", text: "dashboard ok" }] }),
    )
    protocol.setRequestHandler(ReadResourceRequestSchema, () =>
      Promise.resolve({ contents: [{ uri: "ui://dashboard", text: "<html/>" }] }),
    )

    const transport = new WebStandardStreamableHTTPServerTransport({
      sessionIdGenerator: () => crypto.randomUUID(),
      enableJsonResponse: true,
    })
    await protocol.connect(transport)
    const http = Bun.serve({
      port: 0,
      fetch(request) {
        return transport.handleRequest(request)
      },
    })
    return {
      url: http.url.toString(),
      close: async () => {
        await http.stop(true)
        await protocol.close()
      },
    }
  }),
  (server) => Effect.promise(server.close),
)

describe("mcp rpc endpoint", () => {
  it.instance(
    "relays an MCP method to a connected server and returns 200 for known methods, 400 for unsupported, 404 for missing",
    () =>
      Effect.gen(function* () {
        const server = yield* serve
        const tmp = yield* TestInstance
        const dir = tmp.directory

        // Add a remote server (auto-connects) so a client exists in mcp.clients().
        const added = yield* request("/mcp", dir, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ name: "ui", config: { type: "remote", url: server.url } }),
        })
        expect(added.status).toBe(200)

        // Known method → forwarded result.
        const list = yield* request("/mcp/ui/rpc", dir, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ method: "tools/list" }),
        })
        expect(list.status).toBe(200)
        expect(yield* json(list)).toMatchObject({
          tools: [{ name: "show_dashboard" }],
        })

        // Unsupported method → 400.
        const unsupported = yield* request("/mcp/ui/rpc", dir, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ method: "resources/subscribe" }),
        })
        expect(unsupported.status).toBe(400)
        expect(yield* json(unsupported)).toEqual({ message: "Unsupported MCP method: resources/subscribe" })

        // Missing server → 404.
        const missing = yield* request("/mcp/nope/rpc", dir, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ method: "ping" }),
        })
        expect(missing.status).toBe(404)
        expect(yield* json(missing)).toEqual({
          _tag: "McpServerNotFoundError",
          name: "nope",
          message: "MCP server not found: nope",
        })
      }),
    { config: { mcp: {} } },
  )
})