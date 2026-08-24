/**
 * review_tool 的 mock 数据。
 *
 * 本 host 控制台只服务 review_tool 一个工具:进度推送 + 人工审核 + 提交。
 */

export interface UiEvent {
  review_pending?: boolean;
  review_id?: string;
  tool_name?: string;
  final_result?: Record<string, unknown>;
  [k: string]: unknown;
}

export interface ProgressStep {
  progress: number;
  total: number;
  message: string;
  uiEvent?: UiEvent;
}

export interface ReviewStage {
  reviewId: string;
  finalResult: Record<string, unknown>;
  result: Record<string, unknown>;
  resultIsError?: boolean;
}

export interface MockScenario {
  id: string;
  label: string;
  toolName: string;
  args: Record<string, unknown>;
  steps: ProgressStep[];
  review?: ReviewStage;
  /** skipReview=true 时,host 不发 review_pending,直接发 tool-result(review 工具不设)。 */
  skipReview?: boolean;
  /** 错误结果(设置此项时,跳过审核,直接发送错误 tool-result)。 */
  errorResult?: { content: Array<{ type: string; text: string }> };
}

export interface ToolGroup {
  name: string;
  label: string;
  page: string;
  scenarios: MockScenario[];
}

/** 通用结果数据。 */
function makeResult(): Record<string, unknown> {
  return {
    status: 'success',
    message: '示例提取结果',
    items: [
      { id: 'I-001', name: '条目 A', value: '100' },
      { id: 'I-002', name: '条目 B', value: '200' },
      { id: 'I-003', name: '条目 C', value: '300' },
    ],
    warnings: ['Mock warning: this is a mock result'],
  };
}

// --- review_tool: 完整审核流程 ---
function reviewScenario(): MockScenario {
  const result = {
    ...makeResult(),
    // review_tool 通过 read_image 读取的源图 data URL(真实 server 由 review_tool 推送)
    image_url:
      'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI4MDAiIGhlaWdodD0iNTAwIiB2aWV3Qm94PSIwIDAgODAwIDUwMCI+PHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iIzBiMjIzOSIvPjxyZWN0IHg9IjQwIiB5PSI0MCIgd2lkdGg9IjcyMCIgaGVpZ2h0PSI0MjAiIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzdmZDFmZiIgc3Ryb2tlLXdpZHRoPSIyIi8+PHRleHQgeD0iNDAwIiB5PSIyMzAiIGZpbGw9IiM3ZmQxZmYiIGZvbnQtc2l6ZT0iNDAiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtZmFtaWx5PSJtb25vc3BhY2UiPlNPVVJDRSBJTUFHRTwvdGV4dD48dGV4dCB4PSI0MDAiIHk9IjI4MCIgZmlsbD0iIzNlNmE4YyIgZm9udC1zaXplPSIyMCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1mYW1pbHk9Im1vbm9zcGFjZSI+cmV2aWV3X3Rvb2wgLSByZWFkX2ltYWdlIGRlbW88L3RleHQ+PC9zdmc+',
  };
  return {
    id: 'review-normal',
    label: '正常:提取 + 审核',
    toolName: 'review_tool',
    args: { input_path: 'example://data' },
    steps: [
      { progress: 0, total: 3, message: '启动工具' },
      { progress: 1, total: 3, message: '数据解析完成', uiEvent: { event_type: 'parsed', item_count: 3 } },
      { progress: 2, total: 3, message: '提取完成' },
    ],
    review: {
      reviewId: 'review-review-001',
      finalResult: result,
      result,
    },
  };
}

function reviewErrorScenario(): MockScenario {
  return {
    id: 'review-error',
    label: '错误:提取中途失败',
    toolName: 'review_tool',
    args: { input_path: 'example://data' },
    steps: [
      { progress: 0, total: 3, message: '启动工具' },
    ],
    errorResult: {
      content: [{ type: 'text', text: 'Mock error: 提取中途失败，无法继续' }],
    },
  };
}

export const MOCK_TOOLS: ToolGroup[] = [
  {
    name: 'review_tool',
    label: '审核流程',
    page: 'ReviewPage',
    scenarios: [reviewScenario(), reviewErrorScenario()],
  },
];

export function findToolGroup(toolName: string): ToolGroup | undefined {
  return MOCK_TOOLS.find((t) => t.name === toolName);
}
