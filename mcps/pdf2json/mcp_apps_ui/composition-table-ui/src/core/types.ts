/**
 * 公共类型定义（core 层）。
 *
 * 仅包含跨模块共享的通用类型。业务专属类型定义在各页面文件中。
 */

/** 会话状态：状态机流转。 */
export type SessionStatus =
  | 'pending'
  | 'parsing_pdf'
  | 'extracting'
  | 'extracting_boundary'
  | 'extracting_equipment'
  | 'extracting_topology'
  | 'waiting_review'
  | 'confirming'
  | 'completed'
  | 'error';

/** 单条事件。 */
export interface SessionEvent {
  event: string;
  data: Record<string, unknown>;
  timestamp: number;
}

/** 提交审核请求体。 */
export interface SubmitReviewRequest {
  approved: boolean;
  edited_data?: unknown;
  reason?: string;
}

/** 提交审核响应。 */
export interface SubmitReviewResponse {
  session_id: string;
  review_status: 'approved' | 'rejected';
  result_path: string;
  summary: Record<string, unknown>;
  message: string;
  reason?: string;
}
