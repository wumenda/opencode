/**
 * MCP Apps postMessage 客户端（core 层）。
 *
 * 本模块实现 SEP-1865 (io.modelcontextprotocol/ui) 的 iframe 侧通信：
 *   1. ui/initialize 握手 -> 获取 host context（theme / capabilities）
 *   2. ui/notifications/initialized 通知 host 握手完成
 *   3. 接收 ui/notifications/tool-input（工具入参，如 image_path）
 *   4. 接收 ui/notifications/tool-result（工具返回结果，含 structuredContent）
 *   5. tools/call 反向调用 host 上其它 MCP 工具
 *
 * core 层提供通用通信能力，不感知业务语义（如 review / topology）。
 * 业务模式通过 patterns/ 下的扩展点注入：
 *   - registerProgressEventResolver：注册 uiEvent -> 事件名解析器
 *
 * MCP server 只提供工具，不管理 session、不提供 HTTP 端点。
 * 所有数据通过 postMessage 从 host 获取。
 */

import { useEffect, useSyncExternalStore } from 'react';
import type { SessionEvent } from '@/core/types';

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------

/** JSON-RPC 2.0 消息。 */
interface JsonRpcMessage {
  jsonrpc: '2.0';
  id?: number | string;
  method?: string;
  params?: unknown;
  result?: unknown;
  error?: { code: number; message: string; data?: unknown };
}

/** host context（ui/initialize 响应）。 */
export interface HostContext {
  protocolVersion?: string;
  theme?: 'light' | 'dark' | 'system';
  capabilities?: Record<string, unknown>;
  [k: string]: unknown;
}

/** 工具入参通知（ui/notifications/tool-input）。 */
export interface ToolInput {
  toolName?: string;
  args?: Record<string, unknown>;
  [k: string]: unknown;
}

/** 工具结果通知（ui/notifications/tool-result）。 */
export interface ToolResult {
  /** 结构化结果（工作流返回的 dict）。 */
  structuredContent?: Record<string, unknown>;
  /** 文本内容数组（fallback）。 */
  content?: Array<{ type: string; text?: string }>;
  isError?: boolean;
  [k: string]: unknown;
}

/** 进度通知（notifications/progress，host 可能转发）。
 *
 * 标准 MCP progress 通知只有 progress/total/message，但
 * ProgressNotificationParams 的 pydantic model_config = extra="allow"，
 * 因此后端可通过 _send_progress_with_data 携带一个结构化的 ``uiEvent``
 * 扩展字段，前端直接从 ``progress.uiEvent.<key>`` 读取逐步渲染所需数据。
 *
 * core 层不定义 uiEvent 的具体字段 -- 业务模式（如审核）在 patterns/ 下
 * 定义专用类型并通过 registerProgressEventResolver 注册事件名解析。
 */
export interface ProgressNotification {
  progressToken?: unknown;
  progress?: number;
  total?: number;
  message?: string;
  uiEvent?: Record<string, unknown>;
}

/** progress 事件名解析器：输入 uiEvent，返回事件名；不识别时返回 null。 */
export type ProgressEventResolver = (
  uiEvent: ProgressNotification['uiEvent'] | undefined,
) => string | null;

const progressEventResolvers = new Set<ProgressEventResolver>();

/**
 * 注册 progress 事件名解析器（业务模式在模块加载时调用）。
 *
 * 事件名归属业务模式，core 不感知业务语义（如 review_pending/final_result）；
 * 未注册任何解析器或均不识别时，事件名默认 'progress'。
 *
 * @returns 注销函数（测试隔离用）。
 */
export function registerProgressEventResolver(
  resolver: ProgressEventResolver,
): () => void {
  progressEventResolvers.add(resolver);
  return () => progressEventResolvers.delete(resolver);
}

/** App 连接状态。 */
export type AppStatus =
  | 'initializing' // 等待 ui/initialize 握手
  | 'ready' // 握手完成，等待 tool-input/result
  | 'processing' // 收到 tool-input，等待 tool-result
  | 'result_ready' // 收到 tool-result
  | 'error';

// ---------------------------------------------------------------------------
// McpApp 单例
// ---------------------------------------------------------------------------

