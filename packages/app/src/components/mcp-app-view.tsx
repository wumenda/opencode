import type { CallToolResult, CreateMessageRequest, CreateMessageResult, CreateMessageResultWithTools } from "@modelcontextprotocol/sdk/types.js"
import { AppBridge, PostMessageTransport } from "@modelcontextprotocol/ext-apps/app-bridge"
import { Client } from "@modelcontextprotocol/sdk/client/index.js"
import { createEffect, createMemo, type Component, createSignal, onCleanup, onMount, Show } from "solid-js"
import { Spinner } from "@opencode-ai/ui/spinner"
import { useTheme } from "@opencode-ai/ui/theme/context"
import { useLanguage } from "@/context/language"
import { usePlatform } from "@/context/platform"
import { useSDK } from "@/context/sdk"
import { useServerSDK } from "@/context/server-sdk"
import { useMcpAppHost, useMcpModelContext, type AppKey, type McpAppEvent, type McpAppSink } from "@opencode-ai/session-ui/context"
import { HttpRpcTransport } from "@/lib/mcp-apps/http-rpc-transport"
import { resolveDisplayMode, SUPPORTED_DISPLAY_MODES } from "@/lib/mcp-apps/display-mode"
import { hostCapabilities } from "@/lib/mcp-apps/bridge"
import { buildHostContext } from "@/lib/mcp-apps/host-context"
import { toMcpTheme } from "@/lib/mcp-apps/host-context-utils"
import { buildBinaryResourceUrl, buildSandboxedHtml, readUiResource } from "@/lib/mcp-apps/resource"
import { mcpServerStatus } from "@/lib/mcp-apps/mcp-status"
import { showToast } from "@/utils/toast"
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
  /** 宿主提供的采样实现：接通 AppBridge 的 oncreatesamplingmessage（声明 sampling 能力）。 */
  onSampling?: (request: CreateMessageRequest["params"]) => Promise<CreateMessageResult | CreateMessageResultWithTools>
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
  const host = useMcpAppHost()
  const modelCtx = useMcpModelContext()
  const themeCtx = useTheme()
  const resolvedTheme = createMemo(() => toMcpTheme(themeCtx.mode()))

  const [phase, setPhase] = createSignal<"loading" | "ready" | "error">("loading")
  const [errorMessage, setErrorMessage] = createSignal("")
  const [blobUrl, setBlobUrl] = createSignal<string>()
  const [sandbox, setSandbox] = createSignal("allow-scripts")
  const [allow, setAllow] = createSignal("")
  const [autoHeight, setAutoHeight] = createSignal<number>()

  let client: Client | undefined
  let bridge: AppBridge | undefined
  let revoke: (() => void) | undefined
  let unregister: (() => void) | undefined
  let containerRef: HTMLDivElement | undefined
  let resizeObserver: ResizeObserver | undefined

  // 宿主主题或容器尺寸变化时，把最新 hostContext 实时推给 App（bridge 未就绪时为无害 no-op）。
  const publishHostContext = (width?: number, height?: number) => {
    void bridge?.setHostContext(
      buildHostContext({ width, height, theme: resolvedTheme(), locale: language.intl() }),
    )
  }

  const onResize = () => {
    if (containerRef) publishHostContext(containerRef.clientWidth || undefined, containerRef.clientHeight || undefined)
  }

  createEffect(() => {
    void resolvedTheme()
    publishHostContext()
  })

  // 宿主注册表以 server/resourceUri 为 key。App 尚未初始化（bridge 未就绪）前收到的
  // 事件先入 pending，oninitialized 后统一冲刷转发进 iframe。
  let appInitialized = false
  const pending: McpAppEvent[] = []
  const forward = (event: McpAppEvent) => {
    if (!bridge) return
    if (event.type === "tool-input-partial") void bridge.sendToolInputPartial({ arguments: event.arguments })
    else if (event.type === "tool-result") void bridge.sendToolResult(event.result as CallToolResult)
    else if (event.type === "tool-cancelled") void bridge.sendToolCancelled({ reason: event.reason })
  }
  const handleEvent: McpAppSink = (event) => {
    if (!bridge || !appInitialized) {
      pending.push(event)
      return
    }
    forward(event)
  }
  const drainPending = () => {
    while (pending.length) forward(pending.shift()!)
  }

  // 按 server/resourceUri 在宿主注册表注册/注销本 App 的 sink，接收运行中/完成的工具事件。
  const appKey = () => `${props.server}/${props.resourceUri}` as AppKey
  onMount(() => {
    void start()
    unregister = host.register(appKey(), handleEvent)
    // 宿主容器尺寸变化时实时推送 hostContext（避免首帧容器尚未布局导致尺寸为 0）。
    if (typeof ResizeObserver !== "undefined" && containerRef) {
      resizeObserver = new ResizeObserver(onResize)
      resizeObserver.observe(containerRef)
    }
  })
  onCleanup(() => {
    unregister?.()
    resizeObserver?.disconnect()
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
    setAllow("")
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
        setAllow(s.allow)
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
      hostCapabilities({ openLink: true, downloadFile: true, message: true, logging: true, sampling: !!props.onSampling }),
      { hostContext },
    )
    if (props.onSampling) {
      // 接通宿主采样实现：App 发起 sampling 时委托给宿主提供的 onSampling。
      next.oncreatesamplingmessage = async (params) => props.onSampling!(params)
    }
    next.oninitialized = () => {
      // App 就绪后标记已初始化并回放 fallbackData（契约 1）。
      // pending 事件要等 `bridge` 赋值后再冲刷（见 connect 成功处），否则会被 forward 丢弃。
      appInitialized = true
      if (props.fallbackData) void next.sendToolResult(props.fallbackData)
    }
    next.onopenlink = async (params) => {
      platform.openExternal(params.url)
      return {}
    }
    next.onmessage = async ({ content }, _extra) => {
      // 把 App 发来的 ui/message 文本上屏到宿主（轻量呈现：toast）。若接入会话存储可替换为写会话。
      const text = content
        .filter((block) => block.type === "text" && typeof block.text === "string")
        .map((block) => (block as { text: string }).text)
        .join("\n")
      if (text) showToast(text)
      return {}
    }
    next.onupdatemodelcontext = async ({ content, structuredContent }, _extra) => {
      // 把 App 发来的 ui/update-model-context 写入宿主可读的 store，供后续并入模型上下文。
      modelCtx.set({ content, structuredContent })
      return {}
    }
    next.onrequestteardown = async () => {
      // 视图请求卸载：先发 ui/resource-teardown 让视图优雅结束，再关桥。
      try {
        await next.teardownResource({})
      } catch {
        // 视图未应答，忽略后继续卸载
      }
      void next.close()
    }
    next.ondownloadfile = async ({ contents }, _extra) => {
      const trigger = async (uri: string, body: { text?: string; blob?: string; mimeType?: string }) => {
        const mime = body.mimeType
        const blob = body.blob
          ? new Blob([Uint8Array.from(atob(body.blob), (c) => c.charCodeAt(0))], { type: mime })
          : new Blob([body.text ?? ""], { type: mime })
        const url = URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = url
        a.download = uri.split("/").pop() ?? "download"
        a.click()
        URL.revokeObjectURL(url)
      }
      try {
        for (const item of contents) {
          if (item.type === "resource") {
            await trigger(item.resource.uri, item.resource as { text?: string; blob?: string; mimeType?: string })
          } else if (item.type === "resource_link" && client) {
            const read = await client.readResource({ uri: item.uri })
            const c = read.contents[0] as { text?: string; blob?: string; mimeType?: string } | undefined
            await trigger(item.uri, c ?? {})
          }
        }
        return {}
      } catch (error) {
        console.error("[mcp-app] download failed", error)
        return { isError: true }
      }
    }
    next.onrequestdisplaymode = async ({ mode }) => {
      // 显式协商显示模式：按宿主支持列表决定实际生效模式，不支持则回退 inline。
      return { mode: resolveDisplayMode(mode, SUPPORTED_DISPLAY_MODES) }
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
      // bridge 就绪后才冲刷初始化期间缓冲的流式事件，避免 forward 因 bridge 未赋值而丢弃。
      if (appInitialized) drainPending()
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
      ref={containerRef}
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
          allow={allow()}
          class="w-full border-0 bg-v2-background-bg-layer-01"
          classList={{ "h-80": !props.fillHeight && !autoHeight(), "flex-1": props.fillHeight }}
          style={autoHeight() ? { height: `${autoHeight()}px` } : undefined}
          onLoad={(event) => void onIframeLoad(event.currentTarget)}
        />
      </Show>
    </div>
  )
}
