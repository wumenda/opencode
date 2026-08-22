/**
 * 多页 PFD 拓扑审核页（替代 multi_page_topology.html）。
 *
 * 数据结构（pfd_topology / topology_overlay 任务的 final_result）：
 *   {
 *     page_graphs: [
 *       {
 *         page_index, page_label,
 *         pfd_drawing: { topology?: { equipment_nodes, boundary_nodes, edges }
 *                      | { topology: { ... } }, equipment_nodes?, ..., warnings? },
 *         image_url?
 *       }
 *     ],
 *     global_graph?: {
 *       cross_page_edges?: [{ from_node_id: "p0_xxx", from_page_index,
 *                             to_node_id, to_page_index, match_reason }],
 *       edges?: [{ source_node_id, source_node_pageindex, ..., metadata: { cross_page_link } }]
 *     },
 *     warnings?: string[]
 *   }
 *
 * 编辑模式：
 *   - global：所有页平铺在单画布上，跨页连接作为可编辑边（带折点）
 *   - single：仅当前页，pageOffset={0,0}
 * 切换模式时通过 key 强制 remount TopologyEditor（丢弃撤销历史）。
 * 提交时按当前模式分别用 rfToPfdPage / rfToCrossLinks 反归一化回原结构。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Node, Edge } from '@xyflow/react';
import { Layout } from '@/components/Layout';
import { ProgressBanner } from '@/components/ProgressBanner';
import { ReviewToolbar } from '@/components/ReviewToolbar';
import { JsonDrawer } from '@/components/JsonDrawer';
import { ErrorBanner } from '@/components/ErrorBanner';
import { useToast } from '@/components/Toast';
import { useMcpApp, useNormalizedToolResult, useToolInput } from '@/core/mcpApp';
import { useReviewStatus, submitReview } from '@/patterns/review';
import { useSourceImages } from '@/patterns/image';
import {
  TopologyEditor,
  type TopologyEditorHandle,
} from '@/components/topology/TopologyEditor';
import {
  PFD_NODE_FIELDS,
  PFD_EDGE_FIELDS,
} from '@/components/topology/PropertyPanel';
import {
  pfdPageToRF,
  crossLinksToRF,
  rfToPfdPage,
  rfToCrossLinks,
  type PageLayout,
  type CrossLink,
} from '@/components/topology/topologyAdapters';

// ===================== 类型 =====================

interface PfdDrawing {
  topology?: unknown;
  equipment_nodes?: Array<Record<string, unknown>>;
  boundary_nodes?: Array<Record<string, unknown>>;
  edges?: Array<Record<string, unknown>>;
  warnings?: string[];
  [k: string]: unknown;
}

interface PageGraph {
  page_index?: number;
  page_label?: string;
  pfd_drawing?: PfdDrawing;
  image_url?: string;
  [k: string]: unknown;
}

interface CrossPageEdge {
  from_node_id?: string;
  from_page_index?: number;
  to_node_id?: string;
  to_page_index?: number;
  match_reason?: string;
  bend_points?: Array<[number, number]>;
  [k: string]: unknown;
}

interface GlobalGraph {
  cross_page_edges?: CrossPageEdge[];
  edges?: Array<{
    source_node_id?: string;
    source_node_pageindex?: number;
    target_node_id?: string;
    target_node_pageindex?: number;
    metadata?: { cross_page_link?: boolean; match_method?: string; equipment_tag?: string };
  }>;
  [k: string]: unknown;
}

interface MultiPageResult {
  page_graphs?: PageGraph[];
  global_graph?: GlobalGraph;
  expert_outputs?: Record<string, unknown>;
  warnings?: string[];
  [k: string]: unknown;
}

// ===================== 常量与工具 =====================

/** 画布长边基准像素（短边按图片宽高比缩放）。 */
const CANVAS_LONG_EDGE = 1200;
/** 默认画布尺寸（图片尺寸未就绪时回退）。 */
const DEFAULT_CANVAS_W = 1200;
const DEFAULT_CANVAS_H = 1600;
/** 多页平铺时页与页之间的间距。 */
const GAP = 80;
/** 多页网格列数上限。 */
const COLS = 5;

/** 解析 page-aware id "p0_xxx" → { pageIndex: 0, nodeId: "xxx" }。 */
function parsePageAwareId(id: unknown): { pageIndex: number; nodeId: string } | null {
  const m = String(id ?? '').match(/^p(\d+)_(.+)$/);
  if (!m) return null;
  return { pageIndex: parseInt(m[1], 10), nodeId: m[2] };
}

/** 根据图片尺寸计算画布宽高（长边 = CANVAS_LONG_EDGE，保持宽高比）。 */
function canvasSizeFromImage(imgW?: number, imgH?: number): { w: number; h: number } {
  if (imgW && imgH && imgW > 0 && imgH > 0) {
    const longEdge = Math.max(imgW, imgH);
    const scale = CANVAS_LONG_EDGE / longEdge;
    return { w: Math.round(imgW * scale), h: Math.round(imgH * scale) };
  }
  return { w: DEFAULT_CANVAS_W, h: DEFAULT_CANVAS_H };
}

