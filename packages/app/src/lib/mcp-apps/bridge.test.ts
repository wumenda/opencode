import { expect, test } from "bun:test"
import { hostCapabilities } from "./bridge"

test("advertises only implemented capabilities", () => {
  const caps = hostCapabilities({ openLink: true, downloadFile: false, message: true, logging: true })
  expect(caps.openLinks).toBeDefined()
  expect(caps.downloadFile).toBeUndefined()
  expect(caps.message).toBeDefined()
  expect(caps.logging).toBeDefined()
  expect(caps.serverTools).toBeDefined()
  expect(caps.serverResources).toBeDefined()
})

test("omits unset capabilities", () => {
  const caps = hostCapabilities({ openLink: false, downloadFile: false, message: false, logging: false })
  expect(caps.openLinks).toBeUndefined()
  expect(caps.downloadFile).toBeUndefined()
  expect(caps.message).toBeUndefined()
  expect(caps.logging).toBeUndefined()
  expect(caps.serverTools).toBeDefined()
})

test("declares downloadFile when enabled", () => {
  const caps = hostCapabilities({ openLink: false, downloadFile: true, message: false, logging: false })
  expect(caps.downloadFile).toEqual({})
  expect(caps.openLinks).toBeUndefined()
  expect(caps.message).toBeUndefined()
})

test("declares sampling when a handler is enabled", () => {
  const caps = hostCapabilities({ openLink: false, downloadFile: false, message: false, logging: false, sampling: true })
  expect(caps.sampling).toEqual({})
  const off = hostCapabilities({ openLink: true, downloadFile: true, message: true, logging: true, sampling: false })
  expect(off.sampling).toBeUndefined()
})