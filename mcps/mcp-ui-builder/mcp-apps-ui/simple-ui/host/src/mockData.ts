/**
 * simple_tool 的 mock 数据。
 *
 * 本 host 控制台只服务 simple_tool 一个工具:无进度推送,直接返回结果。
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
  /** skipReview=true 时,host 不发 review_pending,直接发 tool-result(simple 工具用)。 */
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

// --- simple_tool: 无进度,直接返回结果 ---
function simpleScenario(): MockScenario {
  return {
    id: 'simple-normal',
    label: '正常:直接返回结果',
    toolName: 'simple_tool',
    args: { input_path: 'example://data' },
    steps: [],
    review: {
      reviewId: 'review-simple-001',
      finalResult: makeResult(),
      result: makeResult(),
    },
    skipReview: true,
  };
}

export const MOCK_TOOLS: ToolGroup[] = [
  {
    name: 'simple_tool',
    label: '简单结果',
    page: 'SimpleResultPage',
    scenarios: [simpleScenario()],
  },
];

export function findToolGroup(toolName: string): ToolGroup | undefined {
  return MOCK_TOOLS.find((t) => t.name === toolName);
}
