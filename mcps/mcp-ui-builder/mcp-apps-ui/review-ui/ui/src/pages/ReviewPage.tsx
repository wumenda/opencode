/**
 * 示例页：完整审核流程。
 *
 * 适合：工具执行后需要人工审核/编辑/确认再提交的场景。
 * 流程：等待工具入参 -> 展示提取进度 -> 等待用户审核 -> 提交审核 -> 完成。
 *
 * 同事改为自己的业务：替换 ReviewResult 类型 + 渲染逻辑即可。
 */

import { useCallback, useMemo, useState } from 'react';
import { Layout } from '@/components/Layout';
import { PageHeader } from '@/components/PageHeader';
import { ProgressBanner } from '@/components/ProgressBanner';
import { ReviewToolbar } from '@/components/ReviewToolbar';
import { JsonDrawer } from '@/components/JsonDrawer';
import { ErrorBanner } from '@/components/ErrorBanner';
import { useToast } from '@/components/Toast';
import { TaskWithImage } from '@/components/TaskWithImage';
import { useMcpApp } from '@/core/mcpApp';
import { useReviewStatus, useReviewResult, submitReview } from '@/patterns/review';
import { useEditedData } from '@/core/hooks/useEditedData';
import { useDirtyGuard } from '@/core/hooks/useDirtyGuard';
import { SectionCard, InfoCell } from '@/components/common';

/** 示例结果类型 -- 改成你的工具返回结构。 */
interface ReviewResult {
  status?: string;
  message?: string;
  items?: Array<{ id?: string; name?: string; value?: string }>;
  warnings?: string[];
  /** review_tool 通过 read_image 读取的源图 data URL。 */
  image_url?: string;
  /** 源图读取失败原因。 */
  image_error?: string;
}

export function ReviewPage() {
  const app = useMcpApp();
  const { finalResult: rawFinalResult, isError } = useReviewResult();
  const status = useReviewStatus();
  const progressError = isError ? app.error : null;
  const { toast, show } = useToast();
  const [submitting, setSubmitting] = useState(false);
  const [resultMessage, setResultMessage] = useState<{
    type: 'success' | 'error';
    text: string;
  } | null>(null);

  const finalResult = (rawFinalResult ?? null) as ReviewResult | null;
  const { data, updatePath, getEdited, dirty, reset } = useEditedData<ReviewResult>(finalResult);
  useDirtyGuard(dirty);

  const canSubmit = status === 'waiting_review';
  const isTerminal = status === 'completed' || status === 'error';
  const isProcessing = !canSubmit && !isTerminal;

  const raw = data ?? finalResult;

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
          text: approved ? `审核通过:${resp.message}` : `已驳回:${reason || '未提供原因'}`,
        });
        show('审核已提交', 'success');
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setResultMessage({ type: 'error', text: msg });
        show(`提交失败:${msg}`, 'error');
      } finally {
        setSubmitting(false);
      }
    },
    [getEdited, show],
  );

  const statusHint = useMemo(() => {
    if (isTerminal) return raw ? '审核已完成' : (app.error || '已结束');
    if (canSubmit) return '审核数据已就绪,请审核后提交';
    if (isProcessing) return '执行中…';
    return '等待中…';
  }, [isTerminal, canSubmit, isProcessing, raw, app.error]);

  const warnings = raw?.warnings ?? [];

  return (
    <Layout>
      <div className="flex h-full flex-col">
        <PageHeader icon="document" title="示例审核" subtitle="review_tool" color="accent" />
        {!isProcessing && <ProgressBanner />}
        <div className="flex-1 overflow-hidden">
          {/* 执行中 */}
          {!raw && !progressError && <TaskWithImage />}
          {progressError && !raw && (
            <ErrorBanner error={progressError} onRetry={() => window.location.reload()} />
          )}
          {raw && (
            <div className="flex flex-col gap-3 overflow-y-auto p-4">
              {/* 源图（review_tool 通过 read_image 读取后推送） */}
              {(raw.image_url || raw.image_error) && (
                <SectionCard title="源图">
                  {raw.image_url ? (
                    <img
                      src={raw.image_url}
                      alt="源图"
                      className="max-h-[320px] w-full rounded-lg border border-border object-contain bg-bg"
                    />
                  ) : (
                    <div className="rounded-lg bg-red/5 p-3 text-xs text-red">
                      源图读取失败：{raw.image_error}
                    </div>
                  )}
                </SectionCard>
              )}

              {/* 元信息 */}
              <SectionCard title="提取元信息">
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                  <InfoCell label="状态" value={raw.status || '-'} highlight={raw.status === 'success' ? 'green' : 'orange'} />
                  <InfoCell label="消息" value={raw.message ?? '-'} />
                  <InfoCell label="条目数" value={raw.items?.length ?? 0} />
                </div>
              </SectionCard>

              {/* 可编辑消息(示例:演示 useEditedData) */}
              <SectionCard title="消息(可编辑)" accent={canSubmit ? 'orange' : 'accent'}>
                <textarea
                  className="min-h-[80px] w-full resize-y rounded-lg border border-border bg-bg-2 px-3 py-2 font-mono text-xs text-text outline-none focus:border-accent focus:ring-2 focus:ring-accent/20 disabled:opacity-70"
                  value={raw.message ?? ''}
                  onChange={(e) => updatePath('message', e.target.value)}
                  readOnly={!canSubmit}
                  placeholder="(空)"
                />
              </SectionCard>

              {/* 条目列表(示例:展示数组渲染) */}
              {raw.items && raw.items.length > 0 && (
                <SectionCard title={`条目(${raw.items.length})`}>
                  <div className="flex flex-col gap-1">
                    {raw.items.map((item, i) => (
                      <div key={i} className="flex items-center gap-2 rounded-lg bg-bg px-3 py-2 text-xs">
                        <span className="font-mono text-text-3">{item.id ?? '-'}</span>
                        <span className="flex-1 text-text">{item.name ?? '-'}</span>
                        <span className="font-mono text-text-2">{item.value ?? '-'}</span>
                      </div>
                    ))}
                  </div>
                </SectionCard>
              )}

              {/* 警告 */}
              {warnings.length > 0 && (
                <SectionCard title={`警告(${warnings.length})`} accent="orange">
                  {warnings.map((w, i) => (
                    <div key={i} className="text-xs text-orange">• {w}</div>
                  ))}
                </SectionCard>
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
      <JsonDrawer data={raw} disabled={isProcessing} />
    </Layout>
  );
}
