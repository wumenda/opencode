/**
 * host 侧 postMessage 协议实现（JSON-RPC 2.0 over postMessage）。
 *
 * 对应 ui/src/mcpApp.ts 的 iframe 侧客户端，这里实现 host 侧：
 *   - 收到 ui/initialize 请求 -> 返回 HostContext（theme / capabilities）
 *   - 收到 ui/notifications/initialized -> 记录日志
 *   - 收到 tools/call 请求 -> 分发到 read_image / submit_review 等 mock 工具
 *   - 主动发送 ui/notifications/tool-input、notifications/progress、
 *     ui/notifications/tool-result 驱动 UI
 */

import { renderPdfPage, readPdfBase64 } from './pdfRenderer';

export type LogEntry = {
  dir: 'host→ui' | 'ui→host';
  method: string;
  detail: string;
  ts: number;
};

type JsonRpcMessage = {
  jsonrpc: '2.0';
  id?: number | string;
  method?: string;
  params?: unknown;
  result?: unknown;
  error?: { code: number; message: string; data?: unknown };
};

/** 生成一张"蓝图"风格的占位底图（SVG），供 read_image 返回 base64。 */
function buildPlaceholderImage(width: number, height: number): {
  mime_type: string;
  data_base64: string;
} {
  const svg = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`,
    `<rect width="100%" height="100%" fill="#0b2239"/>`,
    `<g stroke="#1e5a8a" stroke-width="12" opacity="0.7">`,
    `  <line x1="0" y1="${height * 0.5}" x2="${width}" y2="${height * 0.5}"/>`,
    `  <line x1="${width * 0.25}" y1="0" x2="${width * 0.25}" y2="${height}"/>`,
    `  <line x1="${width * 0.5}" y1="0" x2="${width * 0.5}" y2="${height}"/>`,
    `  <line x1="${width * 0.75}" y1="0" x2="${width * 0.75}" y2="${height}"/>`,
    `</g>`,
    `<text x="${width / 2}" y="${height / 2 - 40}" fill="#7fd1ff" font-size="90" text-anchor="middle" font-family="monospace">MOCK PFD DRAWING</text>`,
    `<text x="${width / 2}" y="${height / 2 + 40}" fill="#3f8fc0" font-size="48" text-anchor="middle" font-family="monospace">(host placeholder · use read_image)</text>`,
    `</svg>`,
  ].join('');
  const bytes = new TextEncoder().encode(svg);
  let binary = '';
  bytes.forEach((b) => (binary += String.fromCharCode(b)));
  const data_base64 = btoa(binary);
  return { mime_type: 'image/svg+xml', data_base64 };
}

export class HostConnector {
  private iframe: HTMLIFrameElement | null = null;
  private onLog: (e: LogEntry) => void;
  private onReviewSubmitted: (info: { approved: boolean; reason?: string }) => void;

  constructor(opts: {
    onLog: (e: LogEntry) => void;
    onReviewSubmitted: (info: { approved: boolean; reason?: string }) => void;
  }) {
    this.onLog = opts.onLog;
    this.onReviewSubmitted = opts.onReviewSubmitted;
    window.addEventListener('message', this.handleMessage);
  }

  destroy(): void {
    window.removeEventListener('message', this.handleMessage);
  }

  /** 绑定当前 iframe（消息过滤依据）。 */
  setIframe(iframe: HTMLIFrameElement | null): void {
    this.iframe = iframe;
  }

  // ---- 接收 iframe 消息 ----

  private handleMessage = (event: MessageEvent): void => {
    const src = event.source as Window | null;
    if (this.iframe && src !== this.iframe.contentWindow) return;
    const msg = event.data as JsonRpcMessage;
    if (!msg || typeof msg !== 'object' || msg.jsonrpc !== '2.0') return;

    // 请求（有 id + method）
    if (msg.id != null && msg.method) {
      this.handleRequest(msg);
      return;
    }
    // 通知（无 id，有 method）
    if (!msg.method) return;
    this.onLog({
      dir: 'ui→host',
      method: msg.method,
      detail: safeStringify(msg.params),
      ts: Date.now(),
    });
  };

  private handleRequest(msg: JsonRpcMessage): void {
    const id = msg.id as number;
    const method = msg.method as string;
    const params = (msg.params ?? {}) as Record<string, unknown>;

    this.onLog({
      dir: 'ui→host',
      method,
      detail: safeStringify(params),
      ts: Date.now(),
    });

    try {
      switch (method) {
        case 'ui/initialize':
          // 握手：返回 host context（theme / capabilities）
          this.respond(id, {
            theme: 'light',
            capabilities: {},
            appInfo: params.appInfo,
          });
          break;

        case 'tools/call': {
          const name = params.name as string;
          const args = (params.arguments ?? {}) as Record<string, unknown>;
          this.handleToolCall(id, name, args).catch((e) => {
            this.respondError(id, e instanceof Error ? e.message : String(e));
          });
          break;
        }

        default:
          // 未知请求：返回空 result，避免 UI pending 超时
          this.respond(id, {});
          break;
      }
    } catch (e) {
      this.respondError(id, e instanceof Error ? e.message : String(e));
    }
  }

  /** 处理 UI 反向调用的 MCP 工具。 */
  private async handleToolCall(id: number, name: string, args: Record<string, unknown>): Promise<void> {
    switch (name) {
      case 'read_image': {
        // 解析 path 中的页码：mock://pfd/page-{N} -> pageIndex = N-1
        const path = (args.path as string) ?? '';
        const match = path.match(/mock:\/\/pfd\/page-(\d+)/);
        let pageIndex: number | null = null;
        if (match) {
          pageIndex = parseInt(match[1], 10) - 1;
        } else if (args.page_index != null) {
          pageIndex = args.page_index as number;
        }

        if (pageIndex !== null) {
          try {
            const rendered = await renderPdfPage(pageIndex);
            this.respond(id, {
              structuredContent: { mime_type: rendered.mime_type, data_base64: rendered.data_base64 },
              content: [],
            });
          } catch (e) {
            console.error('[read_image] PDF render failed:', e);
            this.respond(id, {
              structuredContent: buildPlaceholderImage(4096, 2897),
              content: [],
            });
          }
        } else {
          this.respond(id, {
            structuredContent: buildPlaceholderImage(4096, 2897),
            content: [],
          });
        }
        break;
      }

      case 'read_pdf': {
        // 返回整份 PDF 的 base64，供 UI 端直接加载渲染 PDF 文档（而非逐页栅格化）
        const pdfPath = (args.path as string) ?? null;
        try {
          const pdf = await readPdfBase64(pdfPath);
          this.respond(id, { structuredContent: pdf, content: [] });
        } catch (e) {
          console.error('[read_pdf] failed:', e);
          this.respond(id, {
            structuredContent: { mime_type: 'application/pdf', data_base64: '' },
            content: [],
          });
        }
        break;
      }

      case 'submit_review': {
        const approved = !!args.approved;
        const reason = (args.reason as string) ?? '';
        this.respond(id, {
          structuredContent: {
            status: 'ok',
            review_id: args.review_id,
            approved,
          },
          content: [],
          isError: false,
        });
        this.onReviewSubmitted({ approved, reason });
        break;
      }

      default:
        this.respond(id, {
          structuredContent: { status: 'ok', mock: true, tool: name },
          content: [],
        });
        break;
    }
  }

  // ---- 发送响应 ----

  private respond(id: number, result: unknown): void {
    this.post({ jsonrpc: '2.0', id, result });
  }

  private respondError(id: number, message: string): void {
    this.post({ jsonrpc: '2.0', id, error: { code: -32000, message } });
  }

  // ---- 主动发送通知（驱动 UI） ----

  /** 发送工具入参。 */
  sendToolInput(toolName: string, args: Record<string, unknown>): void {
    this.post({
      jsonrpc: '2.0',
      method: 'ui/notifications/tool-input',
      params: { toolName, args },
    });
    this.onLog({
      dir: 'host→ui',
      method: 'ui/notifications/tool-input',
      detail: `toolName=${toolName}`,
      ts: Date.now(),
    });
  }

  /** 发送进度通知（含 uiEvent 扩展字段）。 */
  sendProgress(step: {
    progress: number;
    total: number;
    message: string;
    uiEvent?: unknown;
  }): void {
    this.post({
      jsonrpc: '2.0',
      method: 'notifications/progress',
      params: {
        progress: step.progress,
        total: step.total,
        message: step.message,
        ...(step.uiEvent ? { uiEvent: step.uiEvent } : {}),
      },
    });
    this.onLog({
      dir: 'host→ui',
      method: 'notifications/progress',
      detail: `${step.progress}/${step.total} ${step.message}${
        step.uiEvent ? ` · uiEvent keys=${Object.keys(step.uiEvent as object).join(',')}` : ''
      }`,
      ts: Date.now(),
    });
  }

  /** 发送审核态通知（review_pending + final_result + review_id）。 */
  sendReviewPending(reviewId: string, toolName: string, finalResult: Record<string, unknown>): void {
    this.post({
      jsonrpc: '2.0',
      method: 'notifications/progress',
      params: {
        progress: 1,
        total: 1,
        message: '提取完成，等待审核',
        uiEvent: {
          review_pending: true,
          review_id: reviewId,
          tool_name: toolName,
          final_result: finalResult,
        },
      },
    });
    this.onLog({
      dir: 'host→ui',
      method: 'notifications/progress',
      detail: 'review_pending=true',
      ts: Date.now(),
    });
  }

  /** 发送工具结果。isError=true 时用 errorText 携带具体错误文本（缺省回退'工具执行失败'）。 */
  sendToolResult(result: unknown, isError = false, errorText?: string): void {
    this.post({
      jsonrpc: '2.0',
      method: 'ui/notifications/tool-result',
      params: {
        ...(isError
          ? { content: [{ type: 'text', text: errorText ?? '工具执行失败' }], isError: true }
          : { structuredContent: result }),
      },
    });
    this.onLog({
      dir: 'host→ui',
      method: 'ui/notifications/tool-result',
      detail: isError ? 'isError=true' : `structuredContent keys=${Object.keys((result as object) ?? {}).join(',') || '(object)'}`,
      ts: Date.now(),
    });
  }

  // ---- 底层 ----

  private post(message: object): void {
    if (this.iframe && this.iframe.contentWindow) {
      this.iframe.contentWindow.postMessage(message, '*');
    }
  }
}

/** 安全序列化（截断超长内容）。 */
function safeStringify(value: unknown): string {
  if (value === undefined) return '(undefined)';
  try {
    let s = JSON.stringify(value);
    if (!s) return '(empty)';
    if (s.length > 400) s = s.slice(0, 400) + '…';
    return s;
  } catch {
    return String(value);
  }
}