import { describe, expect, test } from "bun:test"
import { Client } from "@modelcontextprotocol/sdk/client/index.js"
import { HttpRpcTransport } from "./http-rpc-transport"
import { buildSandboxedHtml, injectCsp, readUiResource } from "./resource"

/** Builds a real MCP Client wired to a mock relay, mirroring the McpAppView flow. */
async function setupClient(resourcesReadResult: unknown) {
  const calls: Array<{ method: string; params: unknown }> = []
  const fetchFn = async (input: string | URL, init?: RequestInit) => {
    const body = (await new Request(input, init).json()) as {
      method: string
      params?: { protocolVersion?: string }
    }
    calls.push(body)
    if (body.method === "initialize") {
      return Response.json({
        protocolVersion: body.params?.protocolVersion,
        capabilities: { resources: {} },
        serverInfo: { name: "ui-server", version: "1.0.0" },
      })
    }
    return Response.json(resourcesReadResult)
  }
  const client = new Client({ name: "opencode-web", version: "1.0.0" })
  await client.connect(new HttpRpcTransport({ server: "weather", baseUrl: "http://localhost:4096", fetchFn }))
  return { client, calls }
}

describe("readUiResource", () => {
  test("reads a ui:// resource through the relayed client", async () => {
    const { client, calls } = await setupClient({
      contents: [{ uri: "ui://dashboard", mimeType: "text/html", text: "<html><body><button /></body></html>" }],
    })

    const html = await readUiResource(client, "ui://dashboard")

    expect(html).toBe("<html><body><button /></body></html>")
    expect(calls.find((call) => call.method === "resources/read")).toMatchObject({
      method: "resources/read",
      params: { uri: "ui://dashboard" },
    })
  })

  test("rejects non-HTML resources", async () => {
    const { client } = await setupClient({ contents: [{ uri: "ui://x", mimeType: "text/plain", text: "hi" }] })
    await expect(readUiResource(client, "ui://x")).rejects.toThrow(/text\/html/)
  })

  test("rejects resources without content", async () => {
    const { client } = await setupClient({ contents: [] })
    await expect(readUiResource(client, "ui://x")).rejects.toThrow()
  })
})

describe("injectCsp", () => {
  test("injects the CSP meta before existing head content", () => {
    const html = injectCsp("<html><head><title>t</title></head><body></body></html>")

    const cspAt = html.indexOf('http-equiv="Content-Security-Policy"')
    expect(cspAt).toBeGreaterThan(html.indexOf("<head>"))
    expect(cspAt).toBeLessThan(html.indexOf("<title>"))
    expect(html).toContain("<title>t</title>")
    expect(html).toContain("script-src 'unsafe-inline'")
  })

  test("keeps head attributes when injecting", () => {
    const html = injectCsp('<html><head lang="en"><title>t</title></head></html>')
    expect(html).toContain('<head lang="en"><meta http-equiv="Content-Security-Policy"')
  })

  test("wraps headless fragments in a full document", () => {
    const html = injectCsp("<p>hello</p>")

    expect(html).toMatch(/^<!DOCTYPE html>/i)
    expect(html).toContain('http-equiv="Content-Security-Policy"')
    expect(html).toContain("<p>hello</p>")
  })
})

describe("buildSandboxedHtml", () => {
  test("returns a revocable blob URL for the sandboxed document", () => {
    const { url, revoke } = buildSandboxedHtml("<html><head></head><body></body></html>")

    expect(url.startsWith("blob:")).toBe(true)
    revoke()
  })
})
