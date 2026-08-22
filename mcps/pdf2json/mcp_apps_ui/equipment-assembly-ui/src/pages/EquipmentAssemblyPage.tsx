/**
 * 设备装配图审核页（替代 equipment_assembly_viewer.html）。
 *
 * 数据结构（equipment_assembly 任务的 final_result）：
 *   {
 *     reactor_design?: ReactorDesign,           // 二选一
 *     distillation_column?: DistillationColumn, // 二选一
 *   }
 *
 * 简化策略：
 *   - 旧 HTML 172KB 含复杂 SVG 交互编辑器（接管点击/拖拽等），维护成本高
 *   - React 版改为表单编辑器 + 原始 JSON 查看器 + 源图预览
 *   - 保留可编辑的核心字段（位号、尺寸、压力、温度、接管列表）
 *   - 内件段以表格展示（不可编辑，需要时通过 JSON 编辑）
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
import { useMcpApp, useNormalizedToolResult, useToolInput } from '@/core/mcpApp';
import { useReviewStatus, submitReview } from '@/patterns/review';
import { useEditedData } from '@/core/hooks/useEditedData';
import { useDirtyGuard } from '@/core/hooks/useDirtyGuard';
import {
  Field,
  SelectField,
  QuantityField,
  SectionCard,
  WarningsList,
  TagBadge,
  EditableTable,
  type EditableTableColumn,
} from '@/components/common';
import { SourceImageViewer } from '@/components/common/SourceImageViewer';
import { TowerSchematic } from './equipment-assembly/TowerSchematic';

/** 带 {value, unit} 的物理量。 */
interface Quantity {
  value?: number;
  unit?: string;
}

interface Nozzle {
  nozzle_id?: string;
  service_description?: string;
  nominal_size?: string;
  elevation?: Quantity;
  nozzle_role?: string;
  confidence?: number;
  medium?: string[];
}

type InternalsSection = {
  section_id?: string;
  from_no?: number | string;
  to_no?: number | string;
  spacing?: Quantity;
  diameter?: Quantity;
  height?: Quantity;
  elevation_top?: Quantity;
  elevation_bottom?: Quantity;
  confidence?: number;
  type?: string; // 'tray' | 'packed'
};

interface EquipmentInfo {
  equipment_tag?: string;
  equipment_name?: string;
}

interface DistillationColumn {
  info?: EquipmentInfo;
  column_type?: 'tray' | 'packed' | 'composite' | 'unknown' | string;
  count?: number;
  numbering_direction?: 'top_to_bottom' | 'bottom_to_top' | string;
  nominal_diameter?: Quantity;
  total_height?: Quantity;
  design_pressure?: Quantity;
  design_temperature?: Quantity;
  working_pressure?: { top?: Quantity; bottom?: Quantity };
  working_temperature?: { top?: Quantity; bottom?: Quantity };
  diameter_sections?: Array<{ section_id?: string; diameter?: Quantity; confidence?: number }>;
  internals_sections?: InternalsSection[];
  nozzles?: Nozzle[];
  warnings?: string[];
  source_image_id?: string;
}

interface ReactorDesign {
  info?: EquipmentInfo;
  reactor_type?: string;
  dimensions?: {
    shell_diameter?: Quantity;
    shell_height?: Quantity;
    [k: string]: Quantity | undefined;
  };
  shell_side?: Record<string, unknown>;
  tube_side?: Record<string, unknown>;
  nozzles?: Nozzle[];
  warnings?: string[];
  source_image_id?: string;
}

interface EquipmentAssemblyResult {
  reactor_design?: ReactorDesign;
  distillation_column?: DistillationColumn;
  assembly?: {
    reactor_design?: ReactorDesign;
    distillation_column?: DistillationColumn;
  };
  equipment_type?: string;
  image_path?: string;
}

/** 从最终结果中解析装配数据（兼容嵌套 assembly 与扁平结构）。 */
function resolveAssemblyData(
  data: EquipmentAssemblyResult,
  type: 'reactor' | 'column',
): ReactorDesign | DistillationColumn | null {
  if (!data) return null;
  const key = type === 'reactor' ? 'reactor_design' : 'distillation_column';
  const fromNested = data.assembly?.[key];
  if (fromNested) return fromNested;
  return (data[key] ?? null) as ReactorDesign | DistillationColumn | null;
}

