import type { Transport, TransportSendOptions } from "@modelcontextprotocol/sdk/shared/transport.js"
import type {
  JSONRPCMessage,
  JSONRPCNotification,
  JSONRPCRequest,
  JSONRPCResponse,
  RequestId,
} from "@modelcontextprotocol/sdk/types.js"

type FetchLike = (url: string | URL, init?: RequestInit) => Promise<Response>

export type HttpRpcTransportOptions = {
  /** MCP server configuration name, must already be connected on the host. */
  readonly server: string
  /** Base URL of the opencode server, e.g. "http://localhost:4096". */
  readonly baseUrl: string

  /** Optional workspace directory for instance routing. */
  readonly directory?: string
  /** Extra headers (e.g. Authorization) attached to every RPC call. */
  readonly headers?: Record<string, string>
  /** Fetch implementation, tests inject a stub here. */
  readonly fetchFn?: FetchLike
}

// JSON-RPC server error reserved for implementation-defined failures.
const SERVER_ERROR = -32000

/**
 * Bridges the browser-side MCP Client onto the host's JSON-RPC relay endpoint
 * `POST /api/mcp/:name/rpc`. The relay answers with the bare JSON-RPC result,
 * so responses are re-wrapped into full JSON-RPC response messages before
 * being handed to the client. Notifications are fire-and-forget: the relay
 * may reject them with 400 and the client never expects a reply.
 */
export class HttpRpcTransport implements Transport {
  onclose?: () => void
  onerror?: (error: Error) => void
  onmessage?: (message: JSONRPCMessage) => void

  private readonly url: string
  private readonly fetchFn: FetchLike
  private readonly headers: Record<string, string>
  private started = false
  private closed = false

  constructor(options: HttpRpcTransportOptions) {
    const url = new URL(`/api/mcp/${encodeURIComponent(options.server)}/rpc`, options.baseUrl)
    if (options.directory) url.searchParams.set("directory", options.directory)
    this.url = url.toString()
    this.fetchFn = options.fetchFn ?? globalThis.fetch
    this.headers = { "content-type": "application/json", ...options.headers }
  }

  async start() {
    if (this.closed) throw new Error("HttpRpcTransport already closed")
    if (this.started) throw new Error("HttpRpcTransport already started")
    this.started = true
  }

  async send(message: JSONRPCMessage, _options?: TransportSendOptions) {
    if (this.closed) throw new Error("HttpRpcTransport is closed")
    if (!this.started) throw new Error("HttpRpcTransport not started")
    // Responses to server-initiated requests never occur over this relay.
    if (!("method" in message)) return
    if (!("id" in message)) {
      void this.post(message).catch((error) => this.onerror?.(asError(error)))
      return
    }
    let response: Response
    try {
      response = await this.post(message)
    } catch (error) {
      const err = asError(error)
      this.onerror?.(err)
      throw err
    }
    this.onmessage?.(await toResponse(message.id, response))
  }

  async close() {
    if (this.closed) return
    this.closed = true
    this.onclose?.()
  }

  private post(message: JSONRPCRequest | JSONRPCNotification) {
    return this.fetchFn(this.url, {
      method: "POST",
      headers: this.headers,
      body: JSON.stringify({ method: message.method, params: message.params }),
    })
  }
}

function asError(error: unknown) {
  return error instanceof Error ? error : new Error(String(error))
}

async function toResponse(id: RequestId, response: Response): Promise<JSONRPCResponse> {
  const body = await response.json().catch(() => undefined)
  if (response.ok) return { jsonrpc: "2.0", id, result: body }
  const record = (body ?? {}) as { message?: unknown; data?: { message?: unknown } }
  const message =
    (typeof record.data?.message === "string" && record.data.message) ||
    (typeof record.message === "string" && record.message) ||
    response.statusText ||
    `HTTP ${response.status}`
  return { jsonrpc: "2.0", id, error: { code: SERVER_ERROR, message } }
}
