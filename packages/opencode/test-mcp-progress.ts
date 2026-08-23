// 临时诊断脚本：验证 StreamableHTTPClientTransport 下 notifications/progress 是否送达 onprogress
import { Client } from "@modelcontextprotocol/sdk/client/index.js"
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js"

const url = new URL("http://localhost:8000/mcp")
const client = new Client({ name: "progress-probe", version: "1.0.0" })
const transport = new StreamableHTTPClientTransport(url)
await client.connect(transport)
console.log("connected, server caps:", JSON.stringify(client.getServerCapabilities()))

const result = await client.callTool(
  { name: "step1", arguments: { iterations: 5, message: "probe" } },
  undefined,
  {
    resetTimeoutOnProgress: true,
    onprogress: (p) => console.log("PROGRESS", JSON.stringify(p)),
    timeout: 30_000,
  },
)
console.log("RESULT", JSON.stringify(result).slice(0, 300))
await client.close()
