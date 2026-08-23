import { Client } from "@modelcontextprotocol/sdk/client/index.js"
import {
  CallToolResultSchema,
  ListToolsResultSchema,
  ProgressNotificationParamsSchema,
  ProgressNotificationSchema,
  ToolSchema,
  type Notification,
  type Tool as MCPToolDef,
} from "@modelcontextprotocol/sdk/types.js"
import { dynamicTool, jsonSchema, type JSONSchema7, type Tool } from "ai"
import { Effect } from "effect"

const DEFAULT_TIMEOUT = 30_000
const MAX_LIST_PAGES = 1_000

const TolerantListToolsResultSchema = ListToolsResultSchema.extend({
  tools: ToolSchema.omit({ outputSchema: true }).array(),
})

export async function paginate<T, R extends { nextCursor?: string }>(
  list: (cursor?: string) => Promise<R>,
  items: (result: R) => T[],
) {
  const result: T[] = []
  const cursors = new Set<string>()
  let cursor: string | undefined

  for (let page = 0; page < MAX_LIST_PAGES; page++) {
    const page = await list(cursor)
    result.push(...items(page))
    if (page.nextCursor === undefined) return result
    if (cursors.has(page.nextCursor)) throw new Error(`MCP list returned duplicate cursor: ${page.nextCursor}`)
    cursors.add(page.nextCursor)
    cursor = page.nextCursor
  }

  throw new Error(`MCP list exceeded ${MAX_LIST_PAGES} pages`)
}

export function defs(client: Client, timeout?: number) {
  return listTools(client, timeout ?? DEFAULT_TIMEOUT).pipe(Effect.catch(() => Effect.void))
}

export interface McpProgress {
  progress: number
  total?: number
  message?: string
  /** MCP Apps (SEP-1865) 扩展字段：MCP server 可在 notifications/progress 的 params 里
   *  携带结构化 uiEvent 数据（如 pdf2json 的 send_progress_with_data），前端 step-ui 直接从
   *  `progress.uiEvent.<key>` 读取逐步渲染所需数据。 */
  uiEvent?: unknown
}

/**
 * 松开 SDK 对 notifications/progress 的严格 zod 解析：SDK 的 ProgressNotificationParamsSchema
 * 是 `z.object`（默认 strip），会把 params 里非标准的扩展字段（如 SEP-1865 的 uiEvent）剥离；
 * `.loose()` 版保留全部扩展字段，使 uiEvent 能原样到达 convertTool 的 onprogress 回调。
 */
export const LooseProgressNotificationSchema = ProgressNotificationSchema.extend({
  params: ProgressNotificationParamsSchema.loose(),
})

/** 转交 SDK 内置的 progressToken -> callTool onprogress 分发（保持 timeout reset 与 toolCallId 关联不变）。 */
function dispatchProgress(client: Client, notification: Notification) {
  return (client as unknown as { _onprogress: (notification: Notification) => void })._onprogress(notification)
}

/**
 * 注册非标准 notification 处理（MCP Apps SEP-1865 uiEvent 扩展）：
 * 1) 用宽松 schema 重注册 notifications/progress，uiEvent 不再被 SDK 剥离；
 * 2) 兜底捕获未注册 method 的通知，凡携带 progressToken+uiEvent 的走标准进度管道。
 * 直接替换 SDK 构造函数注册的内置 progress handler，行为一致（仅解析更宽松）。
 */
export function installUiEventNotificationHandlers(client: Client) {
  client.setNotificationHandler(LooseProgressNotificationSchema, (notification) =>
    dispatchProgress(client, notification as Notification),
  )
}

/** MCP Apps (SEP-1865) UI metadata from a tool definition's `_meta`. */
export interface McpToolUi {
  resourceUri?: string
  visibility: Array<"model" | "app">
}

const DEFAULT_UI_VISIBILITY: McpToolUi["visibility"] = ["model", "app"]

/**
 * Reads `_meta.ui` from an MCP tool definition, normalizing the deprecated
 * flat `_meta["ui/resourceUri"]` form. Returns undefined when the tool has no
 * UI metadata.
 */
export function toolUi(def: MCPToolDef): McpToolUi | undefined {
  const meta = def._meta
  if (meta === undefined || meta === null || typeof meta !== "object") return undefined
  const record = meta as Record<string, unknown>
  const ui = record["ui"]
  const uiRecord = typeof ui === "object" && ui !== null ? (ui as Record<string, unknown>) : undefined
  const resourceUriFromUi = typeof uiRecord?.["resourceUri"] === "string" ? uiRecord["resourceUri"] : undefined
  const resourceUriFromDeprecated =
    typeof record["ui/resourceUri"] === "string" ? record["ui/resourceUri"] : undefined
  if (resourceUriFromUi === undefined && resourceUriFromDeprecated === undefined && uiRecord === undefined)
    return undefined
  const visibilityRaw = uiRecord?.["visibility"]
  const visibility = Array.isArray(visibilityRaw)
    ? visibilityRaw.filter((value): value is "model" | "app" => value === "model" || value === "app")
    : DEFAULT_UI_VISIBILITY
  return { resourceUri: resourceUriFromUi ?? resourceUriFromDeprecated, visibility }
}