interface AppStore {
  status: AppStatus;
  hostContext: HostContext | null;
  toolInput: ToolInput | null;
  toolResult: ToolResult | null;
  progress: ProgressNotification | null;
  progressEvents: SessionEvent[];
  error: string | null;
  /** 反向工具调用（tools/call）是否进行中。 */
  callToolLoading: boolean;
}

class McpApp {
  private nextId = 1;
  private pending = new Map<
    number,
    { resolve: (v: unknown) => void; reject: (e: Error) => void }
  >();
  /** host 的 origin，握手前为 '*'，握手后锁定为实际 origin。 */
  private hostOrigin: string = '*';

  private store: AppStore = {
    status: 'initializing',
    hostContext: null,
    toolInput: null,
    toolResult: null,
    progress: null,
    progressEvents: [],
    error: null,
    callToolLoading: false,
  };

  private listeners = new Set<() => void>();
  private initStarted = false;
  /** 在途的 tools/call 请求数（callToolLoading 由它派生，支持并发调用）。 */
  private callToolPendingCount = 0;

  constructor() {
    if (typeof window !== 'undefined' && window.parent) {
      window.addEventListener('message', this.onMessage);
    }
  }

  // ---- 外部 store 订阅（useSyncExternalStore） ----

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = (): AppStore => this.store;

  private emit(): void {
    // 浅拷贝触发 React 重渲染
    this.store = { ...this.store };
    this.listeners.forEach((l) => l());
  }

  // ---- postMessage 收发 ----

  private onMessage = (event: MessageEvent): void => {
    // 安全校验：握手完成后，只接受来自 hostOrigin 的消息
    if (this.hostOrigin !== '*' && event.origin !== this.hostOrigin) return;

    const msg: JsonRpcMessage = event.data;
    if (!msg || typeof msg !== 'object' || msg.jsonrpc !== '2.0') return;

    // 1) 响应：匹配 pending 请求
    if (msg.id != null && this.pending.has(Number(msg.id))) {
      // 首次收到 host 响应时锁定 origin
      if (this.hostOrigin === '*') {
        this.hostOrigin = event.origin;
      }
      const id = Number(msg.id);
      const p = this.pending.get(id)!;
      this.pending.delete(id);
      if (msg.error) {
        p.reject(new Error(msg.error.message || 'JSON-RPC error'));
      } else {
        p.resolve(msg.result);
      }
      return;
    }

    // 2) 通知：host -> app
    if (!msg.method) return;

    // 通知也更新 hostOrigin（host 可能在握手前发送通知）
    if (this.hostOrigin === '*' && event.origin !== 'null' && event.origin !== '') {
      this.hostOrigin = event.origin;
    }

    this.handleNotification(msg.method, msg.params);
  };

