import { AppBridge, PostMessageTransport } from "@modelcontextprotocol/ext-apps/app-bridge"
import { Client } from "@modelcontextprotocol/sdk/client/index.js"
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js"
import { type Component, createSignal, onCleanup, onMount, Show } from "solid-js"
import { Spinner } from "@opencode-ai/ui/spinner"
import { useLanguage } from "@/context/language"
import { usePlatform } from "@/context/platform"
import { useSDK } from "@/context/sdk"
import { useServerSDK } from "@/context/server-sdk"
import { HttpRpcTransport } from "@/lib/mcp-apps/http-rpc-transport"
import { hostCapabilities } from "@/lib/mcp-apps/bridge"
import { buildHostContext } from "@/lib/mcp-apps/host-context"
import { buildBinaryResourceUrl, buildSandboxedHtml, readUiResource } from "@/lib/mcp-apps/resource"
import { mcpServerStatus } from "@/lib/mcp-apps/mcp-status"
import { authTokenFromCredentials } from "@/utils/server"

const CONNECT_TIMEOUT_MS = 30_000
const CONNECT_POLL_MS = 500

export type McpAppViewProps = {
  /** MCP server configuration name, e.g. "weather". */
  server: string
  /** ui:// resource URI of the app HTML document. */
  resourceUri: string
  /** Completed tool result (contract 1 metadata.mcp.result) replayed into the app after init. */
  fallbackData?: CallToolResult
  onError?: (message: string) => void
  /** 填满父容器高度（用于面板模式），默认 false 使用固定 h-80。 */
  fillHeight?: boolean
  /** 传入 hostContext 的主题，透传给 MCP App（沿用宿主侧明暗主题）。 */
  theme?: "light" | "dark"
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

/**
 * Renders an MCP App (SEP-1865) from a ui:// resource inside a sandboxed iframe
 * and bridges it to the host MCP server through the /api/mcp/:name/rpc relay.
 */
export const McpAppView: Component<McpAppViewProps> = (props) => {
  const language = useLanguage()
  const platform = usePlatform()
  const serverSDK = useServerSDK()
  const sdk = useSDK()

  const [phase, setPhase] = createSignal<"loading" | "ready" | "error">("loading")
  const [errorMessage, setErrorMessage] = createSignal("")
  const [blobUrl, setBlobUrl] = createSignal<string>()
  const [sandbox, setSandbox] = createSignal("allow-scripts")
  const [autoHeight, setAutoHeight] = createSignal<number>()

  let client: Client | undefined
  let bridge: AppBridge | undefined
  let revoke: (() => void) | undefined

  onMount(() => void start())
  onCleanup(() => {
    void bridge?.close()
    void client?.close()
    revoke?.()
  })

  // 命令式入口：宿主在工具运行期向其推送部分输入。bridge 在 onIframeLoad 成功后才
  // 就绪；未就绪时为 no-op（幂等）。供后续"后端运行中 -> App"流式触发源复用。
  const pushToolInput = (partial: Record<string, unknown>) => {
    void bridge?.sendToolInputPartial({ arguments: partial })
  }

  async function start() {
    void bridge?.close()
    bridge = undefined
    void client?.close()
    client = undefined
    revoke?.()
    revoke = undefined
    setBlobUrl()
    setPhase("loading")

    const directory = sdk().directory
    const http = serverSDK().server.http
    const next = new Client({ name: "opencode-web", version: "1.0.0" })
    const transport = new HttpRpcTransport({
      server: props.server,
      baseUrl: serverSDK().url,
      directory,
      headers: http.password
        ? { authorization: `Basic ${authTokenFromCredentials({ username: http.username, password: http.password })}` }
        : undefined,
      fetchFn: platform.fetch,
    })

    try {
      await ensureConnected(directory)
      await next.connect(transport)
      client = next
      const html = await readUiResource(next, props.resourceUri)
      let url: string
      let sandboxTokens = "allow-scripts"
      if (html.text) {
        const s = buildSandboxedHtml(html.text, { csp: html.meta?.ui?.csp, permissions: html.meta?.ui?.permissions })
        url = s.url
        sandboxTokens = s.sandbox
        revoke = s.revoke
      } else if (html.blob) {
        url = buildBinaryResourceUrl(html.blob, html.mimeType ?? "application/octet-stream")
        revoke = () => URL.revokeObjectURL(url)
      } else {
        throw new Error(language.t("mcp.app.loading"))
      }
      setBlobUrl(url)
      setSandbox(sandboxTokens)
      setPhase("ready")
    } catch (error) {
      void next.close()
      const message = error instanceof Error ? error.message : String(error)
      setErrorMessage(message)
      setPhase("error")
      props.onError?.(message)
    }
  }

  async function ensureConnected(directory: string) {
    // The vendored client talks `location` query terms and expects 204 from connect,
    // neither of which the deployed backend honours. Ping the same relay endpoints the
    // RPC transport uses (keyed by `directory`) so we observe the actual workspace scope.
    const http = serverSDK().server.http
    const fetchFn = (platform.fetch ?? globalThis.fetch).bind(globalThis)
    const headers = http.password
      ? { authorization: `Basic ${authTokenFromCredentials({ username: http.username, password: http.password })}` }
      : undefined
    const status = async () => {
      const target = new URL("/api/mcp", serverSDK().url)
      if (directory) target.searchParams.set("directory", directory)
      const response = await fetchFn(target, { headers })
      if (!response.ok) return undefined
      const payload = (await response.json()) as
        | { data?: Array<{ name: string; status: { status?: string } }> }
        | Record<string, { status?: string }>
      // `/api/mcp` may answer an array `{ data: [{ name, status }] }` (E2E mock) or a
      // record keyed by server name (deployed backend). Accept both.
      return mcpServerStatus(payload, props.server)
    }

    const current = await status()
    if (current === "connected") return
    if (current === undefined) throw new Error(language.t("mcp.app.notConfigured"))
    if (current === "needs_auth" || current === "needs_client_registration") {
      throw new Error(language.t("mcp.app.needsAuth"))
    }

    const connectTarget = new URL(`/api/mcp/${encodeURIComponent(props.server)}/connect`, serverSDK().url)
    if (directory) connectTarget.searchParams.set("directory", directory)
    await fetchFn(connectTarget, { method: "POST", headers })
    const deadline = Date.now() + CONNECT_TIMEOUT_MS
    while (Date.now() < deadline) {
      await sleep(CONNECT_POLL_MS)
      const next = await status()
      if (next === "connected") return
      if (next === "needs_auth" || next === "needs_client_registration") {
        throw new Error(language.t("mcp.app.needsAuth"))
      }
      if (next === "failed") throw new Error(language.t("mcp.app.connectFailed"))
    }
    throw new Error(language.t("mcp.app.connectTimeout"))
  }

  // The blob document replaces the initial about:blank window, so the bridge is
  // wired up only after the iframe finished loading the sandboxed document.
  async function onIframeLoad(iframe: HTMLIFrameElement) {
    if (!client || !iframe.contentWindow) return
    const hostContext = buildHostContext({
      width: iframe.clientWidth || undefined,
      height: iframe.clientHeight || undefined,
      locale: language.intl(), // 取自 useLanguage() 的 BCP-47 locale tag
      theme: props.theme,
    })
    const next = new AppBridge(
      client,
      { name: "opencode", version: "1.0.0" },
      hostCapabilities({ openLink: true, downloadFile: false, message: true, logging: true }),
      { hostContext },
    )
    next.oninitialized = () => {
      if (props.fallbackData) void next.sendToolResult(props.fallbackData)
    }
    next.onopenlink = async (params) => {
      platform.openExternal(params.url)
      return {}
    }
    next.onmessage = async (params) => {
      console.log("[mcp-app] app message", params)
      return {}
    }
    next.onupdatemodelcontext = async (params) => {
      console.log("[mcp-app] update model context", params)
      return {}
    }
    next.onrequestteardown = async () => {
      void next.close()
    }
    next.onsizechange = (h: { width?: number; height?: number }) => {
      if (h.height) setAutoHeight(h.height)
    }
    try {
      const transport = new PostMessageTransport(iframe.contentWindow, iframe.contentWindow)
      // Log host -> iframe `ui/notifications/*` dispatch (diagnostics only, no UI).
      const baseSend = transport.send.bind(transport)
      transport.send = async (message, options) => {
        const method = (message as { method?: unknown } | undefined)?.method
        if (typeof method === "string" && method.startsWith("ui/notifications/")) {
          console.log(`[mcp-app] host -> app ${method}`, (message as { params?: unknown }).params)
        }
        return baseSend(message, options)
      }
      await next.connect(transport)
      bridge = next
    } catch (error) {
      void next.close()
      const message = error instanceof Error ? error.message : String(error)
      setErrorMessage(message)
      setPhase("error")
      props.onError?.(message)
    }
  }

  return (
    <div
      class="w-full overflow-hidden rounded-xl border-[0.5px] border-v2-border-border-base bg-v2-background-bg-layer-01"
      classList={{ "h-full flex flex-col": props.fillHeight }}
    >
      <Show when={phase() === "loading"}>
        <div
          class="flex items-center justify-center gap-2 text-v2-text-text-muted"
          classList={{ "h-80": !props.fillHeight, "flex-1": props.fillHeight }}
        >
          <Spinner class="size-4" />
          <span class="text-[13px] font-[440] leading-5 tracking-[-0.04px]">{language.t("mcp.app.loading")}</span>
        </div>
      </Show>
      <Show when={phase() === "error"}>
        <div
          class="flex flex-col items-center justify-center gap-2 text-v2-text-text-muted"
          classList={{ "h-80": !props.fillHeight, "flex-1": props.fillHeight }}
        >
          <span class="text-[13px] font-[440] leading-5 tracking-[-0.04px]">{errorMessage()}</span>
          <button
            type="button"
            class="cursor-pointer border-none bg-transparent p-0 text-[13px] font-[530] leading-5 tracking-[-0.04px] text-v2-text-text-base underline"
            onClick={() => void start()}
          >
            {language.t("mcp.app.retry")}
          </button>
        </div>
      </Show>
      <Show when={blobUrl()}>
        <iframe
          src={blobUrl()}
          sandbox={sandbox()}
          class="w-full border-0 bg-v2-background-bg-layer-01"
          classList={{ "h-80": !props.fillHeight && !autoHeight(), "flex-1": props.fillHeight }}
          style={autoHeight() ? { height: `${autoHeight()}px` } : undefined}
          onLoad={(event) => void onIframeLoad(event.currentTarget)}
        />
      </Show>
    </div>
  )
}