/** 计算页 i 在全局网格中的 pageOffset。 */
function pageOffsetFor(pageIndex: number, canvasW: number, canvasH: number): { x: number; y: number } {
  const col = pageIndex % COLS;
  const row = Math.floor(pageIndex / COLS);
  return { x: col * (canvasW + GAP), y: row * (canvasH + GAP) };
}

/** 从 global_graph 提取跨页连接（统一格式）。 */
function extractCrossPageLinks(gg?: GlobalGraph): CrossLink[] {
  if (!gg) return [];
  const out: CrossLink[] = [];

  if (Array.isArray(gg.cross_page_edges)) {
    for (const link of gg.cross_page_edges) {
      const fromParsed = parsePageAwareId(link.from_node_id);
      const toParsed = parsePageAwareId(link.to_node_id);
      if (!fromParsed || !toParsed) continue;
      const reason = link.match_reason || '';
      const label = reason.includes(':') ? reason.split(':').slice(1).join(':') : reason;
      out.push({
        fromPage: link.from_page_index ?? fromParsed.pageIndex,
        fromNode: fromParsed.nodeId,
        toPage: link.to_page_index ?? toParsed.pageIndex,
        toNode: toParsed.nodeId,
        label,
        reason,
        bendPoints: (link.bend_points ?? []).map(([x, y]) => ({ x, y })),
      });
    }
    return out;
  }

  if (Array.isArray(gg.edges)) {
    for (const e of gg.edges) {
      if (!e.metadata?.cross_page_link) continue;
      const fromParsed = parsePageAwareId(e.source_node_id);
      const toParsed = parsePageAwareId(e.target_node_id);
      if (!fromParsed || !toParsed) continue;
      const tag = e.metadata.equipment_tag;
      out.push({
        fromPage: e.source_node_pageindex ?? fromParsed.pageIndex,
        fromNode: fromParsed.nodeId,
        toPage: e.target_node_pageindex ?? toParsed.pageIndex,
        toNode: toParsed.nodeId,
        label: tag || e.metadata.match_method || 'cross_page',
      });
    }
  }

  return out;
}

/** 把新的 cross links 写回 global_graph（保留其它字段与用户编辑的折点）。 */
function updateGlobalGraphCrossLinks(
  gg: GlobalGraph | undefined,
  links: CrossLink[],
): GlobalGraph {
  // 原始边按 from|to 建索引，重写时保留 confidence 等未知字段
  const origByKey = new Map<string, CrossPageEdge>();
  for (const e of gg?.cross_page_edges ?? []) {
    origByKey.set(`${e.from_node_id}|${e.to_node_id}`, e);
  }
  const cross_page_edges: CrossPageEdge[] = links.map((l) => {
    const key = `p${l.fromPage}_${l.fromNode}|p${l.toPage}_${l.toNode}`;
    const orig = origByKey.get(key) ?? {};
    return {
      ...orig,
      from_node_id: `p${l.fromPage}_${l.fromNode}`,
      from_page_index: l.fromPage,
      to_node_id: `p${l.toPage}_${l.toNode}`,
      to_page_index: l.toPage,
      // 优先写回原始完整值，避免截断展示值污染
      match_reason: l.reason ?? l.label,
      // 用户编辑的折点（原始结构无此字段时为新增扩展字段，空折点不写）
      ...(l.bendPoints && l.bendPoints.length > 0
        ? { bend_points: l.bendPoints.map((b) => [b.x, b.y]) }
        : {}),
    };
  });
  if (!gg) return { cross_page_edges };
  // 若原结构用的是 edges[]+metadata.cross_page_link，也同步重写 cross_page_edges
  return { ...gg, cross_page_edges };
}

// ===================== 组件 =====================

type EditMode = 'global' | 'single';

