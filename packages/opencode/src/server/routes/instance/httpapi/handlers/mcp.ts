import { MCP } from "@/mcp"
import type { Client as MCPClient } from "@modelcontextprotocol/sdk/client/index.js"
import {
  LATEST_PROTOCOL_VERSION,
  type CallToolRequest,
  type CreateMessageRequest,
  CreateMessageResultSchema,
  type GetPromptRequest,
  type ListPromptsRequest,
  type ListResourceTemplatesRequest,
  type ListResourcesRequest,
  type ListToolsRequest,
  type ReadResourceRequest,
} from "@modelcontextprotocol/sdk/types.js"
import { Effect, Schema } from "effect"
import { HttpApiBuilder, HttpApiError } from "effect/unstable/httpapi"
import { InstanceHttpApi } from "../api"
import { McpServerNotFoundError } from "../errors"
import { AddPayload, AuthCallbackPayload, McpRpcError, RpcPayload, StatusMap, UnsupportedOAuthError } from "../groups/mcp"

export const mcpHandlers = HttpApiBuilder.group(InstanceHttpApi, "mcp", (handlers) =>
  Effect.gen(function* () {
    const mcp = yield* MCP.Service

    const status = Effect.fn("McpHttpApi.status")(function* () {
      return yield* mcp.status()
    })

    const add = Effect.fn("McpHttpApi.add")(function* (ctx: { payload: typeof AddPayload.Type }) {
      const result = (yield* mcp.add(ctx.payload.name, ctx.payload.config)).status
      return yield* Schema.decodeUnknownEffect(StatusMap)(
        "status" in result ? { [ctx.payload.name]: result } : result,
      ).pipe(Effect.mapError(() => new HttpApiError.BadRequest({})))
    })

    const authStart = Effect.fn("McpHttpApi.authStart")(function* (ctx: { params: { name: string } }) {
      return yield* Effect.gen(function* () {
        if (!(yield* mcp.supportsOAuth(ctx.params.name))) {
          return yield* new UnsupportedOAuthError({ error: `MCP server ${ctx.params.name} does not support OAuth` })
        }
        return yield* mcp.startAuth(ctx.params.name)
      }).pipe(
        Effect.catchTag("MCP.NotFoundError", (error) =>
          Effect.fail(new McpServerNotFoundError({ name: error.name, message: `MCP server not found: ${error.name}` })),
        ),
      )
    })

    const authCallback = Effect.fn("McpHttpApi.authCallback")(function* (ctx: {
      params: { name: string }
      payload: typeof AuthCallbackPayload.Type
    }) {
      return yield* mcp
        .finishAuth(ctx.params.name, ctx.payload.code)
        .pipe(
          Effect.catchTag("MCP.NotFoundError", (error) =>
            Effect.fail(
              new McpServerNotFoundError({ name: error.name, message: `MCP server not found: ${error.name}` }),
            ),
          ),
        )
    })

    const authAuthenticate = Effect.fn("McpHttpApi.authAuthenticate")(function* (ctx: { params: { name: string } }) {
      return yield* Effect.gen(function* () {
        if (!(yield* mcp.supportsOAuth(ctx.params.name))) {
          return yield* new UnsupportedOAuthError({ error: `MCP server ${ctx.params.name} does not support OAuth` })
        }
        return yield* mcp.authenticate(ctx.params.name)
      }).pipe(
        Effect.catchTag("MCP.NotFoundError", (error) =>
          Effect.fail(new McpServerNotFoundError({ name: error.name, message: `MCP server not found: ${error.name}` })),
        ),
      )
    })

    const authRemove = Effect.fn("McpHttpApi.authRemove")(function* (ctx: { params: { name: string } }) {
      const status = yield* mcp.status()
      if (!(ctx.params.name in status))
        return yield* new McpServerNotFoundError({
          name: ctx.params.name,
          message: `MCP server not found: ${ctx.params.name}`,
        })
      yield* mcp.removeAuth(ctx.params.name)
      return { success: true as const }
    })

    const connect = Effect.fn("McpHttpApi.connect")(function* (ctx: { params: { name: string } }) {
      yield* mcp
        .connect(ctx.params.name)
        .pipe(
          Effect.catchTag("MCP.NotFoundError", (error) =>
            Effect.fail(
              new McpServerNotFoundError({ name: error.name, message: `MCP server not found: ${error.name}` }),
            ),
          ),
        )
      return true
    })

    const disconnect = Effect.fn("McpHttpApi.disconnect")(function* (ctx: { params: { name: string } }) {
      yield* mcp
        .disconnect(ctx.params.name)
        .pipe(
          Effect.catchTag("MCP.NotFoundError", (error) =>
            Effect.fail(
              new McpServerNotFoundError({ name: error.name, message: `MCP server not found: ${error.name}` }),
            ),
          ),
        )
      return true
    })

    const rpc = Effect.fn("McpHttpApi.rpc")(function* (ctx: {
      params: { name: string }
      payload: typeof RpcPayload.Type
    }) {
      const clients = yield* mcp.clients()
      const client = clients[ctx.params.name]
      if (!client)
        return yield* new McpServerNotFoundError({
          name: ctx.params.name,
          message: `MCP server not found: ${ctx.params.name}`,
        })
      const call = rpcCall(client, ctx.payload.method, ctx.payload.params)
      if (!call) return yield* new McpRpcError({ message: `Unsupported MCP method: ${ctx.payload.method}` })
      return yield* Effect.tryPromise({
        try: call,
        catch: (error) => new McpRpcError({ message: error instanceof Error ? error.message : String(error) }),
      })
    })

    return handlers
      .handle("status", status)
      .handle("add", add)
      .handle("authStart", authStart)
      .handle("authCallback", authCallback)
      .handle("authAuthenticate", authAuthenticate)
      .handle("authRemove", authRemove)
      .handle("connect", connect)
      .handle("disconnect", disconnect)
      .handle("rpc", rpc)
  }),
)