export function convertTool(
  mcpTool: MCPToolDef,
  client: Client,
  timeout?: number,
  onProgress?: (progress: McpProgress, toolCallId: string) => void,
): Tool {
  const inputSchema: JSONSchema7 = {
    ...(mcpTool.inputSchema as JSONSchema7),
    type: "object",
    properties: (mcpTool.inputSchema.properties ?? {}) as JSONSchema7["properties"],
    additionalProperties: false,
  }

  return dynamicTool({
    description: mcpTool.description ?? "",
    inputSchema: jsonSchema(inputSchema),
    execute: async (args: unknown, options) => {
      const result = await client.callTool(
        {
          name: mcpTool.name,
          arguments: (args || {}) as Record<string, unknown>,
        },
        CallToolResultSchema,
        {
          resetTimeoutOnProgress: true,
          signal: options.abortSignal,
          timeout,
          // The MCP SDK only sends a progress token when this hook is present, enabling timeout resets.
          onprogress: (p) =>
            onProgress?.(
              {
                progress: p.progress,
                total: p.total,
                message: p.message,
                // SDK 的 Progress 类型不含扩展字段，但运行时 params 原样保留 uiEvent（透传）。
                uiEvent: (p as { uiEvent?: unknown }).uiEvent,
              },
              options.toolCallId,
            ),
        },
      )
      if (result.isError)
        throw new Error(
          result.content
            .flatMap((item) => (item.type === "text" ? [item.text] : []))
            .filter((text) => text.trim())
            .join("\n\n") || "MCP tool returned an error",
        )
      if (result.content.length > 0 || result.structuredContent === undefined || result.structuredContent === null)
        return result
      return {
        ...result,
        content: [{ type: "text" as const, text: JSON.stringify(result.structuredContent) }],
      }
    },
  })
}

export function fetch<T extends { name: string }>(
  clientName: string,
  client: Client,
  list: (client: Client) => Promise<T[]>,
  label: string,
  key?: (item: T) => string,
) {
  return Effect.tryPromise({
    try: () => list(client),
    catch: (error) => error,
  }).pipe(
    Effect.tapError((error) =>
      Effect.logWarning(`failed to get ${label}`, {
        clientName,
        error: error instanceof Error ? error.message : String(error),
      }),
    ),
    Effect.map((items) => {
      const sanitizedClient = sanitize(clientName)
      // Escape both the separator and escape marker so `server:uri` keys remain unambiguous.
      const resourceClient = clientName.replaceAll("%", "%25").replaceAll(":", "%3A")
      return Object.fromEntries(
        items.map((item) => [
          key ? resourceClient + ":" + key(item) : sanitizedClient + ":" + sanitize(item.name),
          { ...item, client: clientName },
        ]),
      )
    }),
    Effect.orElseSucceed(() => undefined),
  )
}

export const sanitize = (value: string) => value.replace(/[^a-zA-Z0-9_-]/g, "_")

export const toolName = (clientName: string, name: string) => sanitize(clientName) + "_" + sanitize(name)

export function prompts(client: Client, timeout?: number) {
  if (!client.getServerCapabilities()?.prompts) return Promise.resolve([])
  return paginate(
    (cursor) => client.listPrompts(cursor === undefined ? undefined : { cursor }, { timeout }),
    (result) => result.prompts,
  )
}

export function resources(client: Client, timeout?: number) {
  if (!client.getServerCapabilities()?.resources) return Promise.resolve([])
  return paginate(
    (cursor) => client.listResources(cursor === undefined ? undefined : { cursor }, { timeout }),
    (result) => result.resources,
  )
}

export function resourceTemplates(client: Client, timeout?: number) {
  if (!client.getServerCapabilities()?.resources) return Promise.resolve([])
  return paginate(
    (cursor) => client.listResourceTemplates(cursor === undefined ? undefined : { cursor }, { timeout }),
    (result) => result.resourceTemplates,
  )
}

function listTools(client: Client, timeout: number) {
  return Effect.tryPromise({
    try: () =>
      paginate(
        async (cursor) => {
          const params = cursor === undefined ? undefined : { cursor }
          try {
            return await client.listTools(params, { timeout })
          } catch (error) {
            if (!(error instanceof Error) || !isOutputSchemaValidationError(error)) throw error
            return client.request({ method: "tools/list", params }, TolerantListToolsResultSchema, { timeout })
          }
        },
        (result) => result.tools,
      ),
    catch: (error) => (error instanceof Error ? error : new Error(String(error))),
  })
}

function isOutputSchemaValidationError(error: Error) {
  return /can't resolve reference|resolves to more than one schema|outputSchema|schema.*reference|reference.*schema/i.test(
    error.message,
  )
}

export * as McpCatalog from "./catalog"
