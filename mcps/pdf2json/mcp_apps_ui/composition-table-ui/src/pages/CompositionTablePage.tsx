/**
 * 组分表提取审核页（composition_table 工具）。
 *
 * 数据结构（composition_table 任务的 final_result）：
 *   {
 *     status: 'success' | 'partial',
 *     image_paths?: string[],
 *     aggregated: {
 *       components: [{ name, molecular_weight }],
 *       streams: [{
 *         stream_id, flow_rate: {value, unit},
 *         composition: [{ component, mole_fraction, mass_fraction }],
 *         temperature: {value, unit},
 *         pressure: {value, unit},
 *         phase
 *       }]
 *     },
 *     warnings: string[]
 *   }
 *
 * 表单编辑：组分名称/分子量、物流流量/温度/压力/相态/组成均可编辑。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Layout } from '@/components/Layout';
import { PageHeader } from '@/components/PageHeader';
import { ProgressBanner } from '@/components/ProgressBanner';
import { ReviewToolbar } from '@/components/ReviewToolbar';
import { JsonDrawer } from '@/components/JsonDrawer';
import { ErrorBanner } from '@/components/ErrorBanner';
import { useToast } from '@/components/Toast';
import { ExtractionWithImage } from '@/components/ExtractionWithImage';
import { ExtractionProgress } from '@/components/ExtractionProgress';
import { useMcpApp, useNormalizedToolResult } from '@/core/mcpApp';
import { useReviewStatus, submitReview } from '@/patterns/review';
import { useEditedData } from '@/core/hooks/useEditedData';
import { useDirtyGuard } from '@/core/hooks/useDirtyGuard';
import { InfoCell, SectionCard, WarningsList, TagBadge } from '@/components/common';
import { SourceImageViewer } from '@/components/common/SourceImageViewer';
import { CompositionMatrix } from './composition-table/CompositionMatrix';

// ===================== 类型 =====================

interface Quantity {
  value?: number | null;
  unit?: string;
}

interface Component {
  name: string;
  molecular_weight?: number | null;
}

interface CompositionEntry {
  component: string;
  mole_fraction?: number | null;
  mass_fraction?: number | null;
}

interface Stream {
  stream_id: string;
  flow_rate?: Quantity;
  composition?: CompositionEntry[];
  temperature?: Quantity;
  pressure?: Quantity;
  phase?: string;
}

interface CompositionTableResult {
  status?: string;
  image_paths?: string[];
  aggregated?: {
    components?: Component[];
    streams?: Stream[];
  };
  warnings?: string[];
}

// ===================== 工具函数 =====================

/** 导出组分表为 CSV（含 BOM 以兼容 Excel）。 */
function exportCompositionCsv(data: CompositionTableResult) {
  const components = data.aggregated?.components ?? [];
  const streams = data.aggregated?.streams ?? [];
  const header = [
    'stream_id', 'flow_rate', 'flow_unit',
    'temperature', 'temp_unit', 'pressure', 'pres_unit', 'phase',
    ...components.map((c) => c.name),
  ];
  const rows = streams.map((s) => [
    s.stream_id,
    s.flow_rate?.value ?? '',
    s.flow_rate?.unit ?? '',
    s.temperature?.value ?? '',
    s.temperature?.unit ?? '',
    s.pressure?.value ?? '',
    s.pressure?.unit ?? '',
    s.phase ?? '',
    ...components.map((c) => s.composition?.find((e) => e.component === c.name)?.mole_fraction ?? ''),
  ]);
  const csv = [header, ...rows]
    .map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(','))
    .join('\n');
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'composition_table.csv';
  a.click();
  URL.revokeObjectURL(url);
}

// ===================== 组件 =====================

