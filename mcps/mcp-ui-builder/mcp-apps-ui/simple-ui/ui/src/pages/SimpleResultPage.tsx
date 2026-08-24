/**
 * 示例页：最简结果展示。
 *
 * 适合：工具执行快、无需进度推送、无需人工审核的场景。
 * 流程：等待工具入参 -> 等待工具结果 -> 展示结果。
 *
 * 同事改为自己的业务：替换 SimpleResult 类型 + 渲染逻辑即可。
 */

import { Layout } from '@/components/Layout';
import { LoadingScreen } from '@/components/LoadingScreen';
import { ErrorBanner } from '@/components/ErrorBanner';
import { PageHeader } from '@/components/PageHeader';
import { JsonDrawer } from '@/components/JsonDrawer';
import { useMcpApp, useNormalizedToolResult } from '@/core/mcpApp';
import { SectionCard, InfoCell } from '@/components/common';

/** 示例结果类型 -- 改成你的工具返回结构。 */
interface SimpleResult {
  status?: string;
  message?: string;
  items?: Array<{ id?: string; name?: string; value?: string }>;
  warnings?: string[];
}

export function SimpleResultPage() {
  const app = useMcpApp();
  const { finalResult: rawFinalResult, isError } = useNormalizedToolResult();
  const error = isError ? app.error : null;
  const result = (rawFinalResult ?? null) as SimpleResult | null;

  const isLoading = !result && !error;

  return (
    <Layout>
      <div className="flex h-full flex-col">
        <PageHeader icon="document" title="结果展示" subtitle="simple_tool" color="accent" />
        <div className="flex-1 overflow-hidden">
          {isLoading && <LoadingScreen message="等待工具执行" />}
          {error && !result && (
            <ErrorBanner error={error} onRetry={() => window.location.reload()} />
          )}
          {result && (
            <div className="flex flex-col gap-3 overflow-y-auto p-4">
              <SectionCard title="提取元信息">
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
      </div>
      <JsonDrawer data={result} disabled={isLoading} />
    </Layout>
  );
}
