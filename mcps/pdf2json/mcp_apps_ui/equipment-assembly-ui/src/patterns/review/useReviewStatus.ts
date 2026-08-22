/**
 * 审核状态派生 -- 从 MCP App store 派生 SessionStatus。
 */
import { useMcpApp } from '@/core/mcpApp';
import type { SessionStatus } from '@/core/types';

/** 本项目固定子状态：提取中显示为设备提取态。 */
const EXTRACTING_STATUS: SessionStatus = 'extracting_equipment';

/** MCP App 状态 -> SessionStatus 映射。 */
function statusFromApp(appStatus: string): SessionStatus {
  switch (appStatus) {
    case 'initializing':
    case 'ready':
      return 'pending';
    case 'processing':
      return EXTRACTING_STATUS;
    case 'result_ready':
      return 'waiting_review';
    case 'error':
      return 'error';
    default:
      return 'pending';
  }
}

/**
 * 派生当前审核状态。
 * @returns SessionStatus;null 表示初始化中(app.status === 'initializing')
 */
export function useReviewStatus(): SessionStatus | null {
  const app = useMcpApp();

  if (app.status === 'initializing') return null;

  // 终态优先于 review_pending：审核工具提交后 host 会回推 tool-result
  // （status → 'result_ready'/'error'），此时 progress.uiEvent.review_pending 仍残留为
  // true，若不优先处理会把状态卡死在 waiting_review。
  if (app.status === 'error') return 'error';
  if (app.status === 'result_ready') return 'completed';

  // 提取完成、工具进入审核阻塞等待（app.status 仍为 'processing'）时才返回 waiting_review
  if (app.progress?.uiEvent?.review_pending) return 'waiting_review';

  return statusFromApp(app.status);
}