export function MultiPageTopologyPage() {
  const app = useMcpApp();
  const { finalResult: rawFinalResult, isError } = useNormalizedToolResult();
  const status = useReviewStatus();
  const progressError = isError ? app.error : null;
  // 按页加载图片：每页 image_path 独立调用 read_image，避免所有页共用同一张底图
  const imagePaths = useMemo(() => (app.progress?.uiEvent?.image_paths as string[]) ?? [], [app.progress?.uiEvent?.image_paths]);
  const { urls: pageImageUrls } = useSourceImages(imagePaths);
  const { toast, show } = useToast();
  const [submitting, setSubmitting] = useState(false);
  // 提取失败时弹出 toast 失败提示（去重，仅弹一次）
  const shownErrorRef = useRef<string | null>(null);
  useEffect(() => {
    if (progressError && shownErrorRef.current !== progressError) {
      shownErrorRef.current = progressError;
      show(`提取失败：${progressError}`, 'error');
    }
  }, [progressError, show]);
  // 审核已提交后置为 true，禁用通过/驳回按钮避免重复提交（review_id 已失效）
  const [submitted, setSubmitted] = useState(false);
  const [resultMessage, setResultMessage] = useState<{
    type: 'success' | 'error';
    text: string;
  } | null>(null);
  const [activePageIndex, setActivePageIndex] = useState(0);
  const [mode, setMode] = useState<EditMode>('global');
  const [showGrid, setShowGrid] = useState(true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const editorRef = useRef<TopologyEditorHandle>(null);

  // 本地编辑副本（审核阶段用户编辑后覆盖 final_result；切换 mode/page 前快照写入）
  const [editedData, setEditedData] = useState<MultiPageResult | null>(null);

  const canSubmit = status === 'waiting_review';
  const isTerminal = status === 'completed' || status === 'error';
  const isExtracting = !canSubmit && !isTerminal;

  // tool 入参（pfd_topology 提取参数透出到侧栏）
  const toolInput = useToolInput();
  const args = (toolInput?.args ?? {}) as Record<string, unknown>;
  // 页码基准：后端 image_paths 按渲染顺序（相对下标）排列，
  // 而 page_graphs/page_index 用绝对页码（start_page + idx）。
  // 此值用于两套索引的换算：绝对页码 - startPage = 图片数组下标。
  const startPage = useMemo(() => {
    const sp = Number(args.start_page);
    return Number.isFinite(sp) && sp > 0 ? Math.floor(sp) : 0;
  }, [args.start_page]);

  // final_result 就绪后作为审核数据（editedData 优先）
  const finalResult = (rawFinalResult ?? null) as MultiPageResult | null;
  const reviewData = editedData ?? finalResult;

  // pageGraphs：审核阶段用 final_result，提取阶段用 partial_page_graphs + image_paths 空占位合并
  const pageGraphs: PageGraph[] = useMemo(() => {
    if (reviewData?.page_graphs) return reviewData.page_graphs;
    const partial = (app.progress?.uiEvent?.partial_page_graphs ?? []) as PageGraph[];
    const imagePaths = app.progress?.uiEvent?.image_paths as string[] | undefined;
    const imageInfos = app.progress?.uiEvent?.image_infos as Array<{ path?: string; width?: number; height?: number }> | undefined;
    // 提取早期：用 image_paths 补齐尚未提取的页（空底图占位），与已提取页按 page_index 合并
    if (imagePaths && imagePaths.length > 0) {
      const byIdx = new Map<number, PageGraph>();
      imagePaths.forEach((path, idx) => {
        // 占位页改用绝对页码，与下方 partial 的 pg.page_index 同一坐标体系，避免 start_page>0 时幻影空页
        const absIdx = startPage + idx;
        byIdx.set(absIdx, {
          page_index: absIdx,
          page_label: `第 ${absIdx + 1} 页`,
          pfd_drawing: {
            page_index: absIdx,
            image_path: path,
            image_info: imageInfos?.[idx] ?? { path },
            drawing_info: { drawing_type: 'PFD' },
            topology: { equipment_nodes: [], boundary_nodes: [], edges: [] },
          },
        });
      });
      // 已提取的 partial 覆盖对应页（节点/边叠加到空底图上）
      for (const pg of partial) {
        const idx = pg.page_index ?? 0;
        byIdx.set(idx, pg);
      }
      return Array.from(byIdx.values()).sort(
        (a, b) => (a.page_index ?? 0) - (b.page_index ?? 0),
      );
    }
    return partial;
  }, [reviewData, app.progress?.uiEvent?.partial_page_graphs, app.progress?.uiEvent?.image_paths, app.progress?.uiEvent?.image_infos, startPage]);

  // 单页编辑模式：键盘左右键切换上一页/下一页（switchPage 定义后注册，见下方）

  const globalGraph = reviewData?.global_graph;
  const crossLinks = useMemo(() => extractCrossPageLinks(globalGraph), [globalGraph]);

  // 顶层 warnings + 每页 warnings 合并去重
  const warnings = useMemo(() => {
    if (!reviewData) return [];
    const seen = new Set<string>();
    const out: string[] = [];
    const push = (w?: string) => {
      if (!w || seen.has(w)) return;
      seen.add(w);
      out.push(w);
    };
    (reviewData.warnings || []).forEach(push);
    pageGraphs.forEach((pg) => {
      const w = pg.pfd_drawing?.warnings;
      if (Array.isArray(w)) w.forEach(push);
    });
    return out;
  }, [reviewData, pageGraphs]);

  const activePage = pageGraphs[activePageIndex];
  const activePageIndexValue = activePage?.page_index ?? activePageIndex;

  // 每页画布尺寸（从图片实际宽高比计算，保证 bbox 归一化坐标映射准确）
  const imageSizes = useMemo(
    () => ((app.progress?.uiEvent?.image_infos as Array<{ width?: number; height?: number }>) ?? []).map((i) => [i.width ?? 0, i.height ?? 0] as [number, number]),
    [app.progress?.uiEvent?.image_infos],
  );
  const canvasDims = useMemo(() => {
    return pageGraphs.map((pg, i) => {
      const idx = pg.page_index ?? i;
      // image_infos 按渲染顺序排列：绝对页码需减 startPage 才是数组下标；越界时 undefined → 默认尺寸
      const sz = imageSizes?.[idx - startPage];
      return canvasSizeFromImage(sz?.[0], sz?.[1]);
    });
  }, [pageGraphs, imageSizes, startPage]);
  /** 获取指定页的画布尺寸（越界回退默认值）。 */
  const canvasFor = useCallback(
    (pageIdx: number) => canvasDims.find((_, i) => (pageGraphs[i]?.page_index ?? i) === pageIdx) ?? { w: DEFAULT_CANVAS_W, h: DEFAULT_CANVAS_H },
    [canvasDims, pageGraphs],
  );
  // 全局网格用所有页中的最大宽高作为单元格尺寸
  const gridW = canvasDims.reduce((m, d) => Math.max(m, d.w), DEFAULT_CANVAS_W);
  const gridH = canvasDims.reduce((m, d) => Math.max(m, d.h), DEFAULT_CANVAS_H);

  // ===================== 编辑器初始数据 =====================

  // 全局模式：所有页平铺 + 跨页边
  const globalInitial = useMemo(() => {
    if (pageGraphs.length === 0) return { nodes: [] as Node[], edges: [] as Edge[] };
    const allNodes: Node[] = [];
    const allEdges: Edge[] = [];
    pageGraphs.forEach((pg, i) => {
      const idx = pg.page_index ?? i;
      const offset = pageOffsetFor(idx, gridW, gridH);
      const dims = canvasDims[i] ?? { w: DEFAULT_CANVAS_W, h: DEFAULT_CANVAS_H };
      const layout: PageLayout = {
        pageIndex: idx,
        offsetX: offset.x,
        offsetY: offset.y,
        canvasW: dims.w,
        canvasH: dims.h,
        // 此处 pageImageUrls[i] 为数组下标对数组下标（pageGraphs 与 image_paths 均按渲染顺序排列），本身对齐，无需换算 startPage
        imageUrl: pageImageUrls[i] ?? undefined,
        label: pg.page_label || `第 ${idx + 1} 页`,
      };
      const { nodes, edges } = pfdPageToRF(pg, layout);
      allNodes.push(...nodes);
      allEdges.push(...edges);
    });
    allEdges.push(...crossLinksToRF(crossLinks));
    return { nodes: allNodes, edges: allEdges };
  }, [pageGraphs, pageImageUrls, crossLinks, canvasDims, gridW, gridH]);

  // 单页模式：仅当前页
  const singleInitial = useMemo(() => {
    if (!activePage) return { nodes: [] as Node[], edges: [] as Edge[] };
    const idx = activePageIndexValue;
    const dims = canvasFor(idx);
    const layout: PageLayout = {
      pageIndex: idx,
      offsetX: 0,
      offsetY: 0,
      canvasW: dims.w,
      canvasH: dims.h,
      // pageImageUrls 按渲染顺序（相对下标）排列：绝对页码 activePageIndexValue 需减 startPage
      imageUrl: pageImageUrls[activePageIndexValue - startPage] ?? undefined,
      label: activePage.page_label || `第 ${idx + 1} 页`,
    };
    return pfdPageToRF(activePage, layout);
  }, [activePage, activePageIndexValue, pageImageUrls, canvasFor, startPage]);

  const initialNodes = mode === 'global' ? globalInitial.nodes : singleInitial.nodes;
  const initialEdges = mode === 'global' ? globalInitial.edges : singleInitial.edges;
  // 切换模式/页/数据源（partial→final）时强制 remount，丢弃撤销历史。
  // 不含 img/noimg 段：背景图异步加载完成后不重建画布（改由 TopologyEditor 内部同步 pageBg url），避免丢失用户编辑
  const usingFinal = !!reviewData;
  const editorKey = `${mode}-${activePageIndexValue}-${pageGraphs.length}-${usingFinal ? 'f' : 'p'}-${gridW}x${gridH}`;

  // ===================== 提交 =====================

  /** 构建编辑后的 edited_data：按当前模式分别反归一化。 */
  const buildEditedData = useCallback((): MultiPageResult | null => {
    if (!reviewData || !editorRef.current) return null;
    const { nodes: rfNodes, edges: rfEdges } = editorRef.current.getEdited();

    if (mode === 'global') {
      // 全局模式：每页用其 pageOffset 还原 + 重写跨页连接
      const newPageGraphs = pageGraphs.map((pg, i) => {
        const idx = pg.page_index ?? i;
        const offset = pageOffsetFor(idx, gridW, gridH);
        const dims = canvasDims[i] ?? { w: DEFAULT_CANVAS_W, h: DEFAULT_CANVAS_H };
        const newDrawing = rfToPfdPage(
          rfNodes,
          rfEdges,
          idx,
          offset,
          dims.w,
          dims.h,
          pg,
        );
        return { ...pg, pfd_drawing: newDrawing as PfdDrawing };
      });
      const newCrossLinks = rfToCrossLinks(rfEdges);
      const newGlobalGraph = updateGlobalGraphCrossLinks(globalGraph, newCrossLinks);
      return { ...reviewData, page_graphs: newPageGraphs, global_graph: newGlobalGraph };
    }

    // 单页模式：仅更新当前页，其它页保持原样
    const dims = canvasFor(activePageIndexValue);
    const newPageGraphs = pageGraphs.map((pg, i) => {
      const idx = pg.page_index ?? i;
      if (idx !== activePageIndexValue) return pg;
      const newDrawing = rfToPfdPage(
        rfNodes,
        rfEdges,
        idx,
        { x: 0, y: 0 },
        dims.w,
        dims.h,
        pg,
      );
      return { ...pg, pfd_drawing: newDrawing as PfdDrawing };
    });
    return { ...reviewData, page_graphs: newPageGraphs };
  }, [reviewData, mode, pageGraphs, globalGraph, activePageIndexValue, canvasDims, gridW, gridH, canvasFor]);

  // 切换 mode/page 前快照当前编辑到 editedData，避免丢弃（撤销栈随 remount 丢失，但数据不丢）
  const switchMode = useCallback((next: EditMode) => {
    if (next === mode) return;
    if (canSubmit && editorRef.current) {
      const snapshot = buildEditedData();
      if (snapshot) setEditedData(snapshot);
    }
    setMode(next);
  }, [mode, canSubmit, buildEditedData]);

  const switchPage = useCallback((nextIdx: number) => {
    if (nextIdx === activePageIndex) return;
    if (mode === 'single' && canSubmit && editorRef.current) {
      const snapshot = buildEditedData();
      if (snapshot) setEditedData(snapshot);
    }
    setActivePageIndex(nextIdx);
  }, [activePageIndex, mode, canSubmit, buildEditedData]);

  // 单页编辑模式：键盘左右键切换上一页/下一页
  useEffect(() => {
    if (mode !== 'single' || pageGraphs.length <= 1) return;
    const handler = (e: KeyboardEvent) => {
      // 已被其它处理器处理（如审边模式的 ArrowLeft/ArrowRight）则跳过
      if (e.defaultPrevented) return;
      const target = e.target as HTMLElement;
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) return;
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        switchPage(Math.max(0, activePageIndex - 1));
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        switchPage(Math.min(pageGraphs.length - 1, activePageIndex + 1));
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [mode, pageGraphs.length, activePageIndex, switchPage]);

  const handleSubmit = useCallback(
    async (approved: boolean, reason?: string) => {
      if (!reviewData) return;
      setSubmitting(true);
      setResultMessage(null);
      try {
        const edited = approved ? buildEditedData() : undefined;
        const resp = await submitReview('', {
          approved,
          edited_data: approved ? edited : undefined,
          reason,
        });
        setResultMessage({
          type: 'success',
          text: approved
            ? `审核通过：${resp.message}`
            : `已驳回：${reason || '未提供原因'}`,
        });
        setSubmitted(true);
        show('审核已提交', 'success');
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setResultMessage({ type: 'error', text: msg });
        show(`提交失败：${msg}`, 'error');
      } finally {
        setSubmitting(false);
      }
    },
    [reviewData, show, buildEditedData],
  );

  // ===================== 状态提示 =====================

  const statusHint = useMemo(() => {
    if (isTerminal) return reviewData ? '审核已完成' : (app.error || '已结束');
    if (canSubmit) return '审核数据已就绪，请审核后提交';
    if (isExtracting) {
      const done = pageGraphs.length;
      // 审核数据未就绪时以已推送的 image_paths 页数作为总页数，避免显示未知总数
      const total = finalResult?.page_graphs?.length ?? imagePaths.length;
      return total > 0 ? `提取进行中…（已完成 ${done}/${total} 页）` : '提取进行中…';
    }
    return '等待中…';
  }, [isTerminal, canSubmit, isExtracting, reviewData, app.error, finalResult, pageGraphs.length, imagePaths.length]);

  // ===================== 渲染 =====================

  return (
    <Layout>
      <div className="flex h-full flex-col">
        {!isExtracting && <ProgressBanner />}
        <div className="flex-1 overflow-hidden">
          {progressError && pageGraphs.length === 0 ? (
            /* 进度数据加载错误且无任何页面：整区显示错误 */
            <ErrorBanner error={progressError} onRetry={() => window.location.reload()} />
          ) : (
            /* 两栏：画布 | 侧栏（跨页连接 + 警告 + 全局信息）；侧栏可折叠 */
            <div
              className={`grid h-full overflow-hidden transition-[grid-template-columns] duration-300 ease-in-out grid-cols-1 grid-rows-[1fr_auto] lg:grid-rows-1 ${sidebarCollapsed ? '' : 'lg:grid-cols-[1fr_minmax(240px,300px)]'}`}
            >
              {/* 左：编辑器（全局/单页画布，提取中只读） */}
              <div className={`relative flex flex-col overflow-hidden ${sidebarCollapsed ? '' : 'border-b border-border lg:border-b-0 lg:border-r'}`}>
                {/* 顶部：模式切换 + 单页 tab + JSON */}
                <div className="flex items-center gap-2 overflow-x-auto border-b border-border bg-bg-2/40 px-3 py-1.5">
                  <div className="flex items-center gap-0.5 rounded-md border border-border bg-bg p-0.5">
                    <button
                      className={`rounded px-2.5 py-1 text-xs font-medium transition ${
                        mode === 'global'
                          ? 'bg-accent text-white'
                          : 'text-text-2 hover:bg-bg-3'
                      }`}
                      onClick={() => switchMode('global')}
                    >
                      全局视图
                    </button>
                    <button
                      className={`rounded px-2.5 py-1 text-xs font-medium transition ${
                        mode === 'single'
                          ? 'bg-accent text-white'
                          : 'text-text-2 hover:bg-bg-3'
                      }`}
                      onClick={() => switchMode('single')}
                    >
                      单页编辑
                    </button>
                  </div>

                  {mode === 'single' && (
                    <div className="flex items-center gap-0.5 overflow-x-auto rounded-md border border-border bg-bg/50 p-0.5">
                      {pageGraphs.map((pg, i) => {
                        const idx = pg.page_index ?? i;
                        const label = pg.page_label || `第 ${idx + 1} 页`;
                        const isActive = idx === activePageIndexValue;
                        return (
                          <button
                            key={idx}
                            className={`group flex items-center gap-1.5 whitespace-nowrap rounded px-2.5 py-1 text-xs font-medium transition-all ${
                              isActive
                                ? 'bg-accent text-white shadow-sm'
                                : 'text-text-2 hover:bg-bg-3/60 hover:text-text'
                            }`}
                            onClick={() => switchPage(i)}
                          >
                            <span
                              className={`flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-bold leading-none transition-colors ${
                                isActive
                                  ? 'bg-white/25 text-white'
                                  : 'bg-bg-3/80 text-text-3 group-hover:bg-bg-3 group-hover:text-text-2'
                              }`}
                            >
                              {idx + 1}
                            </span>
                            {label}
                          </button>
                        );
                      })}
                    </div>
                  )}

                  <div className="ml-auto flex items-center gap-1.5">
                    <JsonDrawer
                      data={activePage?.pfd_drawing || reviewData}
                      disabled={isExtracting}
                      trigger={
                        <button
                          type="button"
                          title="查看原始 JSON"
                          className="rounded-md border border-border bg-bg-2 px-2.5 py-1 text-[11px] text-text-2 transition hover:bg-bg-3 hover:text-text"
                        >
                          JSON
                        </button>
                      }
                    />
                    <button
                      type="button"
                      title="切换网格显示"
                      onClick={() => setShowGrid((v) => !v)}
                      className={`rounded-md border px-2.5 py-1 text-[11px] transition ${
                        showGrid
                          ? 'border-accent/50 bg-accent/10 text-accent'
                          : 'border-border bg-bg-2 text-text-2 hover:bg-bg-3'
                      }`}
                    >
                      网格
                    </button>
                    {sidebarCollapsed && (
                      <button
                        type="button"
                        title="展开侧栏"
                        onClick={() => setSidebarCollapsed(false)}
                        className="flex items-center gap-1 rounded-md border border-border bg-bg-2 px-2.5 py-1 text-[11px] text-text-2 transition hover:bg-bg-3 hover:text-text"
                      >
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M15 18l-6-6 6-6" />
                        </svg>
                        总览
                      </button>
                    )}
                    {isExtracting && (
                      <span className="flex items-center gap-1.5 text-[11px] text-text-3">
                        <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-accent" />
                        实时提取中
                      </span>
                    )}
                  </div>
                </div>

                {/* 画布（提取中只读，审核时可编辑）；无页面时叠加加载态 */}
                <div className="relative flex-1 bg-bg">
                  {pageGraphs.length === 0 && isExtracting && (
                    <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 text-text-3">
                      <svg className="h-7 w-7 animate-spin text-accent" viewBox="0 0 24 24" fill="none">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                      </svg>
                      <span className="text-xs">正在解析 PDF，等待首页…</span>
                    </div>
                  )}
                  <TopologyEditor
                    key={editorKey}
                    ref={editorRef}
                    initialNodes={initialNodes}
                    initialEdges={initialEdges}
                    nodeFields={PFD_NODE_FIELDS}
                    edgeFields={PFD_EDGE_FIELDS}
                    // readOnly 控制 UI（工具栏/底部提示）是否显示：终态或全局视图下隐藏。
                    // editable 控制节点/边数据操作：仅审核阶段的单页模式可编辑。
                    readOnly={isTerminal || mode === 'global'}
                    editable={mode === 'single' && canSubmit}
                    className="h-full"
                    showGrid={showGrid}
                    onNodeDoubleClick={(node) => {
                      // 全局视图下双击页面背景或页内节点 -> 进入该页单页编辑
                      const bgMatch = /^__pagebg_(\d+)$/.exec(node.id);
                      const nodeMatch = /^p(\d+)_/.exec(node.id);
                      const pageIdx = bgMatch ? parseInt(bgMatch[1], 10) : nodeMatch ? parseInt(nodeMatch[1], 10) : null;
                      if (pageIdx !== null) {
                        const idx = pageGraphs.findIndex((pg, i) => (pg.page_index ?? i) === pageIdx);
                        if (idx >= 0) {
                          switchMode('single');
                          switchPage(idx);
                        }
                      }
                    }}
                  />

                  {/* 单页模式左右箭头翻页 */}
                  {mode === 'single' && pageGraphs.length > 1 && (
                    <>
                      <button
                        type="button"
                        title="上一页"
                        disabled={activePageIndex <= 0}
                        onClick={() => switchPage(Math.max(0, activePageIndex - 1))}
                        className="group absolute left-3 top-1/2 z-20 flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full border border-border bg-bg-2/80 text-text shadow-card backdrop-blur-md transition-all hover:border-accent/50 hover:bg-accent hover:text-white disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:border-border disabled:hover:bg-bg-2/80 disabled:hover:text-text"
                      >
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" className="transition-transform group-hover:-translate-x-0.5">
                          <path d="M15 18l-6-6 6-6" />
                        </svg>
                      </button>
                      <button
                        type="button"
                        title="下一页"
                        disabled={activePageIndex >= pageGraphs.length - 1}
                        onClick={() => switchPage(Math.min(pageGraphs.length - 1, activePageIndex + 1))}
                        className="group absolute right-3 top-1/2 z-20 flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full border border-border bg-bg-2/80 text-text shadow-card backdrop-blur-md transition-all hover:border-accent/50 hover:bg-accent hover:text-white disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:border-border disabled:hover:bg-bg-2/80 disabled:hover:text-text"
                      >
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" className="transition-transform group-hover:translate-x-0.5">
                          <path d="M9 18l6-6-6-6" />
                        </svg>
                      </button>
                      {/* 页码指示器 */}
                      <div className="pointer-events-none absolute bottom-3 left-1/2 z-20 -translate-x-1/2 rounded-full border border-border bg-bg-2/80 px-3 py-1 font-mono text-[11px] text-text-2 shadow-card backdrop-blur-md">
                        {activePageIndex + 1} <span className="mx-1 text-text-3">/</span> {pageGraphs.length}
                      </div>
                    </>
                  )}
                </div>
              </div>

              {/* 右：侧栏（跨页连接 + 警告 + 全局信息）；折叠后隐藏，由工具栏按钮展开 */}
              {sidebarCollapsed ? null : (
              <div className="flex max-h-[38vh] flex-col overflow-hidden bg-bg-2/30 lg:max-h-full">
                {/* 全局统计 */}
                <div className="border-b border-border bg-bg-2/40 px-3 py-2 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-text">总览</span>
                    <span className="rounded bg-bg-3/60 px-1.5 py-0.5 text-[10px] text-text-3">
                      {pageGraphs.length} 页
                    </span>
                    <span className="rounded bg-bg-3/60 px-1.5 py-0.5 text-[10px] text-text-3">
                      {crossLinks.length} 跨页连接
                    </span>
                    <span className="rounded bg-bg-3/60 px-1.5 py-0.5 text-[10px] text-text-3">
                      {warnings.length} 警告
                    </span>
                    <button
                      type="button"
                      title="折叠侧栏"
                      onClick={() => setSidebarCollapsed(true)}
                      className="group ml-auto flex h-7 w-7 items-center justify-center rounded-lg border border-border/50 text-text-3 transition-all duration-200 hover:border-accent/40 hover:bg-accent hover:text-white hover:shadow-md hover:shadow-accent/25 active:scale-95"
                    >
                      <svg className="transition-transform duration-200 group-hover:scale-110" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M9 18l6-6-6-6" />
                      </svg>
                    </button>
                  </div>
                  <div className="mt-1 text-[10px] text-text-3">
                    {isExtracting
                      ? `提取进行中…（${pageGraphs.length}/${finalResult?.page_graphs?.length ?? imagePaths.length} 页）`
                      : `模式：${mode === 'global' ? '全局视图（跨页连接可编辑）' : `单页编辑 - 第 ${activePageIndexValue + 1} 页`}`}
                  </div>
                </div>

                <div className="flex-1 overflow-y-auto">
                  {/* 提取参数（简洁摘要，不暴露内部参数名） */}
                  <SidebarSection title="提取参数">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="rounded-md border border-border bg-bg/60 px-2 py-0.5 text-[11px] text-text-2">
                        并行 <span className="font-mono text-text">{String(args.max_workers ?? '-')}</span>
                      </span>
                      <span className="rounded-md border border-border bg-bg/60 px-2 py-0.5 text-[11px] text-text-2">
                        页范围 <span className="font-mono text-text">{String(args.start_page ?? 0)} - {String(args.end_page ?? '末页')}</span>
                      </span>
                    </div>
                  </SidebarSection>

                  {/* 跨页连接 */}
                  <SidebarSection title={`跨页连接（${crossLinks.length}）`}>
                    {crossLinks.length === 0 ? (
                      <div className="text-[11px] text-text-3">
                        {isExtracting ? '提取完成后计算跨页连接…' : '无跨页连接'}
                      </div>
                    ) : (
                      <div className="flex flex-col gap-1.5">
                        {crossLinks.map((cl, i) => (
                          <button
                            key={i}
                            className="rounded border border-border bg-bg/60 px-2 py-1.5 text-left text-[11px] hover:border-accent"
                            onClick={() => {
                              switchMode('single');
                              const arrIdx = pageGraphs.findIndex(
                                (pg, i) => (pg.page_index ?? i) === cl.fromPage,
                              );
                              if (arrIdx >= 0) switchPage(arrIdx);
                            }}
                            title={`第 ${cl.fromPage + 1} 页 → 第 ${cl.toPage + 1} 页（切到单页编辑）`}
                          >
                            <div className="flex items-center gap-1.5 font-mono text-text">
                              <span className="rounded bg-cyan/10 px-1 text-cyan">P{cl.fromPage + 1}</span>
                              <span className="text-text-3">→</span>
                              <span className="rounded bg-purple/10 px-1 text-purple">P{cl.toPage + 1}</span>
                            </div>
                            <div className="mt-0.5 truncate text-text-2" title={cl.label}>
                              {cl.label || '(无标签)'}
                            </div>
                          </button>
                        ))}
                      </div>
                    )}
                  </SidebarSection>

                  {/* 警告 */}
                  <SidebarSection title={`警告（${warnings.length}）`} accent="orange">
                    {warnings.length === 0 ? (
                      <div className="text-[11px] text-text-3">无警告</div>
                    ) : (
                      <ul className="flex flex-col gap-1">
                        {warnings.map((w, i) => (
                          <li
                            key={i}
                            className="flex items-start gap-1.5 rounded bg-orange/5 px-2 py-1 text-[11px] text-text-2"
                          >
                            <span className="mt-0.5 text-orange">•</span>
                            <span className="break-all">{w}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </SidebarSection>
                </div>

                {/* 操作提示：固定侧栏底部，不随上方内容滚动 */}
                <div className="mt-auto border-t border-border/60 px-3 py-2.5">
                  <h3 className="mb-2 flex items-center gap-2 text-[11px] font-bold text-text">
                    <span className="h-3 w-1 rounded-sm bg-accent" />
                    {isExtracting ? '提取说明' : '编辑说明'}
                  </h3>
                  <ul className="flex flex-col gap-1 text-[11px] text-text-2">
                    {isExtracting ? (
                      <>
                        <li>• 画布实时展示已提取的页面拓扑</li>
                        <li>• 提取完成后自动进入审核模式</li>
                        <li>• 审核时可拖拽节点、编辑边折点</li>
                      </>
                    ) : (
                      <>
                        <li>• 全局视图：所有页平铺，可编辑跨页连接折点</li>
                        <li>• 单页编辑：仅当前页，pageOffset=0</li>
                        <li>• 双击边添加折点，双击折点删除</li>
                        <li>• 拖拽端点重连，Delete 删除选中</li>
                        <li>• Ctrl+Z 撤销 / Ctrl+Y 重做</li>
                        <li>• 提交时按当前模式反归一化回原结构</li>
                      </>
                    )}
                  </ul>
                </div>
              </div>
              )}
            </div>
          )}
        </div>
        <ReviewToolbar
          canSubmit={canSubmit && !isTerminal && !submitted}
          submitting={submitting}
          resultMessage={resultMessage}
          statusHint={statusHint}
          onApprove={() => handleSubmit(true)}
          onReject={(reason) => handleSubmit(false, reason)}
        />
      </div>
      {toast}
    </Layout>
  );
}

function SidebarSection({
  title,
  accent = 'accent',
  children,
}: {
  title: string;
  accent?: 'accent' | 'orange';
  children: React.ReactNode;
}) {
  const bar = accent === 'orange' ? 'bg-orange' : 'bg-accent';
  return (
    <section className="border-b border-border/60 px-3 py-2.5">
      <h3 className="mb-2 flex items-center gap-2 text-[11px] font-bold text-text">
        <span className={`h-3 w-1 rounded-sm ${bar}`} />
        {title}
      </h3>
      {children}
    </section>
  );
}