export function CompositionTablePage() {
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

  const finalResult = (rawFinalResult ?? null) as CompositionTableResult | null;
  const { data, updatePath, getEdited, dirty, reset } = useEditedData<CompositionTableResult>(finalResult);
  useDirtyGuard(dirty);

  const canSubmit = status === 'waiting_review';
  const isTerminal = status === 'completed' || status === 'error';
  const isExtracting = !canSubmit && !isTerminal;

  // partial 数据派生（提取阶段）：final_result 就绪后不使用 partial
  const partialAggregated = useMemo(() => {
    if (finalResult) return null;
    // 优先使用 partial_aggregated（最终聚合结果）
    const pa = app.progress?.uiEvent?.partial_aggregated as
      | { components?: unknown[]; streams?: unknown[] }
      | undefined;
    if (pa) return pa;
    // 否则用累积的 partial_extracted
    const pe = app.progress?.uiEvent?.partial_extracted as
      | { components?: unknown[]; streams?: unknown[] }
      | undefined;
    if (!pe || (!pe.components?.length && !pe.streams?.length)) return null;
    return pe;
  }, [app.progress?.uiEvent?.partial_aggregated, app.progress?.uiEvent?.partial_extracted, finalResult]);

  const partialRaw = partialAggregated
    ? { aggregated: partialAggregated, status: 'extracting' as const } as CompositionTableResult
    : null;
  const raw = data ?? finalResult ?? partialRaw;

  const components = raw?.aggregated?.components ?? [];
  const streams = raw?.aggregated?.streams ?? [];
  const warnings = raw?.warnings ?? [];

  /** 更新组分字段。 */
  const updateComponent = useCallback(
    (index: number, field: 'name' | 'molecular_weight', value: string | number | null) => {
      const v = field === 'molecular_weight'
        ? (value === '' || value === null ? null : Number(value))
        : value;
      updatePath(`aggregated.components.${index}.${field}`, v);
    },
    [updatePath],
  );

  /** 更新物流字段。 */
  const updateStreamField = useCallback(
    (index: number, field: 'stream_id' | 'phase', value: string) => {
      updatePath(`aggregated.streams.${index}.${field}`, value);
    },
    [updatePath],
  );

  /** 更新物流的 Quantity 字段。 */
  const updateStreamQuantity = useCallback(
    (index: number, field: 'flow_rate' | 'temperature' | 'pressure', subField: 'value' | 'unit', value: string | number | null) => {
      const v = subField === 'value'
        ? (value === '' || value === null ? null : Number(value))
        : value;
      updatePath(`aggregated.streams.${index}.${field}.${subField}`, v);
    },
    [updatePath],
  );

  /** 矩阵单元格更新：按组分名查找 composition 条目索引。 */
  const handleMatrixChange = useCallback(
    (streamIdx: number, compName: string, field: 'mole_fraction' | 'mass_fraction', value: number | null) => {
      const stream = raw?.aggregated?.streams?.[streamIdx];
      if (!stream?.composition) return;
      const compIdx = stream.composition.findIndex((c) => c.component === compName);
      if (compIdx >= 0) {
        updatePath(`aggregated.streams.${streamIdx}.composition.${compIdx}.${field}`, value);
      }
    },
    [updatePath, raw],
  );

  const handleSubmit = useCallback(
    async (approved: boolean, reason?: string) => {
      const edited = getEdited();
      if (!edited) return;
      setSubmitting(true);
      setResultMessage(null);
      try {
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
    [getEdited, show],
  );

  const statusHint = useMemo(() => {
    if (isTerminal) return raw ? '审核已完成' : (app.error || '已结束');
    if (canSubmit) return '审核数据已就绪，请审核后提交';
    if (isExtracting) {
      const compCount = components.length;
      const streamCount = streams.length;
      if (compCount > 0 || streamCount > 0) {
        return `提取进行中…（已提取 ${compCount} 组分 / ${streamCount} 物流）`;
      }
      return '提取进行中…';
    }
    return '等待中…';
  }, [isTerminal, canSubmit, isExtracting, raw, app, components.length, streams.length]);

  const imagePaths = useMemo(
    () => raw?.image_paths ?? [],
    [raw],
  );

  return (
    <Layout>
      <div className="flex h-full flex-col">
        <PageHeader icon="table" title="组分表提取" subtitle="composition_table" color="red" />
        {!isExtracting && <ProgressBanner />}
        <div className="flex-1 overflow-hidden">
          {/* 提取中 */}
          {!raw && !progressError && (
            <ExtractionWithImage />
          )}
          {progressError && !raw && (
            <ErrorBanner error={progressError} onRetry={() => window.location.reload()} />
          )}
          {raw && (
            <div className="grid h-full grid-cols-1 overflow-hidden lg:grid-cols-[minmax(0,1fr)_360px]">
              <div className="min-h-0 overflow-hidden">
            <div className="grid h-full grid-cols-1 gap-3 p-3 lg:grid-cols-[320px_1fr]">
              {/* 左：源图预览（多页） */}
              {imagePaths.length > 0 ? (
                <SourceImageViewer imagePaths={imagePaths} className="rounded-md border border-border" />
              ) : (
                <div className="flex items-center justify-center rounded-md border border-border bg-bg-2/40 text-xs text-text-3">
                  无源图
                </div>
              )}

              {/* 右：滚动审核区 */}
              <div className="flex flex-col gap-3 overflow-y-auto">
                {/* 元信息 */}
                <SectionCard title="提取元信息">
                  <div className="grid grid-cols-3 gap-3">
                    <InfoCell label="状态" value={raw.status || '-'} highlight={raw.status === 'success' ? 'green' : 'orange'} />
                    <InfoCell label="组分数" value={components.length} />
                    <InfoCell label="物流数" value={streams.length} />
                  </div>
                </SectionCard>

                {/* 组分列表 */}
                {components.length > 0 && (
                  <SectionCard
                    title="组分列表"
                    count={components.length}
                    action={
                      <button
                        type="button"
                        className="rounded border border-border bg-bg-2 px-2.5 py-1 text-[11px] text-text-2 hover:bg-bg-3"
                        onClick={() => raw && exportCompositionCsv(raw)}
                      >
                        导出 CSV
                      </button>
                    }
                  >
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-border text-text-3">
                            <th className="px-2 py-1.5 text-left text-[10px] font-bold">#</th>
                            <th className="px-2 py-1.5 text-left text-[10px] font-bold">组分名称</th>
                            <th className="px-2 py-1.5 text-left text-[10px] font-bold">分子量</th>
                          </tr>
                        </thead>
                        <tbody>
                          {components.map((comp, i) => (
                            <tr key={i} className="border-b border-border/50">
                              <td className="px-2 py-1 text-text-3">{i + 1}</td>
                              <td className="px-2 py-1">
                                <input
                                  type="text"
                                  className="w-full rounded border border-border bg-bg px-2 py-0.5 text-text outline-none focus:border-accent disabled:opacity-70"
                                  value={comp.name ?? ''}
                                  onChange={(e) => updateComponent(i, 'name', e.target.value)}
                                  readOnly={!canSubmit || isExtracting}
                                />
                              </td>
                              <td className="px-2 py-1">
                                <input
                                  type="number"
                                  className="w-24 rounded border border-border bg-bg px-2 py-0.5 font-mono text-text outline-none focus:border-accent disabled:opacity-70"
                                  value={comp.molecular_weight ?? ''}
                                  onChange={(e) => updateComponent(i, 'molecular_weight', e.target.value)}
                                  readOnly={!canSubmit || isExtracting}
                                  placeholder="-"
                                />
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </SectionCard>
                )}

                {/* 组成矩阵 */}
                {components.length > 0 && streams.length > 0 && (
                  <SectionCard title="组成矩阵" accent="cyan">
                    <CompositionMatrix
                      components={components}
                      streams={streams}
                      readOnly={!canSubmit || isExtracting}
                      onChange={handleMatrixChange}
                    />
                  </SectionCard>
                )}

                {/* 物流列表（流量/温度/压力/相态） */}
                {streams.length > 0 && (
                  <SectionCard title="物流信息" count={streams.length} accent="green">
                    <div className="flex flex-col gap-3">
                      {streams.map((stream, i) => (
                        <StreamCard
                          key={i}
                          stream={stream}
                          readOnly={!canSubmit || isExtracting}
                          onUpdateField={(field, value) => updateStreamField(i, field, value)}
                          onUpdateQuantity={(field, subField, value) => updateStreamQuantity(i, field, subField, value)}
                        />
                      ))}
                    </div>
                  </SectionCard>
                )}

                {/* 警告 */}
                <WarningsList warnings={warnings} />
              </div>
            </div>
              </div>
              {/* 提取中：partial 数据就绪但 final 未到时，右侧保留进度时间线 */}
              {isExtracting && (
                <div className="hidden overflow-hidden border-l border-border lg:block">
                  <ExtractionProgress />
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
          dirty={dirty}
          onReset={reset}
        />
      </div>
      {toast}
      <JsonDrawer data={raw} disabled={isExtracting} />
    </Layout>
  );
}

// ===================== 物流卡片（仅流量/温度/压力/相态，组成移至矩阵） =====================

function StreamCard({
  stream,
  readOnly,
  onUpdateField,
  onUpdateQuantity,
}: {
  stream: Stream;
  readOnly: boolean;
  onUpdateField: (field: 'stream_id' | 'phase', value: string) => void;
  onUpdateQuantity: (
    field: 'flow_rate' | 'temperature' | 'pressure',
    subField: 'value' | 'unit',
    value: string | number | null,
  ) => void;
}) {
  const fr = stream.flow_rate ?? {};
  const temp = stream.temperature ?? {};
  const pres = stream.pressure ?? {};

  return (
    <div className="rounded-md border border-border bg-bg/60 p-3">
      {/* 头部：物流编号 + 相态 */}
      <div className="mb-3 flex items-center gap-2">
        <TagBadge color="green">{stream.stream_id || '-'}</TagBadge>
        <label className="flex items-center gap-1.5">
          <span className="text-[11px] text-text-3">相态</span>
          <input
            type="text"
            className="w-20 rounded border border-border bg-bg px-2 py-0.5 text-xs text-text outline-none focus:border-accent disabled:opacity-70"
            value={stream.phase ?? ''}
            onChange={(e) => onUpdateField('phase', e.target.value)}
            readOnly={readOnly}
            placeholder="-"
          />
        </label>
      </div>

      {/* 流量 / 温度 / 压力 */}
      <div className="grid grid-cols-3 gap-3">
        <StreamQuantityField
          label="流量"
          q={fr}
          readOnly={readOnly}
          onChangeValue={(v) => onUpdateQuantity('flow_rate', 'value', v)}
          onChangeUnit={(v) => onUpdateQuantity('flow_rate', 'unit', v)}
        />
        <StreamQuantityField
          label="温度"
          q={temp}
          readOnly={readOnly}
          onChangeValue={(v) => onUpdateQuantity('temperature', 'value', v)}
          onChangeUnit={(v) => onUpdateQuantity('temperature', 'unit', v)}
        />
        <StreamQuantityField
          label="压力"
          q={pres}
          readOnly={readOnly}
          onChangeValue={(v) => onUpdateQuantity('pressure', 'value', v)}
          onChangeUnit={(v) => onUpdateQuantity('pressure', 'unit', v)}
        />
      </div>
    </div>
  );
}

/** 物流 Quantity 字段（紧凑横向布局）。 */
function StreamQuantityField({ label, q, onChangeValue, onChangeUnit, readOnly }: {
  label: string;
  q?: Quantity;
  onChangeValue: (v: number | null) => void;
  onChangeUnit: (v: string) => void;
  readOnly?: boolean;
}) {
  return (
    <div className="flex items-center gap-2">
      <label className="w-10 shrink-0 text-[11px] text-text-3">{label}</label>
      <input
        type="number"
        className="w-24 rounded border border-border bg-bg px-2 py-1 font-mono text-xs text-text outline-none focus:border-accent disabled:opacity-70"
        value={q?.value ?? ''}
        onChange={(e) => onChangeValue(e.target.value === '' ? null : Number(e.target.value))}
        readOnly={readOnly}
        placeholder="-"
      />
      <input
        type="text"
        className="w-16 rounded border border-border bg-bg px-2 py-1 font-mono text-xs text-text-2 outline-none focus:border-accent disabled:opacity-70"
        value={q?.unit ?? ''}
        onChange={(e) => onChangeUnit(e.target.value)}
        readOnly={readOnly}
        placeholder="-"
      />
    </div>
  );
}