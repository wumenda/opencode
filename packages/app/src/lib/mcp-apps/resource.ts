import type { Client } from "@modelcontextprotocol/sdk/client/index.js"

export type SandboxOptions = {
  csp?: {
    connectDomains?: string[]
    resourceDomains?: string[]
    frameDomains?: string[]
    scriptDomains?: string[]
  }
  permissions?: {
    clipboardWrite?: unknown
    camera?: unknown
    microphone?: unknown
    geolocation?: unknown
  }
}

export type UiResourceContent = {
  text?: string
  blob?: string
  mimeType?: string
  meta?: { ui?: { csp?: unknown; permissions?: unknown } }
}

const isBlobContent = (c: unknown): c is { blob?: string; text?: string } =>
  typeof c === "object" && c !== null && ("blob" in c || "text" in c)

/** Reads a ui:// resource, returning either its HTML text or binary blob (plus metadata). */
export async function readUiResource(client: Client, uri: string): Promise<UiResourceContent> {
  const result = await client.readResource({ uri })
  if (!Array.isArray(result.contents)) throw new Error(`ui resource ${uri} returned no contents`)
  const content = result.contents.find(isBlobContent)
  if (!content) throw new Error(`ui resource ${uri} returned no content`)
  const mime = (content.mimeType ?? "") || ""
  const base = mime.split(";")[0].trim()
  if (base !== "text/html" && base !== "application/pdf") {
    throw new Error(`ui resource ${uri} has mimeType ${mime || "(none)"}, expected text/html`)
  }
  return {
    text: "text" in content ? content.text : undefined,
    blob: "blob" in content ? content.blob : undefined,
    mimeType: mime,
    meta: (content as { _meta?: UiResourceContent["meta"] })._meta,
  }
}

/** Injects the sandbox CSP meta at the top of <head>, wrapping headless fragments in a full document. */
export function injectCsp(html: string, csp?: SandboxOptions["csp"]): string {
  const base = [
    "default-src 'none'",
    `script-src 'unsafe-inline' 'self' data: ${csp?.scriptDomains?.join(" ") || ""}`.trim(),
    "style-src 'unsafe-inline'",
    "img-src data: blob:",
    `connect-src ${[...(csp?.connectDomains ?? []), ...(csp?.resourceDomains ?? [])].join(" ") || "'none'"}`,
    `frame-src ${csp?.frameDomains?.join(" ") || "'none'"}`,
    "frame-ancestors 'self'",
  ].join("; ")

  const headOpen = /<head(\s[^>]*)?>/i.exec(html)
  if (headOpen) {
    const at = headOpen.index + headOpen[0].length
    return html.slice(0, at) + `<meta http-equiv="Content-Security-Policy" content="${base}">` + html.slice(at)
  }

  const htmlOpen = /<html(\s[^>]*)?>/i.exec(html)
  if (htmlOpen) {
    const at = htmlOpen.index + htmlOpen[0].length
    return html.slice(0, at) + `<head><meta http-equiv="Content-Security-Policy" content="${base}"></head>` + html.slice(at)
  }

  return `<!DOCTYPE html><html><head><meta http-equiv="Content-Security-Policy" content="${base}"></head><body>${html}</body></html>`
}

/** Builds a CSP-sandboxed document and returns its blob URL, cleaned HTML, and iframe sandbox tokens with a cleanup function. */
export function buildSandboxedHtml(
  html: string,
  opts?: SandboxOptions,
): { url: string; revoke: () => void; html: string; sandbox: string } {
  const htmlOut = injectCsp(html, opts?.csp)
  const blob = new Blob([htmlOut], { type: "text/html" })
  const url = URL.createObjectURL(blob)

  const allows = ["allow-scripts"]
  if (opts?.permissions?.clipboardWrite) allows.push("allow-clipboard-write")
  // camera / microphone / geolocation 需要宿主端授权策略，此处不静默放行（仅注释说明）

  return { url, revoke: () => URL.revokeObjectURL(url), html: htmlOut, sandbox: allows.join(" ") }
}