function detectEquipmentType(data: EquipmentAssemblyResult): 'reactor' | 'column' {
  if (data.equipment_type === 'reactor') return 'reactor';
  if (data.equipment_type?.startsWith('column')) return 'column';
  if (data.assembly?.reactor_design) return 'reactor';
  if (data.assembly?.distillation_column) return 'column';
  if (data.reactor_design) return 'reactor';
  if (data.distillation_column) return 'column';
  return 'column';
}

const NOZZLE_ROLE_COLOR: Record<string, string> = {
  inlet: 'var(--cyan)',
  outlet: 'var(--green)',
  drain: 'var(--text3)',
  vent: 'var(--purple)',
  instrument: 'var(--orange)',
  manhole: 'var(--accent)',
};

function nozzleColor(role?: string): string {
  if (!role) return 'var(--text3)';
  return NOZZLE_ROLE_COLOR[role.toLowerCase()] || 'var(--text3)';
}

/** 接管位号 TagBadge 颜色（role -> TagBadge color 枚举）。 */
const NOZZLE_TAG_COLOR: Record<
  string,
  'accent' | 'green' | 'orange' | 'purple' | 'cyan' | 'yellow' | 'red'
> = {
  inlet: 'cyan',
  outlet: 'green',
  drain: 'accent',
  vent: 'purple',
  instrument: 'orange',
  manhole: 'accent',
};

function nozzleTagColor(
  role?: string,
): 'accent' | 'green' | 'orange' | 'purple' | 'cyan' | 'yellow' | 'red' {
  if (!role) return 'accent';
  return NOZZLE_TAG_COLOR[role.toLowerCase()] ?? 'accent';
}