  private handleNotification(method: string, params: unknown): void {
    const p = (params ?? {}) as Record<string, unknown>;

    switch (method) {
      case 'ui/notifications/tool-input':
        // 新会话开始：清空上一会话的进度/结果/错误。
        // 否则旧 progress.uiEvent(如 review_id) 或旧 toolResult 残留，
        // 会导致 submitReview 用旧 review_id 提交、页面展示上一会话的数据。
        this.store = {
          ...this.store,
          toolInput: p as unknown as ToolInput,
          status: 'processing',
          progress: null,
          progressEvents: [],
          toolResult: null,
          error: null,
        };
        this.emit();
        break;

      case 'ui/notifications/tool-result': {
        const result = p as unknown as ToolResult;
        // 后端返回 status === 'failed' 视为提取失败（走 error 态）
        const isErr = result.isError || this.isFailedResult(result);
        this.store = {
          ...this.store,
          toolResult: result,
          status: isErr ? 'error' : 'result_ready',
          error: isErr ? this.extractErrorText(result) : null,
        };
        this.emit();
        break;
      }

      case 'notifications/progress': {
        const incoming = p as unknown as ProgressNotification;
        const incomingUiEvent = incoming.uiEvent;

        // 自定义合并：partial_page_graphs 按 page_index 合并（同页覆盖，新页追加）
        const prevGraphs =
          (this.store.progress?.uiEvent?.partial_page_graphs as Array<{
            page_index?: number;
            page_label?: string;
            pfd_drawing?: Record<string, unknown>;
          }>) ?? [];
        const incomingGraphs =
          (incomingUiEvent?.partial_page_graphs as typeof prevGraphs) ?? [];
        const mergedGraphs = [...prevGraphs];
        for (const pg of incomingGraphs) {
          const idx = mergedGraphs.findIndex(
            (m) => m.page_index === pg.page_index,
          );
          if (idx >= 0) mergedGraphs[idx] = pg; // 同页覆盖（节点->节点+边）
          else mergedGraphs.push(pg); // 新页追加
        }

        // 累积合并 image_paths / image_infos（按 path 去重）：
        // 后续不带这些字段的通知不应清掉已存数据
        const prevImagePaths =
          (this.store.progress?.uiEvent?.image_paths as string[]) ?? [];
        const prevImageInfos =
          (this.store.progress?.uiEvent?.image_infos as Array<{
            path?: string;
            width?: number;
            height?: number;
          }>) ?? [];
        const mergedImagePaths = [...prevImagePaths];
        const mergedImageInfos = [...prevImageInfos];
        const incomingImagePaths =
          (incomingUiEvent?.image_paths as string[]) ?? [];
        const incomingImageInfos =
          (incomingUiEvent?.image_infos as typeof prevImageInfos) ?? [];
        for (let i = 0; i < incomingImagePaths.length; i++) {
          const ip = incomingImagePaths[i];
          if (!mergedImagePaths.includes(ip)) {
            mergedImagePaths.push(ip);
            mergedImageInfos.push(incomingImageInfos[i] ?? { path: ip });
          }
        }

        // 把 progress 通知转成 SessionEvent 累积到 progressEvents
        const ev: SessionEvent = {
          event: inferEventType(incoming, incomingUiEvent),
          data: {
            message: incoming.message ?? '',
            progress: incoming.progress,
            total: incoming.total,
            page_count: mergedGraphs.length,
            ...(incomingUiEvent?.cross_page_edges
              ? {
                  edge_count: (
                    incomingUiEvent.cross_page_edges as Array<unknown>
                  ).length,
                }
              : {}),
            ...(incomingUiEvent ?? {}), // 展开全部 uiEvent 字段
          },
          timestamp: Date.now() / 1000,
        };
        const prevEvents = this.store.progressEvents;
        // 去重：相同 message + progress + event 类型视为重复（host 可能重发）
        const isDup =
          prevEvents.length > 0 &&
          prevEvents[prevEvents.length - 1].data.message === ev.data.message &&
          prevEvents[prevEvents.length - 1].data.progress === ev.data.progress &&
          prevEvents[prevEvents.length - 1].event === ev.event;
        const nextEvents = isDup ? prevEvents : [...prevEvents, ev];

        // 替换式更新 partial_matched_sections / partial_pdf_path / partial_total_pages
        // Phase 1 一次性给出完整章节列表，无需累积合并
        const prevUiEvent = this.store.progress?.uiEvent;
        const mergedPartialSections = incomingUiEvent?.partial_matched_sections
          ? incomingUiEvent.partial_matched_sections
          : prevUiEvent?.partial_matched_sections;
        const mergedPartialPdfPath = incomingUiEvent?.partial_pdf_path
          ? incomingUiEvent.partial_pdf_path
          : prevUiEvent?.partial_pdf_path;
        const mergedPartialTotalPages =
          incomingUiEvent?.partial_total_pages != null
            ? incomingUiEvent.partial_total_pages
            : prevUiEvent?.partial_total_pages;

        this.store = {
          ...this.store,
          progress: {
            ...incoming,
            uiEvent: {
              ...prevUiEvent,
              ...incomingUiEvent,
              partial_page_graphs: mergedGraphs,
              image_paths: mergedImagePaths,
              image_infos: mergedImageInfos,
              partial_matched_sections: mergedPartialSections,
              partial_pdf_path: mergedPartialPdfPath,
              partial_total_pages: mergedPartialTotalPages,
            },
          },
          progressEvents: nextEvents,
        };
        this.emit();
        break;
      }

      case 'ui/resource-teardown':
        // host 即将卸载 iframe；无需处理
        break;

      default:
        // 忽略未知通知
        break;
    }
  }

