import { expect, test } from "bun:test"
import { buildHostContext } from "./host-context"

test("builds host context with container dimensions and theme", () => {
  const ctx = buildHostContext({ width: 640, height: 480, theme: "dark", locale: "zh-CN" })
  expect(ctx.containerDimensions).toMatchObject({ width: 640, height: 480 })
  expect(ctx.theme).toBe("dark")
  expect(ctx.locale).toBe("zh-CN")
  expect(ctx.displayMode).toBe("inline")
  expect(ctx.platform).toBe("web")
})

test("omits dimensions when missing", () => {
  const ctx = buildHostContext({})
  expect(ctx.containerDimensions).toBeUndefined()
})