/**
 * 事件时间线：展示 session 提取过程的所有事件。
 */

import type { ReactNode } from 'react';
import type { SessionEvent } from '@/core/types';

const TERMINAL_EVENTS = new Set([
  'completed',
  'error',
  'cancelled',
  'review_approved',
  'review_rejected',
  'stream_end',
]);

interface EventTimelineProps {
  events: SessionEvent[];
  /** 自定义渲染。 */
  renderItem?: (ev: SessionEvent, idx: number) => ReactNode;
}

export function EventTimeline({ events, renderItem }: EventTimelineProps) {
  if (events.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 py-12 text-text-3">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="opacity-40">
          <circle cx="12" cy="12" r="10" />
          <path d="M12 6v6l4 2" />
        </svg>
        <span className="text-xs">暂无事件</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 py-1">
      {events.map((ev, idx) => {
        const isTerminal = TERMINAL_EVENTS.has(ev.event);
        const isError = ev.event === 'error';
        const isWaiting = ev.event === 'waiting_for_review';
        const isSuccess = ev.event === 'completed' || ev.event === 'review_approved';

        const iconBg = isError
          ? 'bg-red text-white'
          : isTerminal
            ? 'bg-accent text-white'
            : isWaiting
              ? 'bg-orange text-white'
              : isSuccess
                ? 'bg-green text-white'
                : 'bg-bg-3 text-text-3';

        return (
          <div
            key={idx}
            className={`flex gap-3 rounded-md border p-2.5 ${
              isError
                ? 'border-red/30 bg-red/5'
                : isTerminal
                  ? 'border-accent/30 bg-accent/5'
                  : 'border-border bg-bg-2'
            }`}
          >
            <div
              className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold ${iconBg}`}
            >
              {idx + 1}
            </div>
            <div className="min-w-0 flex-1">
              <div className="font-mono text-[13px] font-semibold text-text">
                {ev.event}
              </div>
              {typeof ev.data?.message === 'string' && (
                <div className="mt-0.5 text-xs text-text-2">{ev.data.message}</div>
              )}
              {renderItem && renderItem(ev, idx)}
              {ev.timestamp && (
                <div className="mt-1 break-all font-mono text-[10px] text-text-3">
                  {new Date(ev.timestamp * 1000).toLocaleTimeString()}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}