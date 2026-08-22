/**
 * 进度横幅：显示当前会话状态 + 提取事件流。
 *
 * 用于审核页面顶部，让用户看到"正在提取 / 等待审核 / 已完成"。
 */

import { useMcpApp } from '@/core/mcpApp';
import { useReviewStatus } from '@/patterns/review';
import type { SessionStatus } from '@/core/types';

const STATUS_LABEL: Record<SessionStatus, string> = {
  pending: '排队中',
  parsing_pdf: '解析 PDF',
  extracting: '回流分析',
  extracting_boundary: '提取边界节点',
  extracting_equipment: '提取设备节点',
  extracting_topology: '提取拓扑',
  waiting_review: '等待人工审核',
  confirming: '审核确认中',
  completed: '已完成',
  error: '提取失败',
};

const STATUS_COLOR: Record<SessionStatus, string> = {
  pending: 'bg-bg-3 text-text-3',
  parsing_pdf: 'bg-accent/10 text-accent border-accent/30',
  extracting: 'bg-accent/10 text-accent border-accent/30',
  extracting_boundary: 'bg-accent/10 text-accent border-accent/30',
  extracting_equipment: 'bg-accent/10 text-accent border-accent/30',
  extracting_topology: 'bg-accent/10 text-accent border-accent/30',
  waiting_review: 'bg-orange/10 text-orange border-orange/30',
  confirming: 'bg-purple/10 text-purple border-purple/30',
  completed: 'bg-green/10 text-green border-green/30',
  error: 'bg-red/10 text-red border-red/30',
};

interface ProgressBannerProps {}

export function ProgressBanner({}: ProgressBannerProps) {
  const app = useMcpApp();
  const status = useReviewStatus();
  const events = app.progressEvents;

  if (!status) return null;

  const lastEv = events.filter((e) => e.event !== 'stage_update')[events.length - 1];
  const isTerminal = status === 'completed' || status === 'error';

  return (
    <div
      className={`border-b border-border px-4 py-2 ${
        isTerminal ? 'bg-bg-2/40' : 'bg-bg-2/60'
      }`}
    >
      <div className="flex items-center gap-3">
        <span
          className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-semibold ${STATUS_COLOR[status]}`}
        >
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              isTerminal ? 'bg-current' : 'bg-current animate-pulse'
            }`}
          />
          {STATUS_LABEL[status]}
        </span>
        <div className="flex-1" />
        {lastEv && (
          <span className="truncate text-xs text-text-3" title={lastEv.event}>
            <span className="font-mono text-text-2">{lastEv.event}</span>
            {typeof lastEv.data?.message === 'string' && (
              <span className="ml-2 text-text-3">{lastEv.data.message}</span>
            )}
          </span>
        )}
      </div>
      {status === 'error' && app.error && (
        <pre className="mt-2 max-h-24 overflow-auto rounded bg-red/5 p-2 text-[11px] text-red">
          {app.error}
        </pre>
      )}
    </div>
  );
}