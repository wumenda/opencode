import { describe, expect, test } from "bun:test"
import { createMcpAppHostRegistry, type McpAppEvent } from "./mcp-app-host"

describe("createMcpAppHostRegistry", () => {
  test("routes events to the registered sink", () => {
    const reg = createMcpAppHostRegistry()
    const received: McpAppEvent[] = []
    const un = reg.register("a/ui://x", (e) => received.push(e))
    reg.push("a/ui://x", { type: "tool-input-partial", arguments: { axis: "x" } })
    expect(received).toEqual([{ type: "tool-input-partial", arguments: { axis: "x" } }])
    un()
  })

  test("buffers pushes before registration and flushes on register", () => {
    const reg = createMcpAppHostRegistry()
    const received: McpAppEvent[] = []
    reg.push("a/ui://x", { type: "tool-result", result: { content: [{ type: "text", text: "ok" }] } })
    reg.register("a/ui://x", (e) => received.push(e))
    expect(received).toHaveLength(1)
  })

  test("drops pushes for an unregistered key after unregister", () => {
    const reg = createMcpAppHostRegistry()
    const received: McpAppEvent[] = []
    const un = reg.register("a/ui://x", (e) => received.push(e))
    un()
    reg.push("a/ui://x", { type: "tool-input-partial", arguments: {} })
    expect(received).toHaveLength(0)
  })

  test("routes tool-cancelled to the registered sink", () => {
    const reg = createMcpAppHostRegistry()
    const received: McpAppEvent[] = []
    const un = reg.register("a/ui://x", (e) => received.push(e))
    reg.push("a/ui://x", { type: "tool-cancelled", reason: "canceled" })
    expect(received).toEqual([{ type: "tool-cancelled", reason: "canceled" }])
    un()
  })

  test("routes tool-progress to the registered sink", () => {
    const reg = createMcpAppHostRegistry()
    const received: McpAppEvent[] = []
    const un = reg.register("a/ui://x", (e) => received.push(e))
    reg.push("a/ui://x", { type: "tool-progress", progress: 3, total: 5, message: "step 3/5" })
    expect(received).toEqual([{ type: "tool-progress", progress: 3, total: 5, message: "step 3/5" }])
    un()
  })

  test("replays the last tool-progress to a re-registered (remounted) app", () => {
    const reg = createMcpAppHostRegistry()
    const first: McpAppEvent[] = []
    const firstUn = reg.register("a/ui://x", (e) => first.push(e))
    reg.push("a/ui://x", { type: "tool-progress", progress: 1, total: 5, message: "step 1/5" })
    reg.push("a/ui://x", { type: "tool-progress", progress: 5, total: 5, message: "step 5/5" })
    firstUn()

    // 模拟 iframe 重挂载：重新注册新 sink，应重放最近一次的 tool-progress。
    const second: McpAppEvent[] = []
    reg.register("a/ui://x", (e) => second.push(e))
    expect(second).toEqual([{ type: "tool-progress", progress: 5, total: 5, message: "step 5/5" }])
  })

  test("replays the last tool-result to a re-registered (remounted) app", () => {
    const reg = createMcpAppHostRegistry()
    const first: McpAppEvent[] = []
    const firstUn = reg.register("a/ui://x", (e) => first.push(e))
    reg.push("a/ui://x", { type: "tool-result", result: { content: [{ type: "text", text: "ok" }] } })
    firstUn()

    // 模拟懒挂载 tab 在工具完成后重挂载：应重放最终 tool-result，而不是空等。
    const second: McpAppEvent[] = []
    reg.register("a/ui://x", (e) => second.push(e))
    expect(second).toEqual([{ type: "tool-result", result: { content: [{ type: "text", text: "ok" }] } }])
  })

  test("replays the last tool-input (before tool-result) to a re-registered app", () => {
    const reg = createMcpAppHostRegistry()
    const first: McpAppEvent[] = []
    const firstUn = reg.register("a/ui://x", (e) => first.push(e))
    reg.push("a/ui://x", { type: "tool-input", arguments: { input_path: "a.pdf" } })
    reg.push("a/ui://x", { type: "tool-result", result: { content: [{ type: "text", text: "ok" }] } })
    firstUn()

    // 模拟懒挂载的面板 tab 在工具完成后重挂载：tool-input 必须先于 tool-result 重放
    // （App 状态机 processing -> result_ready），否则 UI 因 toolInput 缺失卡"等待任务"。
    const second: McpAppEvent[] = []
    reg.register("a/ui://x", (e) => second.push(e))
    expect(second).toEqual([
      { type: "tool-input", arguments: { input_path: "a.pdf" } },
      { type: "tool-result", result: { content: [{ type: "text", text: "ok" }] } },
    ])
  })

  test("does not record tool-input-partial as lastToolInput (streaming fragments are transient)", () => {
    const reg = createMcpAppHostRegistry()
    const first: McpAppEvent[] = []
    const firstUn = reg.register("a/ui://x", (e) => first.push(e))
    reg.push("a/ui://x", { type: "tool-input-partial", arguments: { input_path: "a.pdf" } })
    firstUn()

    // partial 是流式片段，不进入 lastToolInput 重放；只有完整版 tool-input 被记录。
    const second: McpAppEvent[] = []
    reg.register("a/ui://x", (e) => second.push(e))
    expect(second).toHaveLength(0)
  })

  test("skips lastToolInput replay when pending buffer already carries one", () => {
    const reg = createMcpAppHostRegistry()
    // 首个 sink 从未注册：推送的完整版 input 进入 pending 缓冲。
    reg.push("a/ui://x", { type: "tool-input", arguments: { input_path: "a.pdf" } })
    reg.push("a/ui://x", { type: "tool-input", arguments: { input_path: "a.pdf" } })

    const second: McpAppEvent[] = []
    reg.register("a/ui://x", (e) => second.push(e))
    // buffered 中已有 tool-input 时不再叠加 lastToolInput，避免重复投递。
    expect(second).toEqual([{ type: "tool-input", arguments: { input_path: "a.pdf" } }, { type: "tool-input", arguments: { input_path: "a.pdf" } }])
  })

  test("broadcasts events to all sinks sharing the same app key", () => {
    const reg = createMcpAppHostRegistry()
    const timeline: McpAppEvent[] = []
    const sidebar: McpAppEvent[] = []
    reg.register("a/ui://x", (e) => timeline.push(e))
    reg.register("a/ui://x", (e) => sidebar.push(e))

    reg.push("a/ui://x", { type: "tool-progress", progress: 2, total: 5, message: "step 2/5" })
    reg.push("a/ui://x", { type: "tool-progress", progress: 5, total: 5, message: "step 5/5" })

    // 对话流工具卡与侧栏面板都应收到全部进度步骤。
    expect(timeline).toHaveLength(2)
    expect(sidebar).toHaveLength(2)
    expect(timeline[1]).toEqual({ type: "tool-progress", progress: 5, total: 5, message: "step 5/5" })
    expect(sidebar[1]).toEqual({ type: "tool-progress", progress: 5, total: 5, message: "step 5/5" })
  })
})