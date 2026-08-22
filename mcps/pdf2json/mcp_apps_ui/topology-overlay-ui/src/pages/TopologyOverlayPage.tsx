/**
 * 拓扑叠加审核页（topology_overlay 工具）。
 *
 * 数据结构（topology_overlay 任务的 final_result）：
 *   {
 *     topology: { equipment_nodes, boundary_nodes, edges },
 *     match_stats: { pd_equipment_total, matched, unmatched_pd,
 *                    image_equipment_total, extra_image, boundary_nodes,
 *                    edges, connections_total, connections_dropped },
 *     match_details: { matched, unmatched_pd, extra_image },
 *     warnings: string[]
 *   }
 *
 * topology 包装为 { pfd_drawing: { topology } } 复用 pfdPageToRF 适配器。
 * 提交时用 rfToPfdPage 反归一化回 topology 结构。
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
  PFD_NODE_FIELDS,
  PFD_EDGE_FIELDS,
} from '@/components/topology/PropertyPanel';
import {
  pfdPageToRF,
  rfToPfdPage,
} from '@/components/topology/topologyAdapters';
import { useEditedData } from '@/core/hooks/useEditedData';
import { InfoCell, SectionCard, WarningsList } from '@/components/common';
import { MatchRelationView, type MatchDetails } from './topology-overlay/MatchRelationView';

interface MatchStats {
  pd_equipment_total?: number;
  matched?: number;
  unmatched_pd?: number;
  image_equipment_total?: number;
  extra_image?: number;
  boundary_nodes?: number;
  edges?: number;
  connections_total?: number;
  connections_dropped?: number;
}

interface TopologyOverlayResult {
  topology?: {
    equipment_nodes?: Array<Record<string, unknown>>;
    boundary_nodes?: Array<Record<string, unknown>>;
    edges?: Array<Record<string, unknown>>;
  };
  match_stats?: MatchStats;
  match_details?: MatchDetails;
  warnings?: string[];
}

const CANVAS_W = 1200;
const CANVAS_H = 1600;

export function TopologyOverlayPage() {
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
  const [droppedExpanded, setDroppedExpanded] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const editorRef = useRef<TopologyEditorHandle>(null);

  const canSubmit = status === 'waiting_review';
  const isTerminal = status === 'completed' || status === 'error';
  const isExtracting = !canSubmit && !isTerminal;

  // tool 入参（透出到丢弃连接详情）
  const toolInput = useToolInput();
  const args = (toolInput?.args ?? {}) as Record<string, unknown>;

  const finalResult = (rawFinalResult ?? null) as TopologyOverlayResult | null;
  const { data } = useEditedData<TopologyOverlayResult>(finalResult);
  const reviewData = data ?? finalResult;

  const topology = reviewData?.topology;
  const matchStats = reviewData?.match_stats;
  const matchDetails = reviewData?.match_details ?? { matched: [], unmatched_pd: [], extra_image: [] };
  const warnings = reviewData?.warnings ?? [];

  // 包装为 pfdPageToRF 能消费的格式
  const { nodes: initialNodes, edges: initialEdges } = useMemo(() => {
    if (!topology) return { nodes: [] as Node[], edges: [] as Edge[] };
    const pageGraph = { pfd_drawing: { topology } };
    return pfdPageToRF(pageGraph, {
      pageIndex: 0,
      offsetX: 0,
      offsetY: 0,
      canvasW: CANVAS_W,
      canvasH: CANVAS_H,
      label: '拓扑叠加',
    });
  }, [topology]);

  const stats = useMemo(() => {
    const equipmentCount = initialNodes.filter((n: Node) => n.type === 'equipment').length;
    const boundaryCount = initialNodes.filter((n: Node) => n.type === 'boundary').length;
    return {
      equipmentCount,
      boundaryCount,
      edgeCount: initialEdges.length,
    };
  }, [initialNodes, initialEdges]);

  /** 构建编辑后的 edited_data。 */
  const buildEditedData = useCallback((): TopologyOverlayResult | null => {
    if (!reviewData || !topology || !editorRef.current) return null;
    const { nodes: rfNodes, edges: rfEdges } = editorRef.current.getEdited();
    const newDrawing = rfToPfdPage(
      rfNodes,
      rfEdges,
      0,
      { x: 0, y: 0 },
      CANVAS_W,
      CANVAS_H,
      { pfd_drawing: { topology } },
    );
    return {
      ...reviewData,
      topology: (newDrawing.topology as TopologyOverlayResult['topology']) ?? topology,
    };
  }, [reviewData, topology]);

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
    if (isExtracting) return '计算进行中…';
    return '等待中…';
  }, [isTerminal, canSubmit, isExtracting, reviewData, app]);

  // 匹配统计项
  const matchStatsItems = useMemo(() => {
    if (!matchStats) return [];
    return [
      { label: '工艺说明设备', value: matchStats.pd_equipment_total ?? '-', color: 'default' as const },
      { label: '已匹配', value: matchStats.matched ?? '-', color: 'green' as const },
      { label: '未匹配(他图)', value: matchStats.unmatched_pd ?? '-', color: 'orange' as const },
      { label: '图纸设备', value: matchStats.image_equipment_total ?? '-', color: 'default' as const },
      { label: '图纸多余', value: matchStats.extra_image ?? '-', color: 'orange' as const },
      { label: '边界节点', value: matchStats.boundary_nodes ?? '-', color: 'default' as const },
      { label: '生成边数', value: matchStats.edges ?? '-', color: 'default' as const },
      { label: '连接总数', value: matchStats.connections_total ?? '-', color: 'default' as const },
      { label: '丢弃连接', value: matchStats.connections_dropped ?? '-', color: 'orange' as const },
    ];
  }, [matchStats]);

  return (
    <Layout>
      <div className="flex h-full flex-col">
        <PageHeader icon="layers" title="拓扑叠加" subtitle="topology_overlay" color="purple" />
        {!isExtracting && <ProgressBanner />}
        <div className="flex-1 overflow-hidden">
          {/* 计算中 */}
          {!topology && !progressError && (
            <ExtractionWithImage />
          )}
          {progressError && !topology && (
            <ErrorBanner error={progressError} onRetry={() => window.location.reload()} />
          )}
          {topology && (
            <div
              className={`grid h-full overflow-hidden transition-[grid-template-columns] duration-300 grid-cols-1 ${rightCollapsed ? 'lg:grid-cols-[240px_1fr]' : 'lg:grid-cols-[240px_1fr_320px]'}`}
            >
              {/* 左：匹配统计 + 警告 */}
              <div className="flex flex-col overflow-hidden border-r border-border bg-bg-2/30">
                <div className="flex-1 overflow-y-auto p-3">
                  <SectionCard title="匹配统计">
                    <div className="grid grid-cols-2 gap-2">
                      {matchStatsItems.map((item) => (
                        <InfoCell
                          key={item.label}
                          label={item.label}
                          value={item.value}
                          highlight={item.color === 'default' ? undefined : item.color}
                        />
                      ))}
                    </div>
                    {matchStats?.connections_dropped && matchStats.connections_dropped > 0 && (
                      <div className="mt-2 rounded bg-orange/5 p-2 text-[11px] text-text-2">
                        <button
                          type="button"
                          className="flex w-full items-center gap-1 font-bold text-orange transition hover:text-orange/70 active:scale-[0.98]"
                          onClick={() => setDroppedExpanded((v) => !v)}
                        >
                          <span>{droppedExpanded ? '▼' : '▶'}</span>
                          <span>丢弃连接详情</span>
                          <span className="ml-auto font-mono text-[10px] text-text-3">
                            入参：工艺拓扑 {Array.isArray((args.pd_topology as { equipment?: unknown[] } | undefined)?.equipment) ? ((args.pd_topology as { equipment: unknown[] }).equipment).length : '-'} / 图纸 {Array.isArray(args.image_equipment) ? (args.image_equipment as unknown[]).length : '-'}
                          </span>
                        </button>
                        {droppedExpanded && (
                          <>
                            {warnings
                              .filter((w) => w.toLowerCase().includes('drop') || w.includes('丢弃'))
                              .map((w, i) => (
                                <div key={i} className="mt-1">• {w}</div>
                              ))}
                            {warnings.filter((w) => w.toLowerCase().includes('drop') || w.includes('丢弃')).length === 0 && (
                              <div className="mt-1 text-text-3">详见 warnings</div>
                            )}
                          </>
                        )}
                      </div>
                    )}
                  </SectionCard>
                  <div className="mt-3">
                    <WarningsList warnings={warnings} />
                  </div>
                </div>
              </div>

              {/* 中：编辑器 */}
              <div className="flex flex-col overflow-hidden border-r border-border">
                <div className="flex items-center gap-3 border-b border-border bg-bg-2/40 px-4 py-2">
                  <span className="text-xs font-bold text-text">拓扑叠加编辑器</span>
                  <span className="rounded bg-bg-3/60 px-1.5 py-0.5 text-[10px] text-text-3">
                    {stats.equipmentCount} 设备
                  </span>
                  <span className="rounded bg-bg-3/60 px-1.5 py-0.5 text-[10px] text-text-3">
                    {stats.boundaryCount} 边界
                  </span>
                  <span className="rounded bg-bg-3/60 px-1.5 py-0.5 text-[10px] text-text-3">
                    {stats.edgeCount} 边
                  </span>
                  {dirty && (
                    <span className="ml-auto rounded bg-orange/10 px-1.5 py-0.5 text-[10px] text-orange">
                      未保存
                    </span>
                  )}
                </div>
                <div className="relative flex-1 bg-bg">
                  <TopologyEditor
                    ref={editorRef}
                    initialNodes={initialNodes}
                    initialEdges={initialEdges}
                    nodeFields={PFD_NODE_FIELDS}
                    edgeFields={PFD_EDGE_FIELDS}
                    readOnly={!canSubmit || isTerminal}
                    onChange={() => setDirty(true)}
                    className="h-full"
                  />
                  {rightCollapsed && (
                    <button
                      type="button"
                      title="展开右栏"
                      onClick={() => setRightCollapsed(false)}
                      className="group absolute right-3 top-3 z-20 flex h-9 w-9 items-center justify-center rounded-lg border border-border/60 bg-bg/80 text-text-3 shadow-sm backdrop-blur-sm transition-all duration-200 hover:border-accent/40 hover:bg-accent hover:text-white active:scale-95"
                    >
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M15 18l-6-6 6-6" />
                      </svg>
                    </button>
                  )}
                </div>
              </div>

              {/* 右：匹配关系视图 + 编辑说明（可折叠） */}
              {!rightCollapsed && (
              <div className="flex flex-col overflow-hidden bg-bg-2/30">
                <div className="border-b border-border bg-bg-2/40 px-3 py-2 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-text">匹配关系视图</span>
                    <button
                      type="button"
                      title="折叠右栏"
                      onClick={() => setRightCollapsed(true)}
                      className="group ml-auto flex h-7 w-7 items-center justify-center rounded-lg border border-border/50 text-text-3 transition-all duration-200 hover:border-accent/40 hover:bg-accent hover:text-white active:scale-95"
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M9 18l6-6-6-6" />
                      </svg>
                    </button>
                  </div>
                </div>
                <div className="flex-1 overflow-hidden">
                  <MatchRelationView
                    matchDetails={matchDetails}
                    onLocate={(nodeId, side) => {
                      if (side === 'image') editorRef.current?.focusNode(nodeId);
                    }}
                  />
                </div>
                <div className="border-t border-border p-3">
                  <SectionCard title={isExtracting ? '计算说明' : '编辑说明'}>
                    <ul className="flex flex-col gap-1 text-[11px] text-text-2">
                      {isExtracting ? (
                        <>
                          <li>• 计算完成后自动进入审核模式</li>
                          <li>• 审核时可拖拽节点、编辑边折点</li>
                        </>
                      ) : (
                        <>
                          <li>• 拖拽节点移动位置</li>
                          <li>• 双击边添加折点，双击折点删除</li>
                          <li>• 拖拽端点重连边</li>
                          <li>• Delete 删除选中</li>
                          <li>• Ctrl+Z 撤销 / Ctrl+Y 重做</li>
                        </>
                      )}
                    </ul>
                  </SectionCard>
                </div>
              </div>
              )}
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
