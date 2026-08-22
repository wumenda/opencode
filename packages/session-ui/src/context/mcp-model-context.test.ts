import { describe, expect, test } from "bun:test"
import { createModelContextStore } from "./mcp-model-context"

describe("createModelContextStore", () => {
  test("stores and overwrites the latest model context", () => {
    const store = createModelContextStore()
    expect(store.latest()).toBeUndefined()
    store.set({ content: [{ type: "text", text: "a" }] })
    store.set({ content: [{ type: "text", text: "b" }] })
    expect(store.latest()?.content).toEqual([{ type: "text", text: "b" }])
  })
})