import { OpenCode } from "@opencode-ai/client/promise"

const api = OpenCode.make({ baseUrl: "http://127.0.0.1:4096" })
const dir = "d:/项目/AI-For-Redesign/代码库/opencode"
try {
  const r = await api.mcp.list({ location: { directory: dir } })
  console.log("KEYS:", Array.isArray(r.data) ? "array" : Object.keys(r.data ?? {}).join(", "))
  console.log(JSON.stringify(r, null, 2).slice(0, 1200))
} catch (e) {
  console.log("THREW:", e.constructor.name, e.message)
}