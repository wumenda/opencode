/**
 * 工艺包章节审核页（替代 generic_review.html）。
 *
 * 数据结构（process_package 任务的 final_result）：
 *   {
 *     status: 'success' | 'partial',
 *     total_pages, matched_section_count, filtered_text_length,
 *     pdf_path, locator,
 *     matched_sections: [{ title, level, start_page, end_page, page_count, filtered_text? }],
 *     expert_outputs: {
 *       process_package: { operation_description, reaction_equation }
 *     },
 *     warnings: [{ message } | string, ...]
 *   }
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
import { useMcpApp, useNormalizedToolResult, useToolInput } from '@/core/mcpApp';
import { useReviewStatus, submitReview } from '@/patterns/review';
import { useEditedData } from '@/core/hooks/useEditedData';
import { useDirtyGuard } from '@/core/hooks/useDirtyGuard';
import { usePdfDocument } from '@/hooks/usePdfDocument';
import { InfoCell, SectionCard, WarningsList, TagBadge } from '@/components/common';

interface ProcessPackageResult {
  status?: string;
  total_pages?: number;
  matched_section_count?: number;
  filtered_text_length?: number;
  pdf_path?: string;
  locator?: string;
  matched_sections?: Array<{
    title?: string;
    level?: number;
    start_page?: number;
    end_page?: number;
    page_count?: number;
    filtered_text?: string;
  }>;
  expert_outputs?: {
    process_package?: {
      operation_description?: string;
      reaction_equation?: string;
    };
  };
  warnings?: Array<string | { message?: string }>;
}

export function GenericReviewPage() {
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

  // 章节选中 + 预览模式
  const [selectedSectionIdx, setSelectedSectionIdx] = useState(0);
  const [previewMode, setPreviewMode] = useState<'edit' | 'preview'>('edit');

  const finalResult = (rawFinalResult ?? null) as ProcessPackageResult | null;
  const { data, updatePath, getEdited, dirty, reset } = useEditedData<ProcessPackageResult>(finalResult);
  useDirtyGuard(dirty);

  const canSubmit = status === 'waiting_review';
  const isTerminal = status === 'completed' || status === 'error';
  const isExtracting = !canSubmit && !isTerminal;

  // tool 入参（chapter 定位方式透出到元信息卡片）
  const toolInput = useToolInput();
  const args = (toolInput?.args ?? {}) as Record<string, unknown>;

  // partial 数据派生（提取阶段）：final_result 就绪后不使用 partial
  const partialData = useMemo<ProcessPackageResult | null>(() => {
    if (finalResult) return null;
    const partialSections = app.progress?.uiEvent?.partial_matched_sections as
      | ProcessPackageResult['matched_sections']
      | undefined;
    const partialPdfPath = app.progress?.uiEvent?.partial_pdf_path as string | undefined;
    const partialTotalPages = app.progress?.uiEvent?.partial_total_pages as number | undefined;
    // 收到 PDF（partial_pdf_path）即可进入审核布局，渲染 PDF 首图；章节待抽取后再填入
    if (!partialPdfPath) return null;
    return {
      status: 'extracting',
      matched_sections: partialSections || [],
      matched_section_count: partialSections?.length ?? 0,
      pdf_path: partialPdfPath,
      total_pages: partialTotalPages,
      // expert_outputs 暂无（Phase 2 才有），UI 端用占位
    };
  }, [
    app.progress?.uiEvent?.partial_matched_sections,
    app.progress?.uiEvent?.partial_pdf_path,
    app.progress?.uiEvent?.partial_total_pages,
    finalResult,
  ]);

  const raw = data ?? finalResult ?? partialData;

  const pkg = raw?.expert_outputs?.process_package || {};
  const opDesc = pkg.operation_description ?? '';
  const rxnEq = pkg.reaction_equation ?? '';

  const sections = raw?.matched_sections || [];
  const selectedSection = sections[selectedSectionIdx];

  // PDF 文档加载：PDF 已接收（pdf_path 就绪）即发起 read_pdf，在左侧用 iframe 渲染整份 PDF
  const { url: pdfUrl, loading: pdfLoading, error: pdfError } = usePdfDocument(raw?.pdf_path);

  const warnings = useMemo(() => {
    if (!raw?.warnings) return [];
    return raw.warnings.map((w) =>
      typeof w === 'string' ? w : w?.message || JSON.stringify(w),
    );
  }, [raw]);

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
      const sectionCount = sections.length;
      if (sectionCount > 0) {
        return `提取进行中…（已定位 ${sectionCount} 章节）`;
      }
      return '提取进行中…';
    }
    return '等待中…';
  }, [isTerminal, canSubmit, isExtracting, raw, app, sections.length]);

  // 结构化预览：工序说明按空行分段
  const opDescParagraphs = useMemo(() => {
    if (!opDesc.trim()) return [];
    return opDesc.split(/\n\s*\n/).filter((p) => p.trim());
  }, [opDesc]);

  // 结构化预览：反应方程式按行分割
  const rxnEqLines = useMemo(() => {
    if (!rxnEq.trim()) return [];
    return rxnEq.split('\n').filter((l) => l.trim());
  }, [rxnEq]);

  return (
    <Layout>
      <div className="flex h-full flex-col">
        <PageHeader icon="document" title="工艺包章节" subtitle="process_package" color="green" />
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
            <div className="grid h-full grid-cols-1 gap-3 p-3 lg:grid-cols-[280px_1fr]">
              {/* 左：章节列表 + 选中章节首页 PDF 图预览 */}
              <div className="flex flex-col overflow-hidden rounded-md border border-border bg-bg-2/40">
                <div className="border-b border-border bg-bg-2/60 px-3 py-2 text-xs font-bold text-text">
                  匹配章节（{sections.length}）
                </div>
                {/* 选中章节首页 PDF 图预览 */}
                {(pdfUrl || pdfLoading || pdfError) && (
                  <div className="border-b border-border bg-bg p-2">
                    {pdfLoading && (
                      <div className="flex h-40 items-center justify-center text-[11px] text-text-3">
                        加载 PDF…
                      </div>
                    )}
                    {!pdfLoading && pdfError && (
                      <div className="rounded border border-red/30 bg-red/5 p-2 text-[10px] text-red">
                        PDF 加载失败：{pdfError}
                      </div>
                    )}
                    {!pdfLoading && !pdfError && pdfUrl && (
                      <iframe
                        src={pdfUrl}
                        title="PDF 预览"
                        className="h-64 w-full rounded border border-border bg-white"
                      />
                    )}
                  </div>
                )}
                <div className="flex-1 overflow-y-auto p-1.5">
                  {sections.length === 0 ? (
                    <div className="py-6 text-center text-xs text-text-3">无匹配章节</div>
                  ) : (
                    sections.map((s, i) => (
                      <button
                        key={i}
                        type="button"
                        onClick={() => setSelectedSectionIdx(i)}
                        className={`mb-1 w-full rounded border px-2.5 py-2 text-left text-xs ${
                          i === selectedSectionIdx
                            ? 'border-accent bg-accent/5 text-text'
                            : 'border-border bg-bg/60 text-text-2 hover:bg-bg-3/40'
                        }`}
                      >
                        <div className="flex items-center gap-1.5">
                          <TagBadge color={s.level === 1 ? 'accent' : 'cyan'}>L{s.level ?? '-'}</TagBadge>
                          <span className="font-semibold">{s.title || '(无标题)'}</span>
                        </div>
                        <div className="mt-1 font-mono text-[10px] text-text-3">
                          P{s.start_page ?? '?'}-{s.end_page ?? '?'} · {s.page_count ?? '?'}页
                        </div>
                      </button>
                    ))
                  )}
                </div>
              </div>

              {/* 右：滚动审核区 */}
              <div className="flex flex-col gap-3 overflow-y-auto">
                {/* 选中章节详情 */}
                {selectedSection && (
                  <SectionCard title={selectedSection.title || '(无标题)'} accent="cyan">
                    <div className="mb-2 flex items-center gap-3 text-[11px] text-text-3">
                      <span>层级 {selectedSection.level ?? '-'}</span>
                      <span>页码 {selectedSection.start_page ?? '?'}-{selectedSection.end_page ?? '?'}</span>
                      <span>{selectedSection.page_count ?? '?'} 页</span>
                    </div>
                    {selectedSection.filtered_text ? (
                      <CollapsibleText text={selectedSection.filtered_text} maxChars={500} />
                    ) : (
                      <div className="text-xs text-text-3">（无章节文本摘要）</div>
                    )}
                  </SectionCard>
                )}

                {/* 元信息 */}
                <SectionCard title="提取元信息">
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
                    <InfoCell label="状态" value={raw.status || '-'} highlight={raw.status === 'success' ? 'green' : 'orange'} />
                    <InfoCell label="总页数" value={raw.total_pages ?? '-'} />
                    <InfoCell label="匹配章节数" value={raw.matched_section_count ?? '-'} />
                    <InfoCell label="筛选文本长度" value={raw.filtered_text_length ?? '-'} />
                    <InfoCell label="定位器" value={raw.locator || '-'} />
                    <InfoCell
                      label="定位方式"
                      value={args.chapter_index != null ? `章节序号 ${args.chapter_index}` : args.chapter_title ? `标题"${args.chapter_title}"` : '-'}
                    />
                  </div>
                  <div className="mt-3 break-all rounded bg-bg-3/40 px-3 py-2 font-mono text-[11px] text-text-2">
                    {raw.pdf_path || '-'}
                  </div>
                </SectionCard>

                {/* 工序说明 / 反应方程式（可编辑 + 结构化预览切换） */}
                <SectionCard
                  title={isExtracting && !opDesc && !rxnEq ? '工序说明 / 反应方程式（提取中…）' : '工序说明 / 反应方程式'}
                  accent={canSubmit ? 'orange' : 'accent'}
                >
                  <div className="mb-3 flex items-center gap-2">
                    <span className="text-[11px] text-text-3">模式：</span>
                    <button
                      type="button"
                      className={`rounded px-2 py-0.5 text-[11px] transition ${previewMode === 'edit' ? 'bg-accent text-white' : 'bg-bg-3 text-text-2 hover:bg-bg-3/70 hover:text-text'}`}
                      onClick={() => setPreviewMode('edit')}
                    >
                      编辑
                    </button>
                    <button
                      type="button"
                      className={`rounded px-2 py-0.5 text-[11px] transition ${previewMode === 'preview' ? 'bg-accent text-white' : 'bg-bg-3 text-text-2 hover:bg-bg-3/70 hover:text-text'}`}
                      onClick={() => setPreviewMode('preview')}
                    >
                      结构化预览
                    </button>
                  </div>

                  <div className="grid gap-3 lg:grid-cols-2">
                    {/* 工序说明 */}
                    <div>
                      <div className="mb-1 text-[11px] text-text-3">operation_description</div>
                      {previewMode === 'edit' ? (
                        <textarea
                          className="min-h-[160px] w-full resize-y rounded-md border border-border bg-bg px-3 py-2 font-mono text-xs leading-relaxed text-text outline-none focus:border-accent disabled:opacity-70"
                          value={opDesc}
                          onChange={(e) => updatePath('expert_outputs.process_package.operation_description', e.target.value)}
                          readOnly={!canSubmit || isExtracting}
                          placeholder="(空)"
                        />
                      ) : (
                        <div className="min-h-[160px] rounded-md border border-border bg-bg/60 p-3">
                          {opDescParagraphs.length > 0 ? (
                            opDescParagraphs.map((p, i) => (
                              <p key={i} className="mb-2 text-xs leading-relaxed text-text">{p.trim()}</p>
                            ))
                          ) : (
                            <div className="text-xs text-text-3">（空）</div>
                          )}
                        </div>
                      )}
                    </div>

                    {/* 反应方程式 */}
                    <div>
                      <div className="mb-1 text-[11px] text-text-3">reaction_equation</div>
                      {previewMode === 'edit' ? (
                        <textarea
                          className="min-h-[160px] w-full resize-y rounded-md border border-border bg-bg px-3 py-2 font-mono text-xs leading-relaxed text-text outline-none focus:border-accent disabled:opacity-70"
                          value={rxnEq}
                          onChange={(e) => updatePath('expert_outputs.process_package.reaction_equation', e.target.value)}
                          readOnly={!canSubmit || isExtracting}
                          placeholder="(空)"
                        />
                      ) : (
                        <div className="flex min-h-[160px] flex-col gap-1.5 rounded-md border border-border bg-bg/60 p-3">
                          {rxnEqLines.length > 0 ? (
                            rxnEqLines.map((l, i) => (
                              <code key={i} className="rounded bg-bg-3/60 px-2 py-1 font-mono text-xs text-text">{l.trim()}</code>
                            ))
                          ) : (
                            <div className="text-xs text-text-3">（空）</div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                </SectionCard>

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

/** 可折叠文本：默认显示前 maxChars 字符，点击展开全部。 */
function CollapsibleText({ text, maxChars = 500 }: { text: string; maxChars?: number }) {
  const [expanded, setExpanded] = useState(false);
  const display = expanded ? text : text.slice(0, maxChars);
  const needCollapse = text.length > maxChars;

  return (
    <div>
      <pre className="whitespace-pre-wrap break-words rounded bg-bg/60 p-2 font-mono text-[11px] leading-relaxed text-text-2">
        {display}
        {!expanded && needCollapse && <span className="text-text-3">…</span>}
      </pre>
      {needCollapse && (
        <button
          type="button"
          className="mt-1 text-[11px] text-accent hover:underline"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? '收起' : '展开全部'}
        </button>
      )}
    </div>
  );
}
