import { describe, expect, test } from "bun:test"
import { toMcpTheme } from "./host-context-utils"

describe("toMcpTheme", () => {
  test("maps host light/dark mode to an MCP theme label", () => {
    expect(toMcpTheme("light")).toBe("light")
    expect(toMcpTheme("dark")).toBe("dark")
  })
})