export function EquipmentAssemblyPage() {
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

  const finalResult = (rawFinalResult ?? null) as EquipmentAssemblyResult | null;

  // 编辑副本管理（统一 hook，修复 editedData 不回写 bug）
  const { data, updatePath, getEdited, dirty, reset } = useEditedData<EquipmentAssemblyResult>(finalResult);
  useDirtyGuard(dirty);
  const raw = data ?? finalResult;

  const canSubmit = status === 'waiting_review';
  const isTerminal = status === 'completed' || status === 'error';
  const isExtracting = !canSubmit && !isTerminal;

  // tool 入参（equipment_id 透出到副标题）
  const toolInput = useToolInput();
  const args = (toolInput?.args ?? {}) as Record<string, unknown>;

  // 解构出当前设备数据（优先读取嵌套 assembly.* 结构）
  const equipmentType = useMemo(() => (raw ? detectEquipmentType(raw) : 'column'), [raw]);
  const equipmentData = useMemo(
    () => (raw ? resolveAssemblyData(raw, equipmentType) : null),
    [raw, equipmentType],
  );

  // 编辑：按 prefix 写入 assembly.reactor_design / assembly.distillation_column
  const updateField = useCallback(
    (path: string, value: unknown) => {
      const rootKey = equipmentType === 'reactor' ? 'reactor_design' : 'distillation_column';
      const target = (raw as EquipmentAssemblyResult).assembly?.[rootKey] ?? (raw as EquipmentAssemblyResult)[rootKey];
      if (!target) return;
      updatePath(`assembly.${rootKey}.${path}`, value);
    },
    [updatePath, equipmentType, raw],
  );

  // 内件段表格列：render 内直接调 updateField 写嵌套 path（保护 Quantity 结构）
  const internalsColumns: EditableTableColumn<InternalsSection>[] = [
    {
      key: 'from_no',
      header: '起始',
      render: (row, i, readOnly) => (
        <input
          type="number"
          className="w-16 rounded border border-border bg-bg px-1 py-0.5 font-mono text-[11px] disabled:opacity-70"
          value={row.from_no ?? ''}
          readOnly={readOnly}
          onChange={(e) =>
            updateField(
              `internals_sections.${i}.from_no`,
              e.target.value === '' ? undefined : Number(e.target.value),
            )
          }
        />
      ),
    },
    {
      key: 'to_no',
      header: '结束',
      render: (row, i, readOnly) => (
        <input
          type="number"
          className="w-16 rounded border border-border bg-bg px-1 py-0.5 font-mono text-[11px] disabled:opacity-70"
          value={row.to_no ?? ''}
          readOnly={readOnly}
          onChange={(e) =>
            updateField(
              `internals_sections.${i}.to_no`,
              e.target.value === '' ? undefined : Number(e.target.value),
            )
          }
        />
      ),
    },
    {
      key: 'type',
      header: '类型',
      render: (row, i, readOnly) => (
        <select
          className="rounded border border-border bg-bg px-1 py-0.5 text-[11px] disabled:opacity-70"
          value={row.type ?? 'tray'}
          disabled={readOnly}
          onChange={(e) => updateField(`internals_sections.${i}.type`, e.target.value)}
        >
          <option value="tray">塔板</option>
          <option value="packed">填料</option>
        </select>
      ),
    },
    {
      key: 'spacing',
      header: '间距',
      render: (row, i, readOnly) => (
        <input
          type="number"
          className="w-20 rounded border border-border bg-bg px-1 py-0.5 font-mono text-[11px] disabled:opacity-70"
          value={row.spacing?.value ?? ''}
          readOnly={readOnly}
          onChange={(e) =>
            updateField(
              `internals_sections.${i}.spacing.value`,
              e.target.value === '' ? undefined : Number(e.target.value),
            )
          }
        />
      ),
    },
    {
      key: 'diameter',
      header: '直径',
      render: (row, i, readOnly) => (
        <input
          type="number"
          className="w-20 rounded border border-border bg-bg px-1 py-0.5 font-mono text-[11px] disabled:opacity-70"
          value={row.diameter?.value ?? ''}
          readOnly={readOnly}
          onChange={(e) =>
            updateField(
              `internals_sections.${i}.diameter.value`,
              e.target.value === '' ? undefined : Number(e.target.value),
            )
          }
        />
      ),
    },
    {
      key: 'height',
      header: '段高',
      render: (row, i, readOnly) => (
        <input
          type="number"
          className="w-20 rounded border border-border bg-bg px-1 py-0.5 font-mono text-[11px] disabled:opacity-70"
          value={row.height?.value ?? ''}
          readOnly={readOnly}
          onChange={(e) =>
            updateField(
              `internals_sections.${i}.height.value`,
              e.target.value === '' ? undefined : Number(e.target.value),
            )
          }
        />
      ),
    },
  ];

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
    if (isExtracting) return '提取进行中…';
    return '等待中…';
  }, [isTerminal, canSubmit, isExtracting, raw, app]);

  const imagePaths = useMemo(
    () => (raw?.image_path ? [raw.image_path] : []),
    [raw?.image_path],
  );

  return (
    <Layout>
      <div className="flex h-full flex-col">
        <PageHeader icon="equipment" title="设备装配图" subtitle={args.equipment_id ? `equipment_assembly · ${args.equipment_id}` : 'equipment_assembly'} color="orange" />
        {!isExtracting && <ProgressBanner />}
        <div className="flex-1 overflow-hidden">
          {/* 提取中：展示 SSE 事件时间线 */}
          {!raw && !progressError && (
            <ExtractionWithImage />
          )}
          {/* 进度数据加载错误 */}
          {progressError && !raw && (
            <ErrorBanner error={progressError} onRetry={() => window.location.reload()} />
          )}
          {raw && equipmentData && (
            <div className="grid h-full grid-cols-1 gap-3 p-3 lg:grid-cols-[320px_1fr]">
              {/* 左：源图预览 */}
              {imagePaths.length > 0 ? (
                <SourceImageViewer imagePaths={imagePaths} className="rounded-md border border-border" />
              ) : (
                <div className="flex items-center justify-center rounded-md border border-border bg-bg-2/40 text-xs text-text-3">
                  无源图
                </div>
              )}

              {/* 右：滚动审核区 */}
              <div className="flex flex-col gap-3 overflow-y-auto">
                {/* 基本信息 */}
                <SectionCard title="基本信息">
                  <div className="flex flex-col gap-1.5">
                    <Field
                      label="设备位号"
                      value={equipmentData.info?.equipment_tag ?? ''}
                      onChange={(v) => updateField('info.equipment_tag', v)}
                      readOnly={!canSubmit}
                    />
                    <Field
                      label="设备名称"
                      value={equipmentData.info?.equipment_name ?? ''}
                      onChange={(v) => updateField('info.equipment_name', v)}
                      readOnly={!canSubmit}
                    />
                    {equipmentType === 'column' && (
                      <>
                        <SelectField
                          label="塔型"
                          value={(equipmentData as DistillationColumn).column_type ?? 'unknown'}
                          options={[
                            { v: 'tray', l: '板式塔' },
                            { v: 'packed', l: '填料塔' },
                            { v: 'composite', l: '复合塔' },
                            { v: 'unknown', l: '未知' },
                          ]}
                          onChange={(v) => updateField('column_type', v)}
                          readOnly={!canSubmit}
                        />
                        <Field
                          label="塔板数/填料段数"
                          value={String((equipmentData as DistillationColumn).count ?? '')}
                          onChange={(v) => updateField('count', Math.max(0, Number(v) || 0))}
                          readOnly={!canSubmit}
                        />
                        <SelectField
                          label="编号方向"
                          value={(equipmentData as DistillationColumn).numbering_direction ?? ''}
                          options={[
                            { v: 'top_to_bottom', l: '自上而下' },
                            { v: 'bottom_to_top', l: '自下而上' },
                          ]}
                          onChange={(v) => updateField('numbering_direction', v)}
                          readOnly={!canSubmit}
                        />
                      </>
                    )}
                    {equipmentType === 'reactor' && (
                      <Field
                        label="反应器类型"
                        value={(equipmentData as ReactorDesign).reactor_type ?? ''}
                        onChange={(v) => updateField('reactor_type', v)}
                        readOnly={!canSubmit}
                      />
                    )}
                  </div>
                </SectionCard>

                {/* 尺寸参数 */}
                <SectionCard title="尺寸参数">
                  <div className="flex flex-col gap-1.5">
                    {equipmentType === 'column' && (
                      <>
                        <QuantityField
                          label="公称直径"
                          q={(equipmentData as DistillationColumn).nominal_diameter}
                          onChangeValue={(v) => updateField('nominal_diameter.value', v)}
                          onChangeUnit={(v) => updateField('nominal_diameter.unit', v)}
                          readOnly={!canSubmit}
                        />
                        <QuantityField
                          label="总高"
                          q={(equipmentData as DistillationColumn).total_height}
                          onChangeValue={(v) => updateField('total_height.value', v)}
                          onChangeUnit={(v) => updateField('total_height.unit', v)}
                          readOnly={!canSubmit}
                        />
                      </>
                    )}
                    {equipmentType === 'reactor' && (
                      <QuantityField
                        label="壳体直径"
                        q={(equipmentData as ReactorDesign).dimensions?.shell_diameter}
                        onChangeValue={(v) => updateField('dimensions.shell_diameter.value', v)}
                        onChangeUnit={(v) => updateField('dimensions.shell_diameter.unit', v)}
                        readOnly={!canSubmit}
                      />
                    )}
                  </div>
                </SectionCard>

                {/* 压力/温度（仅 column） */}
                {equipmentType === 'column' && (
                  <>
                    <SectionCard title="压力参数">
                      <div className="flex flex-col gap-1.5">
                        <QuantityField
                          label="设计压力"
                          q={(equipmentData as DistillationColumn).design_pressure}
                          onChangeValue={(v) => updateField('design_pressure.value', v)}
                          onChangeUnit={(v) => updateField('design_pressure.unit', v)}
                          readOnly={!canSubmit}
                        />
                        <QuantityField
                          label="操作压力(顶)"
                          q={(equipmentData as DistillationColumn).working_pressure?.top}
                          onChangeValue={(v) => updateField('working_pressure.top.value', v)}
                          onChangeUnit={(v) => updateField('working_pressure.top.unit', v)}
                          readOnly={!canSubmit}
                        />
                        <QuantityField
                          label="操作压力(底)"
                          q={(equipmentData as DistillationColumn).working_pressure?.bottom}
                          onChangeValue={(v) => updateField('working_pressure.bottom.value', v)}
                          onChangeUnit={(v) => updateField('working_pressure.bottom.unit', v)}
                          readOnly={!canSubmit}
                        />
                      </div>
                    </SectionCard>
                    <SectionCard title="温度参数">
                      <div className="flex flex-col gap-1.5">
                        <QuantityField
                          label="设计温度"
                          q={(equipmentData as DistillationColumn).design_temperature}
                          onChangeValue={(v) => updateField('design_temperature.value', v)}
                          onChangeUnit={(v) => updateField('design_temperature.unit', v)}
                          readOnly={!canSubmit}
                        />
                        <QuantityField
                          label="操作温度(顶)"
                          q={(equipmentData as DistillationColumn).working_temperature?.top}
                          onChangeValue={(v) => updateField('working_temperature.top.value', v)}
                          onChangeUnit={(v) => updateField('working_temperature.top.unit', v)}
                          readOnly={!canSubmit}
                        />
                        <QuantityField
                          label="操作温度(底)"
                          q={(equipmentData as DistillationColumn).working_temperature?.bottom}
                          onChangeValue={(v) => updateField('working_temperature.bottom.value', v)}
                          onChangeUnit={(v) => updateField('working_temperature.bottom.unit', v)}
                          readOnly={!canSubmit}
                        />
                      </div>
                    </SectionCard>
                  </>
                )}

                {/* 内件段（仅 column，可编辑表格） */}
                {equipmentType === 'column' &&
                  (equipmentData as DistillationColumn).internals_sections &&
                  (equipmentData as DistillationColumn).internals_sections!.length > 0 && (
                    <SectionCard
                      title="内件段"
                      count={(equipmentData as DistillationColumn).internals_sections!.length}
                    >
                      <EditableTable
                        rows={(equipmentData as DistillationColumn).internals_sections!}
                        columns={internalsColumns}
                        readOnly={!canSubmit}
                        onRowChange={() => {}}
                        onRowAdd={() =>
                          updateField('internals_sections', [
                            ...((equipmentData as DistillationColumn).internals_sections ?? []),
                            { from_no: 1, to_no: 1, type: 'tray' },
                          ])
                        }
                        onRowDelete={(idx) =>
                          updateField(
                            'internals_sections',
                            ((equipmentData as DistillationColumn).internals_sections ?? []).filter(
                              (_, i) => i !== idx,
                            ),
                          )
                        }
                      />
                    </SectionCard>
                  )}

                {/* 塔体示意图（仅 column） */}
                {equipmentType === 'column' && (
                  <SectionCard title="塔体示意图">
                    <TowerSchematic
                      sections={(equipmentData as DistillationColumn).internals_sections ?? []}
                      nozzles={(equipmentData as DistillationColumn).nozzles ?? []}
                    />
                  </SectionCard>
                )}

                {/* 接管列表 */}
                {equipmentData.nozzles && equipmentData.nozzles.length > 0 && (
                  <SectionCard title="接管" count={equipmentData.nozzles.length}>
                    <div className="flex flex-col gap-1.5">
                      {equipmentData.nozzles.map((nz, i) => (
                        <div
                          key={i}
                          className="rounded border-l-2 border border-border bg-bg/60 px-2 py-1.5 text-[11px]"
                          style={{ borderLeftColor: nozzleColor(nz.nozzle_role) }}
                        >
                          <div className="flex items-center gap-2">
                            <TagBadge color={nozzleTagColor(nz.nozzle_role)}>
                              {nz.nozzle_id || '-'}
                            </TagBadge>
                            {nz.nominal_size && (
                              <span className="rounded bg-bg-3 px-1 py-0.5 text-[10px] text-text-2">
                                {nz.nominal_size}
                              </span>
                            )}
                            {nz.nozzle_role && (
                              <span className="rounded bg-bg-3 px-1 py-0.5 text-[10px] text-text-3">
                                {nz.nozzle_role}
                              </span>
                            )}
                            <span className="ml-auto text-[10px] text-text-3">
                              EL {nz.elevation?.value ?? '-'}
                            </span>
                          </div>
                          {nz.service_description && (
                            <div className="mt-0.5 text-text-2">{nz.service_description}</div>
                          )}
                        </div>
                      ))}
                    </div>
                  </SectionCard>
                )}

                {/* 警告 */}
                <WarningsList warnings={equipmentData.warnings ?? []} />
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
          dirty={dirty}
          onReset={reset}
        />
      </div>
      {toast}
      <JsonDrawer data={raw} disabled={isExtracting} />
    </Layout>
  );
}