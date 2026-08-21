import { describe, expect, test } from "bun:test"
import { HttpRpcTransport } from "./http-rpc-transport"

type FetchLike = (url: string | URL, init?: RequestInit) => Promise<Response>

function setup(options?: { status?: number; body?: unknown }) {
  const requests: Request[] = []
  const fetchFn: FetchLike = async (input, init) => {
    const request = new Request(input, init)
    requests.push(request)
    return new Response(JSON.stringify(options?.body ?? {}), {
      status: options?.status ?? 200,
      headers: { "content-type": "application/json" },
    })
  }
  return { requests, fetchFn }
}

function makeTransport(overrides?: Partial<ConstructorParameters<typeof HttpRpcTransport>[0]>) {
  return new HttpRpcTransport({
    server: "weather",
    baseUrl: "http://localhost:4096",
    fetchFn: overrides?.fetchFn,
    ...overrides,
  })
}

describe("HttpRpcTransport", () => {
  test("sends JSON-RPC requests to POST /api/mcp/:name/rpc with {method, params} body", async () => {
    const { requests, fetchFn } = setup({ body: { protocolVersion: "2025-06-18", capabilities: {} } })
    const transport = makeTransport({ fetchFn })
    const received: unknown[] = []
    transport.onmessage = (message) => received.push(message)
    await transport.start()

    await transport.send({ jsonrpc: "2.0", id: 1, method: "initialize", params: { clientInfo: { name: "app", version: "1" } } })

    expect(requests.length).toBe(1)
    const request = requests[0]!
    expect(request.method).toBe("POST")
    expect(new URL(request.url).pathname).toBe("/api/mcp/weather/rpc")
    expect(request.headers.get("content-type")).toBe("application/json")
    expect(await request.json()).toEqual({
      method: "initialize",
      params: { clientInfo: { name: "app", version: "1" } },
    })
    expect(received).toEqual([{ jsonrpc: "2.0", id: 1, result: { protocolVersion: "2025-06-18", capabilities: {} } }])
  })

  test("wraps HTTP error responses as JSON-RPC errors", async () => {
    const { fetchFn } = setup({ status: 400, body: { name: "McpRpcError", data: { message: "Unsupported MCP method: foo" } } })
    const transport = makeTransport({ fetchFn })
    const received: unknown[] = []
    transport.onmessage = (message) => received.push(message)
    await transport.start()

    await transport.send({ jsonrpc: "2.0", id: 2, method: "foo" })

    expect(received).toEqual([{ jsonrpc: "2.0", id: 2, error: { code: -32000, message: "Unsupported MCP method: foo" } }])
  })

  test("falls back to status text when the error body carries no message", async () => {
    const { fetchFn } = setup({ status: 404, body: { name: "McpServerNotFoundError", data: { name: "weather" } } })
    const transport = makeTransport({ fetchFn })
    const received: unknown[] = []
    transport.onmessage = (message) => received.push(message)
    await transport.start()

    await transport.send({ jsonrpc: "2.0", id: 3, method: "ping" })

    const error = (received[0] as { error: { code: number; message: string } }).error
    expect(error.code).toBe(-32000)
    expect(error.message.length).toBeGreaterThan(0)
  })

  test("fire-and-forwards notifications without waiting or triggering onmessage", async () => {
    let release: (() => void) | undefined
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    const requests: Request[] = []
    const fetchFn: FetchLike = async (input, init) => {
      const request = new Request(input, init)
      requests.push(request)
      await gate
      return new Response("{}", { status: 200 })
    }
    const transport = makeTransport({ fetchFn })
    const received: unknown[] = []
    transport.onmessage = (message) => received.push(message)
    await transport.start()

    await transport.send({ jsonrpc: "2.0", method: "notifications/initialized" })

    expect(requests.length).toBe(1)
    expect(await requests[0]!.json()).toEqual({ method: "notifications/initialized", params: undefined })
    expect(received).toEqual([])
    release!()
  })

  test("stops sending after close() and reports onclose", async () => {
    const { requests, fetchFn } = setup()
    const transport = makeTransport({ fetchFn })
    let closed = 0
    transport.onclose = () => closed++
    await transport.start()
    await transport.close()

    expect(closed).toBe(1)
    await expect(transport.send({ jsonrpc: "2.0", id: 4, method: "ping" })).rejects.toThrow()
    expect(requests.length).toBe(0)
  })

  test("rejects send() and reports onerror when fetch fails", async () => {
    const fetchFn: FetchLike = async () => {
      throw new Error("network down")
    }
    const transport = makeTransport({ fetchFn })
    const errors: Error[] = []
    transport.onerror = (error) => errors.push(error)
    await transport.start()

    await expect(transport.send({ jsonrpc: "2.0", id: 5, method: "ping" })).rejects.toThrow("network down")
    expect(errors.length).toBe(1)
    expect(errors[0]!.message).toBe("network down")
  })

  test("appends the directory query param and forwards auth headers", async () => {
    const { requests, fetchFn } = setup()
    const transport = new HttpRpcTransport({
      server: "weather",
      baseUrl: "http://localhost:4096",
      directory: "/repo",
      headers: { authorization: "Basic dXNlcjpwYXNz" },
      fetchFn,
    })
    await transport.start()

    await transport.send({ jsonrpc: "2.0", id: 6, method: "ping" })

    const url = new URL(requests[0]!.url)
    expect(url.searchParams.get("directory")).toBe("/repo")
    expect(requests[0]!.headers.get("authorization")).toBe("Basic dXNlcjpwYXNz")
  })

  test("rejects double start", async () => {
    const { fetchFn } = setup()
    const transport = makeTransport({ fetchFn })
    await transport.start()
    await expect(transport.start()).rejects.toThrow()
  })
})
