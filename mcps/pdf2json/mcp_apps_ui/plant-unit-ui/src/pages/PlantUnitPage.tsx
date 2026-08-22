/**
 * 整厂装置拓扑审核页（替代 plant_unit_viewer.html）。
 *
 * 数据结构（plant_unit_topology 任务的 final_result）：
 *   {
 *     plant_unit_drawing: {
 *       canvas_width, canvas_height,
 *       nodes: [{ node_id, x, y, width, height, name, display_name, layer, ... }],
 *       edges: [{ _key, source_id, target_id, material_name, waypoints, ... }],
 *       metadata?: { ... }
 *     },
 *     image_path?: string
 *   }
 *
 * 编辑能力：基于 TopologyEditor，节点拖拽+属性、边折点、端点重连+增删、撤销重做。
 * 提交时用 rfToPlantUnit 反归一化回原结构作为 edited_data。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Node, Edge } from '@xyflow/react';
import { Layout } from '@/components/Layout';
import { PageHeader } from '@/components/PageHeader';
import { ProgressBanner } from '@/components/ProgressBanner';
import { ReviewToolbar } from '@/components/ReviewToolbar';
import { JsonDrawer } from '@/components/JsonDrawer';
import { ErrorBanner } from '@/components/ErrorBanner';
import { useToast } from '@/components/Toast';
import { ExtractionWithImage } from '@/components/ExtractionWithImage';
import { useMcpApp, useNormalizedToolResult, useToolInput } from '@/core/mcpApp';
import { useReviewStatus, submitReview } from '@/patterns/review';
import {
  TopologyEditor,
  type TopologyEditorHandle,
} from '@/components/topology/TopologyEditor';
import {
  PLANT_UNIT_NODE_FIELDS,
  PLANT_UNIT_EDGE_FIELDS,
} from '@/components/topology/PropertyPanel';
import {
  plantUnitToRF,
  rfToPlantUnit,
} from '@/components/topology/topologyAdapters';
import { useEditedData } from '@/core/hooks/useEditedData';
import { useBboxOverlays } from '@/hooks/useBboxOverlays';
import {
  SourceImageViewer,
  SectionCard,
  TagBadge,
} from '@/components/common';

interface PlantUnitDrawing {
  canvas_width?: number;
  canvas_height?: number;
  nodes?: Array<Record<string, unknown>>;
  edges?: Array<Record<string, unknown>>;
  metadata?: Record<string, unknown>;
  [k: string]: unknown;
}

interface PlantUnitResult {
  plant_unit_drawing: PlantUnitDrawing;
  image_path?: string;
}

/**
 * partial 节点处理：把后端 partial 载荷（PlantUnitNode 原样：position/bbox，
 * 无 node_id/x/y）规整为 PlantUnitPage 下游（plantUnitToRF / deviceGroups）消费的
 * 像素坐标 + 名称字段。无可用坐标时用简单列自动布局兜底（design 3.1.1 最简实现，
 * 替代 dagre），避免全部叠在原点导致"提取阶段看起来无渲染"。
 */
function layoutPartialNodes(
  items: Array<Record<string, unknown>>,
): Array<Record<string, unknown>> {
  const out: Array<Record<string, unknown>> = [];
  let fx = 48;
  let fy = 48;
  for (const raw of items) {
    const n: Record<string, unknown> = { ...raw };
    const position = n.position;
    const bbox = n.bbox;
    let hasCoords = false;
    if (Array.isArray(position) && position.length === 2) {
      // PlantUnit.position 为像素坐标，代表节点中心。
      const w = Number(n.width ?? 160);
      const h = Number(n.height ?? 60);
      n.width = w;
      n.height = h;
      n.x = Number(position[0]) - w / 2;
      n.y = Number(position[1]) - h / 2;
      hasCoords = true;
    } else if (Array.isArray(bbox) && bbox.length === 4) {
      n.x = Number(bbox[0]);
      n.y = Number(bbox[1]);
      n.width = Number(bbox[2]) - Number(bbox[0]);
      n.height = Number(bbox[3]) - Number(bbox[1]);
      hasCoords = true;
    } else if (n.x != null && n.y != null) {
      hasCoords = true;
    }
    if (!hasCoords) {
      n.width = Number(n.width ?? 160);
      n.height = Number(n.height ?? 60);
      n.x = fx;
      n.y = fy;
      // 900 画布两列自动排布：超出行高后换到第二列
      fy += 130;
      if (fy + 100 > 880) {
        fx += 620;
        fy = 48;
      }
    }
    const id = String(n.id ?? '');
    n.name = n.name ?? n.unit_name ?? id;
    n.display_name = n.display_name ?? (n.unit_name ? String(n.unit_name) : String(n.name));
    n.layer = n.layer ?? '其他';
    out.push(n);
  }
  return out;
}

