import type { Client } from "@modelcontextprotocol/sdk/client/index.js"
import type { TextResourceContents } from "@modelcontextprotocol/sdk/types.js"

const CSP_POLICY = [
  "default-src 'none'",
  "script-src 'unsafe-inline' 'self' data:",
  "style-src 'unsafe-inline'",
  "img-src data: blob:",
  "connect-src 'none'",
  "frame-ancestors 'self'",
].join("; ")

const CSP_META = `<meta http-equiv="Content-Security-Policy" content="${CSP_POLICY}">`

/** Type guard for a text resource content (distinct from blob content). */
function isTextContent(content: unknown): content is TextResourceContents {
  return typeof content === "object" && content !== null && "text" in content
}

/** Reads a ui:// resource and returns its HTML text, rejecting anything that is not text/html. */
export async function readUiResource(client: Client, uri: string): Promise<string> {
  const result = await client.readResource({ uri })
  const content = result.contents.find(isTextContent)
  if (!content) throw new Error(`ui resource ${uri} returned no text content`)
  if (content.mimeType !== "text/html") {
    throw new Error(`ui resource ${uri} has mimeType ${content.mimeType ?? "(none)"}, expected text/html`)
  }
  return content.text
}

/** Injects the sandbox CSP meta at the top of <head>, wrapping headless fragments in a full document. */
export function injectCsp(html: string): string {
  const headOpen = /<head(\s[^>]*)?>/i.exec(html)
  if (headOpen) {
    const at = headOpen.index + headOpen[0].length
    return html.slice(0, at) + CSP_META + html.slice(at)
  }

  const htmlOpen = /<html(\s[^>]*)?>/i.exec(html)
  if (htmlOpen) {
    const at = htmlOpen.index + htmlOpen[0].length
    return html.slice(0, at) + `<head>${CSP_META}</head>` + html.slice(at)
  }

  return `<!DOCTYPE html><html><head>${CSP_META}</head><body>${html}</body></html>`
}

/** Builds a CSP-sandboxed document and returns its blob URL with a cleanup function. */
export function buildSandboxedHtml(html: string): { url: string; revoke: () => void } {
  const blob = new Blob([injectCsp(html)], { type: "text/html" })
  const url = URL.createObjectURL(blob)
  return { url, revoke: () => URL.revokeObjectURL(url) }
}
