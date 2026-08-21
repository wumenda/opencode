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
import { buildSandboxedHtml, readUiResource } from "@/lib/mcp-apps/resource"
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

  let client: Client | undefined
  let bridge: AppBridge | undefined
  let revoke: (() => void) | undefined

  onMount(() => void start())
  onCleanup(() => {
    void bridge?.close()
    void client?.close()
    revoke?.()
  })

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
      const sandbox = buildSandboxedHtml(html)
      revoke = sandbox.revoke
      setBlobUrl(sandbox.url)
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
    const api = serverSDK().currentApi
    const status = async () =>
      (await api.mcp.list({ location: { directory } })).data.find((entry) => entry.name === props.server)?.status.status

    const current = await status()
    if (current === "connected") return
    if (current === undefined) throw new Error(language.t("mcp.app.notConfigured"))
    if (current === "needs_auth" || current === "needs_client_registration") {
      throw new Error(language.t("mcp.app.needsAuth"))
    }

    await api.mcp.connect({ server: props.server, location: { directory } })
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
    const next = new AppBridge(client, { name: "opencode", version: "1.0.0" }, {
      openLinks: {},
      serverTools: {},
      serverResources: {},
      logging: {},
    })
    next.oninitialized = () => {
      if (props.fallbackData) void next.sendToolResult(props.fallbackData)
    }
    try {
      await next.connect(new PostMessageTransport(iframe.contentWindow, iframe.contentWindow))
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
    <div class="w-full overflow-hidden rounded-xl border-[0.5px] border-v2-border-border-base bg-v2-background-bg-layer-01">
      <Show when={phase() === "loading"}>
        <div class="flex h-80 items-center justify-center gap-2 text-v2-text-text-muted">
          <Spinner class="size-4" />
          <span class="text-[13px] font-[440] leading-5 tracking-[-0.04px]">{language.t("mcp.app.loading")}</span>
        </div>
      </Show>
      <Show when={phase() === "error"}>
        <div class="flex h-80 flex-col items-center justify-center gap-2 text-v2-text-text-muted">
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
          sandbox="allow-scripts"
          class="h-80 w-full border-0 bg-v2-background-bg-layer-01"
          onLoad={(event) => void onIframeLoad(event.currentTarget)}
        />
      </Show>
    </div>
  )
}