/**
 * Maps a JSON-RPC style MCP method onto the already-connected server client.
 * Returns undefined for methods the host does not relay.
 */
function rpcCall(
  client: MCPClient,
  method: string,
  params: unknown,
): (() => Promise<unknown>) | undefined {
  const p = (params ?? {}) as Record<string, unknown>
  switch (method) {
    case "initialize":
      return () => {
        const instructions = client.getInstructions()
        const base = {
          protocolVersion: LATEST_PROTOCOL_VERSION,
          capabilities: client.getServerCapabilities() ?? {},
          serverInfo: client.getServerVersion() ?? { name: "unknown", version: "0.0.0" },
        }
        // The relay's HttpApi encodes responses with Schema.Unknown, which cannot
        // serialize `undefined`; omit instructions when the server did not provide it.
        return instructions === undefined
          ? Promise.resolve(base)
          : Promise.resolve({ ...base, instructions })
      }
    case "ping":
      return () => Promise.resolve({})
    case "tools/list":
      return () => client.listTools(p as ListToolsRequest["params"])
    case "tools/call":
      return () => client.callTool(p as CallToolRequest["params"])
    case "resources/list":
      return () => client.listResources(p as ListResourcesRequest["params"])
    case "resources/read":
      return () => client.readResource(p as ReadResourceRequest["params"])
    case "resources/templates/list":
      return () => client.listResourceTemplates(p as ListResourceTemplatesRequest["params"])
    case "prompts/list":
      return () => client.listPrompts(p as ListPromptsRequest["params"])
    case "prompts/get":
      return () => client.getPrompt(p as GetPromptRequest["params"])
    case "sampling/createMessage":
      // The SDK Client exposes no high-level createMessage(); issue a raw
      // request and validate the response against CreateMessageResultSchema.
      return () =>
        client.request(
          { method: "sampling/createMessage", params: p as CreateMessageRequest["params"] },
          CreateMessageResultSchema,
        )
  }
  return undefined
}