  /** 后端返回 status === 'failed' 视为提取失败（走 error 态，UI 弹出失败提示）。 */
  private isFailedResult(result: ToolResult): boolean {
    const sc = (result.structuredContent ?? {}) as Record<string, unknown>;
    return sc.status === 'failed';
  }

  private extractErrorText(result: ToolResult): string {
    const sc = (result.structuredContent ?? {}) as Record<string, unknown>;
    // 优先从 structuredContent 中的 errors / warnings 提取（status=failed 时后端写入）
    const errs = sc.errors;
    if (Array.isArray(errs) && errs.length > 0) return errs.join('\n');
    if (typeof errs === 'string' && errs) return errs;
    const warns = sc.warnings;
    if (Array.isArray(warns) && warns.length > 0) return warns.join('\n');
    if (typeof warns === 'string' && warns) return warns;
    if (Array.isArray(result.content)) {
      const text = result.content
        .map((c) => c.text)
        .filter(Boolean)
        .join('\n');
      if (text) return text;
    }
    return '工具执行失败';
  }

  private send(message: object): void {
    if (window.parent) {
      window.parent.postMessage(message, this.hostOrigin);
    }
  }

  private sendRequest(method: string, params: object): Promise<unknown> {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.send({ jsonrpc: '2.0', id, method, params });
      // 30s 超时
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          reject(new Error(`${method} 请求超时`));
        }
      }, 30000);
    });
  }

  private sendNotification(method: string, params: object): void {
    this.send({ jsonrpc: '2.0', method, params });
  }

  // ---- 公开 API ----

  /** 发起 ui/initialize 握手（幂等，只执行一次）。 */
  async initialize(): Promise<HostContext> {
    if (this.initStarted) return this.store.hostContext ?? {};
    this.initStarted = true;

    try {
      const result = (await this.sendRequest('ui/initialize', {
        protocolVersion: '2025-06-18',
        appInfo: { name: 'pfd-topology-review', version: '1.0.0' },
        appCapabilities: {},
      })) as HostContext;

      this.store = {
        ...this.store,
        hostContext: result,
        status: 'ready',
      };
      this.emit();

      // 通知 host 握手完成
      this.sendNotification('ui/notifications/initialized', {});
      return result;
    } catch (e) {
      this.store = {
        ...this.store,
        status: 'error',
        error: e instanceof Error ? e.message : String(e),
      };
      this.emit();
      throw e;
    }
  }

  /** 反向调用 host 上的 MCP 工具。 */
  async callTool(
    name: string,
    args: Record<string, unknown>,
  ): Promise<ToolResult> {
    // 计数式 loading：并发调用全部结束后才熄灭，避免互相覆盖
    this.callToolPendingCount += 1;
    this.store = { ...this.store, callToolLoading: true };
    this.emit();
    try {
      return (await this.sendRequest('tools/call', {
        name,
        arguments: args,
      })) as ToolResult;
    } finally {
      this.callToolPendingCount -= 1;
      this.store = {
        ...this.store,
        callToolLoading: this.callToolPendingCount > 0,
      };
      this.emit();
    }
  }

  /** 请求取消当前工具调用（通知 host）。best-effort，无响应等待。 */
  cancelCurrentTool(): void {
    this.sendNotification('notifications/cancelled', {});
  }
}

// ---------------------------------------------------------------------------
// 单例
// ---------------------------------------------------------------------------

export const mcpApp = new McpApp();

// ---------------------------------------------------------------------------
// React Hooks
// ---------------------------------------------------------------------------

/** 订阅 MCP App 全局状态。 */
export function useMcpApp(): AppStore {
  return useSyncExternalStore(mcpApp.subscribe, mcpApp.getSnapshot, mcpApp.getSnapshot);
}

/** 订阅工具入参（image_path 等）。 */
export function useToolInput(): ToolInput | null {
  return useMcpApp().toolInput;
}

/** 订阅反向工具调用（tools/call）是否进行中。 */
export function useCallToolLoading(): boolean {
  return useMcpApp().callToolLoading;
}

