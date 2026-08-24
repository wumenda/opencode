/**
 * 示例页：进度 + 结果展示。
 *
 * 适合：工具执行耗时较长、需要展示进度、但无需人工审核的场景。
 * 流程：等待工具入参 -> 展示提取进度 -> 展示结果。
 *
 * 同事改为自己的业务：替换 ProgressResult 类型 + 渲染逻辑即可。
 */

import { useMemo } from 'react';
import { Layout } from '@/components/Layout';
import { PageHeader } from '@/components/PageHeader';
import { ProgressBanner } from '@/components/ProgressBanner';
import { ErrorBanner } from '@/components/ErrorBanner';
import { TaskProgress } from '@/components/TaskProgress';
import { JsonDrawer } from '@/components/JsonDrawer';
import { useMcpApp, useNormalizedToolResult } from '@/core/mcpApp';
import { SectionCard, InfoCell } from '@/components/common';

/** 示例结果类型 -- 改成你的工具返回结构。 */
interface ProgressResult {
  status?: string;
  message?: string;
  items?: Array<{ id?: string; name?: string; value?: string }>;
  warnings?: string[];
}

export function ProgressPage() {
  const app = useMcpApp();
  const { finalResult: rawFinalResult, isError } = useNormalizedToolResult();
  const error = isError ? app.error : null;
  const result = (rawFinalResult ?? null) as ProgressResult | null;

  const isDone = !!result;
  const isProcessing = !isDone && !error;

  const statusHint = useMemo(() => {
    if (error) return '执行失败';
    if (isDone) return '执行完成';
    if (isProcessing) return '执行中…';
    return '等待中…';
  }, [error, isDone, isProcessing]);

  return (
    <Layout>
      <div className="flex h-full flex-col">
        <PageHeader icon="signal" title="进度展示" subtitle="progress_tool" color="accent" />
        {isDone && <ProgressBanner />}
        <div className="flex-1 overflow-hidden">
          {isProcessing && (
            <div className="flex h-full items-center justify-center p-4">
              <div className="h-full w-full max-w-2xl rounded-lg border border-border bg-bg-2/40 overflow-hidden">
                <TaskProgress />
              </div>
            </div>
          )}
          {error && !result && (
            <ErrorBanner error={error} onRetry={() => window.location.reload()} />
          )}
          {result && (
            <div className="flex flex-col gap-3 overflow-y-auto p-4">
              <SectionCard title="执行结果">
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                  <InfoCell label="状态" value={result.status || '-'} highlight={result.status === 'success' ? 'green' : 'orange'} />
                  <InfoCell label="消息" value={result.message ?? '-'} />
                  <InfoCell label="条目数" value={result.items?.length ?? 0} />
                </div>
              </SectionCard>

              {result.items && result.items.length > 0 && (
                <SectionCard title={`条目(${result.items.length})`}>
                  <div className="flex flex-col gap-1">
                    {result.items.map((item, i) => (
                      <div key={i} className="flex items-center gap-2 rounded-lg bg-bg px-3 py-2 text-xs">
                        <span className="font-mono text-text-3">{item.id ?? '-'}</span>
                        <span className="flex-1 text-text">{item.name ?? '-'}</span>
                        <span className="font-mono text-text-2">{item.value ?? '-'}</span>
                      </div>
                    ))}
                  </div>
                </SectionCard>
              )}

              {result.warnings && result.warnings.length > 0 && (
                <SectionCard title={`警告(${result.warnings.length})`} accent="orange">
                  {result.warnings.map((w, i) => (
                    <div key={i} className="text-xs text-orange">• {w}</div>
                  ))}
                </SectionCard>
              )}
            </div>
          )}
        </div>
        {isDone && (
          <div className="bg-bg-2/80 backdrop-blur-xl border-t border-border px-4 py-3 text-xs text-text-3">
            {statusHint}
          </div>
        )}
      </div>
      <JsonDrawer data={result} disabled={isProcessing} />
    </Layout>
  );
}