/** 图纸类型 -> 中文展示名（用于提取阶段 UI 展示）。 */
function drawingTypeLabel(type?: unknown): string {
  const t = String(type ?? '').trim();
  if (t === 'plant_unit_general') return '通用总图';
  if (t === 'plant_unit_dense') return '密集物料图';
  return t;
}

export function PlantUnitPage() {
  const app = useMcpApp();
  const { finalResult: rawFinalResult, isError } = useNormalizedToolResult();
  const status = useReviewStatus();
  const progressError = isError ? app.error : null;
  const { toast, show } = useToast();
  // 提取失败时弹出 toast 失败提示（去重，仅弹一次）
  const shownErrorRef = useRef<string | null>(null);
  useEffect(() => {
    if (progressError && shownErrorRef.current !== progressError) {
      shownErrorRef.current = progressError;
      show(`提取失败：${progressError}`, 'error');
    }
  }, [progressError, show]);
  const [submitting, setSubmitting] = useState(false);
  const [resultMessage, setResultMessage] = useState<{
    type: 'success' | 'error';
    text: string;
  } | null>(null);
  const [dirty, setDirty] = useState(false);
  const editorRef = useRef<TopologyEditorHandle>(null);

  const finalResult = (rawFinalResult ?? null) as PlantUnitResult | null;

  // 本地编辑副本（审核阶段用户编辑后覆盖 final_result）
  const { data } = useEditedData<PlantUnitResult>(finalResult);

  const canSubmit = status === 'waiting_review';
  const isTerminal = status === 'completed' || status === 'error';
  const isExtracting = !canSubmit && !isTerminal;

  // tool 入参（general_topology_mode 透出到设备列表标题）
  const toolInput = useToolInput();
  const args = (toolInput?.args ?? {}) as Record<string, unknown>;
  const mode = args.general_topology_mode === 'all_in_one' ? '整图单次' : '逐单元';

  // partial 数据派生（提取阶段）：final_result 就绪后不使用 partial
  const partialDrawing = useMemo<PlantUnitDrawing | null>(() => {
    if (finalResult) return null;
    const partialUnits =
      (app.progress?.uiEvent?.partial_plant_units ?? []) as Array<Record<string, unknown>>;
    const partialTextDests =
      (app.progress?.uiEvent?.partial_text_destinations ?? []) as Array<Record<string, unknown>>;
    const partialEdges =
      (app.progress?.uiEvent?.partial_edges ?? []) as Array<Record<string, unknown>>;
    if (partialUnits.length === 0 && partialEdges.length === 0) return null;
    const nodes = layoutPartialNodes([...partialUnits, ...partialTextDests]);
    return {
      canvas_width: 1200,
      canvas_height: 900,
      nodes,
      edges: partialEdges,
      metadata: { partial: true },
    };
  }, [
    app.progress?.uiEvent?.partial_plant_units,
    app.progress?.uiEvent?.partial_text_destinations,
    app.progress?.uiEvent?.partial_edges,
    finalResult,
  ]);

  const reviewData = data ?? finalResult ?? (partialDrawing ? { plant_unit_drawing: partialDrawing } as PlantUnitResult : null);

  const drawing = reviewData?.plant_unit_drawing;

  // 提取阶段底图路径：优先最终 image_path，缺失时用 progress.uiEvent.image_paths 兜底
  // （后端在 PDF 解析成图后即推送 image_paths，前端据此反向调用 read_image 显示底图）。
  const progressImagePaths = useMemo(
    () => (app.progress?.uiEvent?.image_paths as string[]) ?? [],
    [app.progress?.uiEvent?.image_paths],
  );
  const sourceImagePaths = reviewData?.image_path
    ? [reviewData.image_path]
    : progressImagePaths;

  // 图纸类型（drawing_type_classified 事件推送），用于提取阶段/源图头部展示
  const drawingType = useMemo(
    () => app.progress?.uiEvent?.drawing_type,
    [app.progress?.uiEvent?.drawing_type],
  );
  const drawingTypeText = drawingType ? drawingTypeLabel(drawingType) : '';

  // 转 RF 节点/边（plantUnit 坐标为像素，scale=1, pageOffset=0）
  const { nodes: initialNodes, edges: initialEdges } = useMemo(() => {
    if (!drawing) return { nodes: [] as Node[], edges: [] as Edge[] };
    return plantUnitToRF({
      canvas_width: drawing.canvas_width,
      canvas_height: drawing.canvas_height,
      nodes: drawing.nodes ?? [],
      edges: drawing.edges ?? [],
    });
  }, [drawing]);

  // 统计信息
  const stats = useMemo(() => {
    const materials = new Set<string>();
    initialEdges.forEach((e: Edge) => {
      const label = (e.data as { label?: string } | undefined)?.label;
      if (label) materials.add(label);
    });
    const equipmentCount = initialNodes.filter((n: Node) => n.type === 'equipment').length;
    return {
      nodeCount: initialNodes.length,
      equipmentCount,
      edgeCount: initialEdges.length,
      materialCount: materials.size,
      canvas: `${drawing?.canvas_width ?? 1200} × ${drawing?.canvas_height ?? 900}`,
    };
  }, [initialNodes, initialEdges, drawing]);

  // 源图 bbox 叠加层（节点框归一化到 0-1）
  const bboxes = useBboxOverlays(drawing?.nodes, drawing?.canvas_width, drawing?.canvas_height);

  // 设备列表按 layer 分组
  const deviceGroups = useMemo(() => {
    if (!drawing?.nodes) return [];
    const groups = new Map<string, Array<{ id: string; name: string; layer: string }>>();
    for (const node of drawing.nodes) {
      const layer = String(node.layer ?? '其他');
      const id = String(node.node_id ?? node.id ?? '');
      const name = String(node.display_name ?? node.name ?? id);
      if (!groups.has(layer)) groups.set(layer, []);
      groups.get(layer)!.push({ id, name, layer });
    }
    return Array.from(groups.entries()).map(([layer, devices]) => ({ layer, devices }));
  }, [drawing]);

  /** 构建编辑后的 edited_data。 */
  const buildEditedData = useCallback((): PlantUnitResult | null => {
    if (!reviewData || !drawing || !editorRef.current) return null;
    const { nodes: rfNodes, edges: rfEdges } = editorRef.current.getEdited();
    const newDrawing = rfToPlantUnit(rfNodes, rfEdges, {
      canvas_width: drawing.canvas_width,
      canvas_height: drawing.canvas_height,
      nodes: drawing.nodes ?? [],
      edges: drawing.edges ?? [],
      metadata: drawing.metadata,
    });
    return { ...reviewData, plant_unit_drawing: newDrawing };
  }, [reviewData, drawing]);

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

  const statusHint = useMemo(() => {
    if (isTerminal) return reviewData ? '审核已完成' : (app.error || '已结束');
    if (canSubmit) return '审核数据已就绪，请审核后提交';
    if (isExtracting) {
      const nodeCount = partialDrawing?.nodes?.length ?? 0;
      const edgeCount = partialDrawing?.edges?.length ?? 0;
      if (nodeCount > 0 || edgeCount > 0) {
        return `提取进行中…（已提取 ${nodeCount} 装置 / ${edgeCount} 边）`;
      }
      return '提取进行中…';
    }
    return '等待中…';
  }, [isTerminal, canSubmit, isExtracting, reviewData, app, partialDrawing]);

  const deviceCount = deviceGroups.reduce((n, g) => n + g.devices.length, 0);

  return (
    <Layout>
      <div className="flex h-full flex-col">
        <PageHeader icon="plantUnit" title="整厂装置拓扑" subtitle="plant_unit_topology" color="cyan" />
        {!isExtracting && <ProgressBanner />}
        <div className="flex-1 overflow-hidden">
          {/* 提取中：展示 SSE 事件时间线 */}
          {!drawing && !progressError && (
            <ExtractionWithImage />
          )}
          {/* 进度数据加载错误 */}
          {progressError && !drawing && (
            <ErrorBanner error={progressError} onRetry={() => window.location.reload()} />
          )}
          {drawing && (
            <div className="grid h-full grid-cols-1 overflow-hidden lg:grid-cols-[300px_1fr] xl:grid-cols-[300px_1fr_260px]">
              {/* 左：源图预览 + bbox 叠加 */}
              <div className="flex flex-col overflow-hidden border-r border-border">
                <div className="flex items-center gap-2 border-b border-border bg-bg-2/40 px-3 py-2">
                  <span className="text-xs font-bold text-text">源图</span>
                  {drawingTypeText && (
                    <span className="rounded bg-cyan/10 px-1.5 py-0.5 text-[10px] text-cyan">
                      图纸类型：{drawingTypeText}
                    </span>
                  )}
                </div>
                <div className="relative flex-1 bg-bg">
                  <SourceImageViewer
                    imagePaths={sourceImagePaths}
                    bboxes={bboxes}
                    className="h-full"
                  />
                </div>
              </div>

              {/* 中：拓扑编辑器 */}
              <div className="flex flex-col overflow-hidden border-r border-border">
                <div className="flex items-center gap-3 border-b border-border bg-bg-2/40 px-4 py-2">
                  <span className="text-xs font-bold text-text">拓扑编辑器</span>
                  <span className="rounded bg-bg-3/60 px-1.5 py-0.5 text-[10px] text-text-3">
                    {stats.equipmentCount} 装置
                  </span>
                  <span className="rounded bg-bg-3/60 px-1.5 py-0.5 text-[10px] text-text-3">
                    {stats.edgeCount} 边
                  </span>
                  <span className="rounded bg-bg-3/60 px-1.5 py-0.5 text-[10px] text-text-3">
                    {stats.materialCount} 物料
                  </span>
                  <span className="ml-auto font-mono text-[10px] text-text-3">
                    {stats.canvas}
                  </span>
                </div>
                <div className="relative flex-1 bg-bg">
                  <TopologyEditor
                    ref={editorRef}
                    initialNodes={initialNodes}
                    initialEdges={initialEdges}
                    nodeFields={PLANT_UNIT_NODE_FIELDS}
                    edgeFields={PLANT_UNIT_EDGE_FIELDS}
                    readOnly={!canSubmit || isTerminal || isExtracting}
                    onChange={() => setDirty(true)}
                    className="h-full"
                  />
                </div>
              </div>

              {/* 右：设备列表 + 编辑说明 */}
              <div className="flex flex-col overflow-hidden bg-bg-2/30">
                <div className="border-b border-border bg-bg-2/40 px-3 py-2 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-text">设备列表</span>
                    <span className="rounded bg-bg-3/60 px-1.5 py-0.5 text-[10px] text-text-3">
                      {deviceCount} 设备
                    </span>
                    <span className="rounded bg-bg-3/60 px-1.5 py-0.5 text-[10px] text-text-3">模式：{mode}</span>
                    {dirty && (
                      <span className="ml-auto rounded bg-orange/10 px-1.5 py-0.5 text-[10px] text-orange">
                        未保存
                      </span>
                    )}
                  </div>
                </div>

                <div className="flex-1 overflow-y-auto">
                  {deviceCount === 0 ? (
                    <div className="px-3 py-4 text-[11px] text-text-3">暂无设备</div>
                  ) : (
                    deviceGroups.map((g) => (
                      <section
                        key={g.layer}
                        className="border-b border-border/60 px-3 py-2.5"
                      >
                        <div className="mb-1.5 flex items-center gap-1.5">
                          <TagBadge color="cyan">{g.layer}</TagBadge>
                          <span className="text-[10px] text-text-3">{g.devices.length}</span>
                        </div>
                        <ul className="flex flex-col gap-0.5">
                          {g.devices.map((d) => (
                            <li key={d.id}>
                              <button
                                type="button"
                                onClick={() => editorRef.current?.focusNode(d.id)}
                                className="w-full truncate rounded px-2 py-1 text-left text-[11px] text-text-2 transition hover:bg-bg-3 hover:text-text"
                                title={d.name}
                              >
                                {d.name}
                              </button>
                            </li>
                          ))}
                        </ul>
                      </section>
                    ))
                  )}

                  <SectionCard
                    title={isExtracting ? '提取说明' : '编辑说明'}
                    accent="accent"
                    className="m-3"
                  >
                    <ul className="flex flex-col gap-1 text-[11px] text-text-2">
                      {isExtracting ? (
                        <>
                          <li>• 提取完成后自动进入审核模式</li>
                          <li>• 审核时可拖拽节点、编辑边折点</li>
                        </>
                      ) : (
                        <>
                          <li>• 拖拽节点移动位置</li>
                          <li>• 双击边添加折点，双击折点删除</li>
                          <li>• 拖拽端点重连边</li>
                          <li>• 从端口拖出连接新边</li>
                          <li>• Delete 删除选中</li>
                          <li>• Ctrl+Z 撤销 / Ctrl+Y 重做</li>
                          <li>• 选中节点/边在右上角编辑属性</li>
                          <li>• 点击右侧设备可定位到对应节点</li>
                        </>
                      )}
                    </ul>
                  </SectionCard>
                </div>
              </div>
            </div>
          )}
        </div>
        <ReviewToolbar
          canSubmit={canSubmit && !isTerminal}
          submitting={submitting}
          resultMessage={resultMessage}
          statusHint={statusHint}
          onApprove={() => handleSubmit(true)}
          onReject={(reason) => handleSubmit(false, reason)}
        />
      </div>
      {toast}
      <JsonDrawer data={reviewData} disabled={isExtracting} />
    </Layout>
  );
}