/**
 * 订阅工具结果，并归一化为 final_result 结构。
 *
 * toolResult 优先。阻塞期(审核等待)toolResult 为 null 时，
 * 用 progress.uiEvent.final_result 兜底（审核工具推送的完整结果）。
 */
export function useNormalizedToolResult(): {
  finalResult: Record<string, unknown> | null;
  rawResult: ToolResult | null;
  isError: boolean;
} {
  const app = useMcpApp();
  const { toolResult } = app;

  // 业务数据优先取 progress.uiEvent.final_result：审核工具会在阻塞前把「完整提取结果」
  // 推送到该字段；tool-result 的 structuredContent 只是轻量摘要（output_file + 元信息），
  // 不含业务数据，若作为渲染源会在审核通过后把页面数据清空。因此 final_result 优先，
  // structuredContent 仅作为兜底（无 final_result 时的单次/失败场景）。
  const fromProgress = app.progress?.uiEvent?.final_result as
    | Record<string, unknown>
    | undefined;
  const raw = fromProgress ?? toolResult?.structuredContent ?? null;

  if (!raw) {
    return { finalResult: null, rawResult: toolResult, isError: !!toolResult?.isError };
  }

  const finalResult = normalizeResult(raw);
  // 失败判定以 tool-result 的最终态为准（审核驳回/超时时 final_result 仍是完整结果，
  // 但其 structuredContent.status 为 failed）。
  const sc = (toolResult?.structuredContent ?? {}) as Record<string, unknown>;
  const statusFailed = sc.status === 'failed' || (raw.status as string) === 'failed';
  return { finalResult, rawResult: toolResult, isError: !!toolResult?.isError || statusFailed };
}

/** 把不同工作流的返回结构归一化为页面期望的 final_result。
 *
 * pfd_topology 工具返回 { pfd_drawing, topology, ... }（单页），
 * MultiPageTopologyPage 期望 final_result.page_graphs。
 * 兼容旧版单页返回：自动包成 page_graphs[0]。
 */
function normalizeResult(raw: Record<string, unknown>): Record<string, unknown> {
  // pfd_topology：单页，有 pfd_drawing 但无 page_graphs
  if (raw.pfd_drawing && !raw.page_graphs) {
    const drawing = raw.pfd_drawing as Record<string, unknown>;
    return {
      ...raw,
      page_graphs: [
        {
          page_index: 0,
          page_label: '第 1 页',
          pfd_drawing: drawing,
        },
      ],
    };
  }
  return raw;
}

/**
 * 在应用启动时发起 ui/initialize 握手。
 * 放在 App 根组件 useEffect 中调用。
 */
export function useMcpInitialize(): void {
  useEffect(() => {
    mcpApp.initialize().catch((e) => {
      // 错误已写入 store，这里只防止 unhandled rejection
      console.error('[mcpApp] initialize failed:', e);
    });
  }, []);
}

// ---------------------------------------------------------------------------
// 辅助纯函数
// ---------------------------------------------------------------------------

/** 根据 progress 的 uiEvent 内容推断事件类型（用于事件时间线展示）。
 *
 * 事件名首先由业务模式注册的解析器决定（见 registerProgressEventResolver）；
 * 然后回退到拓扑工具的默认推断逻辑。
 */
function inferEventType(
  incoming: ProgressNotification,
  uiEvent?: ProgressNotification['uiEvent'],
): string {
  // 1. 业务模式注册的解析器优先
  for (const resolver of progressEventResolvers) {
    const type = resolver(uiEvent);
    if (type) return type;
  }
  // 2. Server 显式事件类型（如 chapter_extracted / expert_complete）
  const explicitType = uiEvent?.event_type;
  if (typeof explicitType === 'string' && explicitType) return explicitType;
  // 3. 拓扑工具默认推断
  if (uiEvent?.global_graph) return 'topology_extracted';
  if (uiEvent?.cross_page_edges) return 'pd_topology_extracted';
  if (uiEvent?.partial_page_graphs) return 'drawing_info_extracted';
  if (incoming.message?.includes('PDF')) return 'pdf_parsed';
  return 'stage_update';
}
