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

test("defaults timeZone to the local timezone when not provided", () => {
  const ctx = buildHostContext({ theme: "dark" })
  expect(ctx.theme).toBe("dark")
  expect(ctx.timeZone).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone)
})