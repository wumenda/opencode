import { expect, test } from "bun:test"
import { mcpServerStatus } from "./mcp-status"

test("reads server status from array payload", () => {
  const payload = { data: [{ name: "ui-server", status: { status: "connected" } }] }
  expect(mcpServerStatus(payload, "ui-server")).toBe("connected")
})

test("reads server status from record payload", () => {
  const payload = { "ui-server": { status: "failed", error: "x" } } as Record<string, { status?: string }>
  expect(mcpServerStatus(payload, "ui-server")).toBe("failed")
})

test("returns undefined when server is absent", () => {
  expect(mcpServerStatus({ data: [] }, "missing")).toBeUndefined()
  expect(mcpServerStatus({}, "missing")).toBeUndefined()
})