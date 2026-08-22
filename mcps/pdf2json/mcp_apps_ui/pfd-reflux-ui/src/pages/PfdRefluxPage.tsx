/**
 * PFD 回流结构审核页（pfd_reflux 工具）。
 *
 * 数据结构（pfd_reflux 任务的 final_result）：
 *   {
 *     status: 'success' | 'partial',
 *     workflow: 'pfd_reflux',
 *     image_path?: string,
 *     expert_outputs: { pfd_reflux: { data: { towers, reactors, warnings } } },
 *     towers: TowerInfo[],
 *     reactors: ReactorInfo[],
 *     warnings: string[]
 *   }
 *
 * TowerInfo: { tag, name, reflux_structure, reflux_detail?, operating_conditions }
 * ReactorInfo: { tag, name, reflux_structure, operating_conditions }
 *
 * 表单编辑：位号/名称/回流结构/回流详情/操作条件均可编辑。
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Layout } from '@/components/Layout';
import { PageHeader } from '@/components/PageHeader';
import { ProgressBanner } from '@/components/ProgressBanner';
import { ReviewToolbar } from '@/components/ReviewToolbar';
import { JsonDrawer } from '@/components/JsonDrawer';
import { ErrorBanner } from '@/components/ErrorBanner';
import { useToast } from '@/components/Toast';
import { ExtractionWithImage } from '@/components/ExtractionWithImage';
import { useMcpApp, useNormalizedToolResult } from '@/core/mcpApp';
import { useReviewStatus, submitReview } from '@/patterns/review';
import { useEditedData } from '@/core/hooks/useEditedData';
import { useDirtyGuard } from '@/core/hooks/useDirtyGuard';
import {
  Field,
  QuantityField,
  SelectField,
  CheckboxField,
  InfoCell,
  TagBadge,
  SectionCard,
  WarningsList,
} from '@/components/common';
import { SourceImageViewer } from '@/components/common/SourceImageViewer';
import { RefluxDiagram } from './pfd-reflux/RefluxDiagram';

// ===================== 类型 =====================

interface Quantity {
  value?: number | null;
  unit?: string;
}

interface RefluxStructure {
  has_reflux?: boolean;
  reflux_type?: string; // none | top | bottom | top_and_bottom
  description?: string;
}

interface TowerRefluxDetail {
  has_top_condenser?: boolean | null;
  has_bottom_reboiler?: boolean | null;
  top_condenser_tag?: string;
  bottom_reboiler_tag?: string;
  reflux_flow_rate?: Quantity;
}

interface TowerOperatingConditions {
  top_temperature?: Quantity;
  top_pressure?: Quantity;
  bottom_temperature?: Quantity;
  bottom_pressure?: Quantity;
}

interface TowerInfo {
  tag: string;
  name?: string;
  reflux_structure?: RefluxStructure;
  reflux_detail?: TowerRefluxDetail | null;
  operating_conditions?: TowerOperatingConditions;
}

interface ReactorOperatingConditions {
  temperature?: Quantity;
  pressure?: Quantity;
}

interface ReactorInfo {
  tag: string;
  name?: string;
  reflux_structure?: RefluxStructure;
  operating_conditions?: ReactorOperatingConditions;
}

interface PfdRefluxResult {
  status?: string;
  workflow?: string;
  image_path?: string;
  expert_outputs?: {
    pfd_reflux?: {
      data?: {
        towers?: TowerInfo[];
        reactors?: ReactorInfo[];
        warnings?: string[];
      };
    };
  };
  towers?: TowerInfo[];
  reactors?: ReactorInfo[];
  warnings?: string[];
}

// ===================== 常量 =====================

const REFLUX_TYPE_OPTIONS = [
  { v: 'none', l: '无回流' },
  { v: 'top', l: '仅塔顶回流' },
  { v: 'bottom', l: '仅塔釜回流' },
  { v: 'top_and_bottom', l: '塔顶与塔釜均有' },
];

const TRI_STATE_OPTIONS = [
  { v: 'true', l: '是' },
  { v: 'false', l: '否' },
  { v: '', l: '无法判断' },
];

function triToBool(v: unknown): boolean | null {
  if (v === true || v === 'true') return true;
  if (v === false || v === 'false') return false;
  return null;
}

function boolToTri(v: unknown): string {
  if (v === true) return 'true';
  if (v === false) return 'false';
  return '';
}

// ===================== 组件 =====================

export function PfdRefluxPage() {
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

  const finalResult = (rawFinalResult ?? null) as PfdRefluxResult | null;

  // 编辑副本管理（修复 editedData 不回写 bug）
  const { data, updatePath, getEdited, dirty, reset } = useEditedData<PfdRefluxResult>(finalResult);
  useDirtyGuard(dirty);

  const canSubmit = status === 'waiting_review';
  const isTerminal = status === 'completed' || status === 'error';
  const isExtracting = !canSubmit && !isTerminal;

  const raw = data ?? finalResult;

  const towers = raw?.towers ?? [];
  const reactors = raw?.reactors ?? [];
  const warnings = raw?.warnings ?? [];

  /** 更新塔字段：towers[index].path = value，同步到 expert_outputs。 */
  const updateTower = useCallback(
    (index: number, path: string, value: unknown) => {
      updatePath(`towers.${index}.${path}`, value);
      // 同步 expert_outputs（若存在）
      if (finalResult?.expert_outputs?.pfd_reflux?.data?.towers) {
        updatePath(`expert_outputs.pfd_reflux.data.towers.${index}.${path}`, value);
      }
    },
    [updatePath, finalResult],
  );

  /** 更新反应器字段。 */
  const updateReactor = useCallback(
    (index: number, path: string, value: unknown) => {
      updatePath(`reactors.${index}.${path}`, value);
      if (finalResult?.expert_outputs?.pfd_reflux?.data?.reactors) {
        updatePath(`expert_outputs.pfd_reflux.data.reactors.${index}.${path}`, value);
      }
    },
    [updatePath, finalResult],
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
    if (isExtracting) return '提取进行中…';
    return '等待中…';
  }, [isTerminal, canSubmit, isExtracting, raw, app]);

  // 多塔回流统计
  const refluxStats = useMemo(() => {
    let topCount = 0;
    let bottomCount = 0;
    let noneCount = 0;
    for (const t of towers) {
      const rt = t.reflux_structure?.reflux_type ?? 'none';
      if (rt === 'top' || rt === 'top_and_bottom') topCount++;
      if (rt === 'bottom' || rt === 'top_and_bottom') bottomCount++;
      if (rt === 'none' && !t.reflux_structure?.has_reflux) noneCount++;
    }
    return { topCount, bottomCount, noneCount };
  }, [towers]);

  const imagePaths = useMemo(
    () => (finalResult?.image_path ? [finalResult.image_path] : []),
    [finalResult],
  );

  return (
    <Layout>
      <div className="flex h-full flex-col">
        <PageHeader icon="reflux" title="PFD 回流结构" subtitle="pfd_reflux" color="yellow" />
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
                {/* 元信息 */}
                <SectionCard title="提取元信息">
                  <div className="grid grid-cols-3 gap-3">
                    <InfoCell label="状态" value={raw.status || '-'} highlight={raw.status === 'success' ? 'green' : 'orange'} />
                    <InfoCell label="塔数量" value={towers.length} />
                    <InfoCell label="反应器数量" value={reactors.length} />
                  </div>
                </SectionCard>

                {/* 多塔回流统计条 */}
                {towers.length > 0 && (
                  <div className="flex items-center gap-3 rounded-md border border-border bg-bg-2/60 px-4 py-2 text-xs">
                    <span className="font-bold text-text">回流统计：</span>
                    <TagBadge color="green">塔顶回流 {refluxStats.topCount}</TagBadge>
                    <TagBadge color="orange">塔釜回流 {refluxStats.bottomCount}</TagBadge>
                    <TagBadge color="accent">无回流 {refluxStats.noneCount}</TagBadge>
                  </div>
                )}

                {/* 塔列表 */}
                {towers.length > 0 && (
                  <SectionCard title="塔" count={towers.length}>
                    <div className="flex flex-col gap-3">
                      {towers.map((tower, i) => (
                        <TowerCard
                          key={i}
                          tower={tower}
                          readOnly={!canSubmit}
                          onUpdate={(path, value) => updateTower(i, path, value)}
                        />
                      ))}
                    </div>
                  </SectionCard>
                )}

                {/* 反应器列表 */}
                {reactors.length > 0 && (
                  <SectionCard title="反应器" count={reactors.length} accent="purple">
                    <div className="flex flex-col gap-3">
                      {reactors.map((reactor, i) => (
                        <ReactorCard
                          key={i}
                          reactor={reactor}
                          readOnly={!canSubmit}
                          onUpdate={(path, value) => updateReactor(i, path, value)}
                        />
                      ))}
                    </div>
                  </SectionCard>
                )}

                {/* 警告 */}
                <WarningsList warnings={warnings} />
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

// ===================== 塔卡片 =====================

function TowerCard({
  tower,
  readOnly,
  onUpdate,
}: {
  tower: TowerInfo;
  readOnly: boolean;
  onUpdate: (path: string, value: unknown) => void;
}) {
  const rs = tower.reflux_structure ?? {};
  const rd = tower.reflux_detail;
  const oc = tower.operating_conditions ?? {};
  const hasReflux = rs.has_reflux ?? false;

  return (
    <div className="rounded-md border border-border bg-bg/60 p-3">
      {/* 头部：位号 + 名称 + 回流示意图 */}
      <div className="mb-3 flex items-start gap-3">
        <div className="flex-1">
          <div className="mb-3 flex items-center gap-2">
            <TagBadge color="accent">{tower.tag || '-'}</TagBadge>
            <input
              type="text"
              className="flex-1 rounded border border-border bg-bg px-2 py-1 text-xs text-text outline-none focus:border-accent disabled:opacity-70"
              value={tower.name ?? ''}
              onChange={(e) => onUpdate('name', e.target.value)}
              readOnly={readOnly}
              placeholder="塔名称"
            />
          </div>
        </div>
        {/* 回流示意图 */}
        <div className="w-48 shrink-0 rounded border border-border bg-bg-2/40 p-1">
          <RefluxDiagram
            hasTopCondenser={rd?.has_top_condenser}
            hasBottomReboiler={rd?.has_bottom_reboiler}
            topCondenserTag={rd?.top_condenser_tag}
            bottomReboilerTag={rd?.bottom_reboiler_tag}
            refluxType={rs.reflux_type}
          />
        </div>
      </div>

      {/* 回流结构 */}
      <SubSection title="回流结构">
        <CheckboxField
          label="存在回流"
          checked={hasReflux}
          readOnly={readOnly}
          onChange={(v) => {
            onUpdate('reflux_structure.has_reflux', v);
            if (!v) onUpdate('reflux_detail', null);
          }}
        />
        <SelectField
          label="回流类型"
          value={rs.reflux_type ?? 'none'}
          options={REFLUX_TYPE_OPTIONS}
          readOnly={readOnly}
          onChange={(v) => onUpdate('reflux_structure.reflux_type', v)}
        />
        <div>
          <div className="mb-1 text-[11px] text-text-3">描述</div>
          <textarea
            className="min-h-[50px] w-full resize-y rounded border border-border bg-bg px-2 py-1 text-xs text-text outline-none focus:border-accent disabled:opacity-70"
            value={rs.description ?? ''}
            onChange={(e) => onUpdate('reflux_structure.description', e.target.value)}
            readOnly={readOnly}
            placeholder="(无)"
          />
        </div>
      </SubSection>

      {/* 回流详情（仅 has_reflux=true） */}
      {hasReflux && rd && (
        <SubSection title="回流详情">
          <SelectField
            label="塔顶冷凝器"
            value={boolToTri(rd.has_top_condenser)}
            options={TRI_STATE_OPTIONS}
            readOnly={readOnly}
            onChange={(v) => onUpdate('reflux_detail.has_top_condenser', triToBool(v))}
          />
          <SelectField
            label="塔釜再沸器"
            value={boolToTri(rd.has_bottom_reboiler)}
            options={TRI_STATE_OPTIONS}
            readOnly={readOnly}
            onChange={(v) => onUpdate('reflux_detail.has_bottom_reboiler', triToBool(v))}
          />
          <Field
            label="冷凝器位号"
            value={rd.top_condenser_tag ?? ''}
            readOnly={readOnly}
            onChange={(v) => onUpdate('reflux_detail.top_condenser_tag', v)}
          />
          <Field
            label="再沸器位号"
            value={rd.bottom_reboiler_tag ?? ''}
            readOnly={readOnly}
            onChange={(v) => onUpdate('reflux_detail.bottom_reboiler_tag', v)}
          />
          <QuantityField
            label="回流量"
            q={rd.reflux_flow_rate}
            readOnly={readOnly}
            onChangeValue={(v) => onUpdate('reflux_detail.reflux_flow_rate.value', v)}
            onChangeUnit={(v) => onUpdate('reflux_detail.reflux_flow_rate.unit', v)}
          />
        </SubSection>
      )}

      {/* 操作条件 */}
      <SubSection title="操作条件">
        <QuantityField
          label="塔顶温度"
          q={oc.top_temperature}
          readOnly={readOnly}
          min={0}
          onChangeValue={(v) => onUpdate('operating_conditions.top_temperature.value', v)}
          onChangeUnit={(v) => onUpdate('operating_conditions.top_temperature.unit', v)}
        />
        <QuantityField
          label="塔顶压力"
          q={oc.top_pressure}
          readOnly={readOnly}
          min={0}
          onChangeValue={(v) => onUpdate('operating_conditions.top_pressure.value', v)}
          onChangeUnit={(v) => onUpdate('operating_conditions.top_pressure.unit', v)}
        />
        <QuantityField
          label="塔釜温度"
          q={oc.bottom_temperature}
          readOnly={readOnly}
          min={0}
          onChangeValue={(v) => onUpdate('operating_conditions.bottom_temperature.value', v)}
          onChangeUnit={(v) => onUpdate('operating_conditions.bottom_temperature.unit', v)}
        />
        <QuantityField
          label="塔釜压力"
          q={oc.bottom_pressure}
          readOnly={readOnly}
          min={0}
          onChangeValue={(v) => onUpdate('operating_conditions.bottom_pressure.value', v)}
          onChangeUnit={(v) => onUpdate('operating_conditions.bottom_pressure.unit', v)}
        />
      </SubSection>
    </div>
  );
}

// ===================== 反应器卡片 =====================

function ReactorCard({
  reactor,
  readOnly,
  onUpdate,
}: {
  reactor: ReactorInfo;
  readOnly: boolean;
  onUpdate: (path: string, value: unknown) => void;
}) {
  const rs = reactor.reflux_structure ?? {};
  const oc = reactor.operating_conditions ?? {};

  return (
    <div className="rounded-md border border-border bg-bg/60 p-3">
      {/* 头部 */}
      <div className="mb-3 flex items-center gap-2">
        <TagBadge color="purple">{reactor.tag || '-'}</TagBadge>
        <input
          type="text"
          className="flex-1 rounded border border-border bg-bg px-2 py-1 text-xs text-text outline-none focus:border-accent disabled:opacity-70"
          value={reactor.name ?? ''}
          onChange={(e) => onUpdate('name', e.target.value)}
          readOnly={readOnly}
          placeholder="反应器名称"
        />
      </div>

      {/* 回流/循环结构 */}
      <SubSection title="回流/循环结构">
        <CheckboxField
          label="存在回流"
          checked={rs.has_reflux ?? false}
          readOnly={readOnly}
          onChange={(v) => onUpdate('reflux_structure.has_reflux', v)}
        />
        <SelectField
          label="回流类型"
          value={rs.reflux_type ?? 'none'}
          options={REFLUX_TYPE_OPTIONS}
          readOnly={readOnly}
          onChange={(v) => onUpdate('reflux_structure.reflux_type', v)}
        />
        <div>
          <div className="mb-1 text-[11px] text-text-3">描述</div>
          <textarea
            className="min-h-[50px] w-full resize-y rounded border border-border bg-bg px-2 py-1 text-xs text-text outline-none focus:border-accent disabled:opacity-70"
            value={rs.description ?? ''}
            onChange={(e) => onUpdate('reflux_structure.description', e.target.value)}
            readOnly={readOnly}
            placeholder="(无)"
          />
        </div>
      </SubSection>

      {/* 操作条件 */}
      <SubSection title="操作条件">
        <QuantityField
          label="温度"
          q={oc.temperature}
          readOnly={readOnly}
          min={0}
          onChangeValue={(v) => onUpdate('operating_conditions.temperature.value', v)}
          onChangeUnit={(v) => onUpdate('operating_conditions.temperature.unit', v)}
        />
        <QuantityField
          label="压力"
          q={oc.pressure}
          readOnly={readOnly}
          min={0}
          onChangeValue={(v) => onUpdate('operating_conditions.pressure.value', v)}
          onChangeUnit={(v) => onUpdate('operating_conditions.pressure.unit', v)}
        />
      </SubSection>
    </div>
  );
}

// ===================== 页面内私有子组件 =====================

function SubSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="mb-2.5">
      <div className="mb-1.5 text-[11px] font-bold text-text-2">{title}</div>
      <div className="flex flex-col gap-1.5">{children}</div>
    </div>
  );
}