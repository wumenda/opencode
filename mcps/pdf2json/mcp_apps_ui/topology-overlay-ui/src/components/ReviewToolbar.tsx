/**
 * 审核工具栏：通过/驳回按钮 + 驳回原因输入。
 *
 * 所有审核页面共用。状态由父组件控制（disabled / submitting / submitted）。
 */

import { useState } from 'react';

/** 驳回快捷原因（点击追加到 textarea，分号分隔）。 */
const REJECT_QUICK_REASONS = [
  '设备漏识别',
  '拓扑连接错误',
  '参数提取错误',
  '位号不一致',
  '边界节点缺失',
  '内件段数据异常',
];

interface ReviewToolbarProps {
  /** 是否可提交（waiting_review 状态时为 true）。 */
  canSubmit: boolean;
  /** 是否提交中。 */
  submitting: boolean;
  /** 已提交的结果消息（成功或失败）。 */
  resultMessage?: { type: 'success' | 'error'; text: string } | null;
  /** 提交通过。 */
  onApprove: () => void;
  /** 提交驳回（带原因）。 */
  onReject: (reason: string) => void;
  /** 状态提示文案（覆盖默认逻辑）。 */
  statusHint?: string;
  /** 是否有未保存编辑。 */
  dirty?: boolean;
  /** 重置编辑回调。 */
  onReset?: () => void;
}

export function ReviewToolbar({
  canSubmit,
  submitting,
  resultMessage,
  onApprove,
  onReject,
  statusHint,
  dirty,
  onReset,
}: ReviewToolbarProps) {
  const [rejectMode, setRejectMode] = useState(false);
  const [reason, setReason] = useState('');

  const handleReject = () => {
    if (!reason.trim()) {
      return;
    }
    onReject(reason.trim());
    setReason('');
    setRejectMode(false);
  };

  const hint =
    statusHint ?? (canSubmit ? '审核数据已就绪，请审核后提交' : '提取进行中…');

  return (
    <div className="border-t border-border bg-bg-2/60 px-4 py-3 backdrop-blur">
      {resultMessage && (
        <div
          className={`mb-2 rounded-md border px-3 py-2 text-xs ${
            resultMessage.type === 'success'
              ? 'border-green/30 bg-green/5 text-green'
              : 'border-red/30 bg-red/5 text-red'
          }`}
        >
          {resultMessage.text}
        </div>
      )}
      {rejectMode ? (
        <div className="flex flex-col gap-2">
          {/* 快捷原因 chips */}
          <div className="flex flex-wrap gap-1.5">
            {REJECT_QUICK_REASONS.map((r) => (
              <button
                key={r}
                type="button"
                className="rounded-full border border-border bg-bg-3 px-2.5 py-1 text-[11px] text-text-2 hover:border-accent hover:text-accent"
                onClick={() => setReason((prev) => (prev ? `${prev}；${r}` : r))}
              >
                {r}
              </button>
            ))}
          </div>
          <textarea
            className="min-h-[64px] w-full resize-y rounded-md border border-border bg-bg px-3 py-2 text-sm text-text outline-none focus:border-accent"
            placeholder="请输入驳回原因（必填，可点击上方快捷原因补充）"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                e.preventDefault();
                handleReject();
              }
            }}
            autoFocus
          />
          <div className="flex items-center justify-end gap-2">
            <span className="mr-auto text-[10px] text-text-3">
              {reason.length} 字{reason.trim() ? '' : '（必填）'}
            </span>
            <button
              className="rounded-md border border-border bg-bg-3 px-3 py-1.5 text-xs text-text-2 hover:border-text-3 disabled:opacity-50"
              onClick={() => {
                setRejectMode(false);
                setReason('');
              }}
              disabled={submitting}
            >
              取消
            </button>
            <button
              className="rounded-md bg-red px-3 py-1.5 text-xs font-semibold text-white hover:bg-red/90 disabled:opacity-50"
              onClick={handleReject}
              disabled={submitting || !reason.trim()}
            >
              {submitting ? '提交中…' : '确认驳回 (Ctrl+Enter)'}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-end gap-2">
          <span className="mr-auto flex items-center gap-1.5 text-xs text-text-3">
            {hint.startsWith('提取进行中') && (
              <svg className="h-3.5 w-3.5 animate-spin text-accent" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
            )}
            {hint}
          </span>
          {dirty && canSubmit && onReset && (
            <button
              className="rounded-md border border-border bg-bg-3 px-3 py-1.5 text-xs text-text-2 hover:border-text-3"
              onClick={() => {
                if (confirm('确认放弃当前编辑？')) onReset();
              }}
              disabled={submitting}
            >
              重置编辑
            </button>
          )}
          {dirty && canSubmit && (
            <span className="rounded bg-orange/10 px-1.5 py-1 text-[10px] text-orange">
              未保存
            </span>
          )}
          <button
            className="rounded-md border border-red/40 bg-red/10 px-4 py-1.5 text-xs font-semibold text-red hover:bg-red/20 disabled:opacity-40"
            onClick={() => setRejectMode(true)}
            disabled={!canSubmit || submitting}
          >
            驳回
          </button>
          <button
            className="rounded-md bg-green px-4 py-1.5 text-xs font-semibold text-white hover:bg-green/90 disabled:opacity-40"
            onClick={onApprove}
            disabled={!canSubmit || submitting}
          >
            {submitting ? '提交中…' : '通过审核'}
          </button>
        </div>
      )}
    </div>
  );
}
