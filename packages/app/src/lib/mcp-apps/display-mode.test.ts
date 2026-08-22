import { describe, expect, test } from "bun:test"
import { resolveDisplayMode } from "./display-mode"

describe("resolveDisplayMode", () => {
  test("returns requested mode when supported by the host", () => {
    expect(resolveDisplayMode("inline", ["inline"])).toBe("inline")
  })
  test("falls back to inline for unsupported modes", () => {
    expect(resolveDisplayMode("fullscreen", ["inline"])).toBe("inline")
    expect(resolveDisplayMode("pip", ["inline"])).toBe("inline")
  })
})