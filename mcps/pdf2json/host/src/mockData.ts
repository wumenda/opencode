/**
 * 所有审核工具（及 progress_probe）的 mock 数据与场景。
 *
 * 结构对照 mcp_server/mock_server.py，保证发出的消息与真实 server 的
 * progress / _send_progress_with_data / tool-result 载荷一致，UI 才能按
 * 真实数据流渲染。每个工具可含多个场景（正常 / 空 / 失败等）。
 */

import resultJson from '../../data/mock/result.json';

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------

/** progress 通知中的 uiEvent 扩展字段（与 mcpApp.ts ProgressNotification 对齐）。 */
export interface UiEvent {
  partial_page_graphs?: Array<Record<string, unknown>>;
  image_paths?: string[];
  image_infos?: Array<{ path?: string; width?: number; height?: number }>;
  cross_page_edges?: Array<Record<string, unknown>>;
  global_graph?: Record<string, unknown>;
  // ---- A 组实时渲染 partial 数据（5-UI-realtime-rendering） ----
  partial_plant_units?: Array<Record<string, unknown>>;
  partial_text_destinations?: Array<Record<string, unknown>>;
  partial_edges?: Array<Record<string, unknown>>;
  partial_extracted?: { components?: unknown[]; streams?: unknown[] };
  partial_aggregated?: Record<string, unknown>;
  partial_matched_sections?: Array<Record<string, unknown>>;
  partial_pdf_path?: string;
  partial_total_pages?: number;
  review_pending?: boolean;
  review_id?: string;
  tool_name?: string;
  final_result?: Record<string, unknown>;
  validation?: Record<string, unknown>;
  event_type?: string;
  matched_section_count?: number;
  total_pages?: number;
  text_length?: number;
  success?: boolean;
  has_data?: boolean;
  drawing_type?: string;
  confidence?: number;
  unit_count?: number;
  text_destination_count?: number;
  edges_count?: number;
  topology_source?: string;
  equipment_type?: string;
  towers?: number;
  reactors?: number;
  page_index?: number;
  has_table?: boolean;
  component_count?: number;
  stream_count?: number;
  probe_seq?: number;
  server_ts?: number;
  probe_count?: number;
  [k: string]: unknown;
}

/** 单条 progress 通知。 */
export interface ProgressStep {
  progress: number;
  total: number;
  message: string;
  uiEvent?: UiEvent;
}

/** 审核阶段：review_pending 通知 + 最终 tool-result。 */
export interface ReviewStage {
  reviewId: string;
  /** 渲染审核编辑器用的最终结果（await_user_review 阻塞期间推送）。 */
  finalResult: Record<string, unknown>;
  /** tool-result 的 structuredContent（提交审核后由 host 发出）。 */
  result: Record<string, unknown>;
  /** 是否以错误结果返回（驳回/超时等场景）。 */
  resultIsError?: boolean;
  resultErrorText?: string;
}

/** 一个可回放的 mock 场景。 */
export interface MockScenario {
  id: string;
  label: string;
  /** 发送给 tool-input 的 toolName。 */
  toolName: string;
  /** 工具入参。 */
  args: Record<string, unknown>;
  /** 提取阶段 progress 序列。 */
  steps: ProgressStep[];
  /** 审核阶段（多数审核工具都有；progress_probe 等无）。 */
  review?: ReviewStage;
  /** 无审核、直接回发的最终结果（失败/异常场景；与 review 互斥）。 */
  direct?: {
    /** tool-result 的 structuredContent。 */
    result?: Record<string, unknown>;
    /** 是否以错误结果返回（isError=true，无 structuredContent）。 */
    isError?: boolean;
    /** isError=true 时携带的具体错误文本。 */
    errorText?: string;
  };
}

// ---------------------------------------------------------------------------
// 真实 global_graph（从 data/mock/result.json 加载，用于 pfd_topology 场景）
// ---------------------------------------------------------------------------

const realGlobalGraph = resultJson.global_graph as Record<string, unknown>;

/** 从 global_graph 按 page_index 过滤出单页拓扑（与 Python _build_page_topology_from_global 对齐）。 */
function pageTopologyFromGlobal(
  globalGraph: Record<string, unknown>,
  pageIndex: number,
  includeBoundary = true,
  includeEdges = true,
): Record<string, unknown> {
  const allNodes = (globalGraph.nodes as Array<Record<string, unknown>>) ?? [];
  const pageNodes = allNodes.filter((n) => n.page_index === pageIndex);
  const equipmentNodes = pageNodes.filter((n) => n.node_type !== 'boundary');
  const boundaryNodes = includeBoundary
    ? pageNodes.filter((n) => n.node_type === 'boundary')
    : [];

  const allEdges = (globalGraph.edges as Array<Record<string, unknown>>) ?? [];
  const edges = includeEdges
    ? allEdges.filter((e) => e.page_index === pageIndex)
    : [];

  return { equipment_nodes: equipmentNodes, boundary_nodes: boundaryNodes, edges };
}

/** 单页 pfd_drawing。 */
function pageDrawing(
  idx: number,
  imagePath: string,
  imageInfo: { path?: string; width?: number; height?: number },
  topo: Record<string, unknown>,
  pageCount: number,
): Record<string, unknown> {
  return {
    page_index: idx,
    page_label: `第 ${idx + 1} 页`,
    pfd_drawing: {
      page_index: idx,
      image_path: imagePath,
      image_info: imageInfo,
      drawing_info: { drawing_type: 'PFD', page_count: pageCount },
      topology: topo,
    },
  };
}

const validationResult = {
  status: 'passed_with_warnings',
  issues: [
    { severity: 'warning', message: 'Mock warning: node E-101 has no upstream connection' },
    { severity: 'info', message: 'Mock info: 2 boundary nodes have ambiguous direction' },
  ],
  needs_human_review: 1,
};

// ---------------------------------------------------------------------------
// 工具 1: pfd_topology（多页 PFD 拓扑，MultiPageTopologyPage）
// ---------------------------------------------------------------------------

function pfdTopologyScenario(): MockScenario {
  // 从 realGlobalGraph 计算页数（取 nodes 中最大 page_index + 1）
  const graphNodes = (realGlobalGraph.nodes as Array<Record<string, unknown>>) ?? [];
  const pageIndices = graphNodes
    .map((n) => n.page_index as number)
    .filter((p) => p !== null && p !== undefined);
  const pageCount = pageIndices.length > 0 ? Math.max(...pageIndices) + 1 : 1;

  const imagePaths = Array.from({ length: pageCount }, (_, i) => `mock://pfd/page-${i + 1}`);
  // 与 pdfRenderer.ts 渲染的 PDF 页面尺寸一致（scale=1 时的 viewport 尺寸）
  const imageInfos = imagePaths.map((p) => ({ path: p, width: 3370, height: 2384 }));

  const nodesOnly = imagePaths.map((p, i) =>
    pageDrawing(i, p, imageInfos[i], pageTopologyFromGlobal(realGlobalGraph, i, false, false), pageCount),
  );
  const withBoundary = imagePaths.map((p, i) =>
    pageDrawing(i, p, imageInfos[i], pageTopologyFromGlobal(realGlobalGraph, i, true, false), pageCount),
  );
  const full = imagePaths.map((p, i) =>
    pageDrawing(i, p, imageInfos[i], pageTopologyFromGlobal(realGlobalGraph, i, true, true), pageCount),
  );
  const cpe = (realGlobalGraph.cross_page_edges as Array<Record<string, unknown>>) ?? [];
  const gg = realGlobalGraph;

  const totalEq = (nodesOnly as Array<Record<string, unknown>>).reduce(
    (sum, p) => sum + (((p.pfd_drawing as Record<string, unknown>).topology as Record<string, unknown>).equipment_nodes as unknown[]).length,
    0,
  );
  const totalBn = (withBoundary as Array<Record<string, unknown>>).reduce(
    (sum, p) => sum + (((p.pfd_drawing as Record<string, unknown>).topology as Record<string, unknown>).boundary_nodes as unknown[]).length,
    0,
  );
  const totalEdges = (full as Array<Record<string, unknown>>).reduce(
    (sum, p) => sum + (((p.pfd_drawing as Record<string, unknown>).topology as Record<string, unknown>).edges as unknown[]).length,
    0,
  );

  const result: Record<string, unknown> = {
    version: '1.0.0',
    workflow: 'pfd_topology',
    status: 'success',
    page_graphs: full,
    global_graph: gg,
    image_path: imagePaths[0],
    image_paths: imagePaths,
    image_infos: imageInfos,
    warnings: ['Mock warning: this is a mock result, not real VLM extraction'],
  };

  return {
    id: 'pfd_topology-normal',
    label: '正常：多页拓扑 + 跨页边',
    toolName: 'pfd_topology',
    args: {
      pdf_path: 'data/装置级/PFD.pdf',
      start_page: 0,
      end_page: null,
      dpi: 300,
      max_workers: 2,
    },
    steps: [
      { progress: 0, total: 5, message: '启动 PFD 拓扑提取' },
      {
        progress: 0.5, total: 5,
        message: `PDF 解析完成，共 ${pageCount} 页`,
        uiEvent: { image_paths: imagePaths, image_infos: imageInfos },
      },
      {
        progress: 1, total: 5,
        message: `图纸已加载到画布，设备节点提取完成（共 ${totalEq} 个设备）`,
        uiEvent: { image_paths: imagePaths, image_infos: imageInfos, partial_page_graphs: nodesOnly },
      },
      {
        progress: 1.5, total: 5,
        message: `边界节点提取完成（共 ${totalBn} 个边界节点）`,
        uiEvent: { partial_page_graphs: withBoundary },
      },
      {
        progress: 2, total: 5,
        message: `拓扑边提取完成（页内 ${totalEdges} 条，跨页 ${cpe.length} 条）`,
        uiEvent: {
          image_paths: imagePaths,
          image_infos: imageInfos,
          partial_page_graphs: full,
          cross_page_edges: cpe,
        },
      },
      {
        progress: 2.5, total: 5,
        message: '跨页拼接开始',
        uiEvent: { cross_page_edges: cpe },
      },
      {
        progress: 3, total: 5,
        message: `全局图构建完成（${(gg.nodes as unknown[]).length} 节点，${cpe.length} 条跨页边）`,
        uiEvent: { global_graph: gg },
      },
      {
        progress: 4, total: 5,
        message: '验证完成',
        uiEvent: { validation: validationResult },
      },
      { progress: 5, total: 5, message: '分析完成' },
    ],
    review: {
      reviewId: 'review-pfd-topology-001',
      finalResult: result,
      result,
    },
  };
}

// ---------------------------------------------------------------------------
// 工具 2: process_package（工艺包章节信息，GenericReviewPage）
// ---------------------------------------------------------------------------

function processPackageScenario(): MockScenario {
  const mockExtracted: Record<string, unknown> = {
    process_description: 'Mock 工序说明：原料经预热后进入反应器，在催化剂作用下发生反应，产物经分离塔分离。',
    reactions: [
      {
        equation: 'C2H4 + H2O -> C2H5OH',
        type: 'hydration',
        catalyst: 'H3PO4/SiO2',
        conditions: { temperature: '300C', pressure: '7MPa' },
      },
    ],
    operating_conditions: [{ unit: 'R-101', temperature: '300C', pressure: '7MPa' }],
  };

  const result: Record<string, unknown> = {
    status: 'partial',
    workflow: 'process_package',
    pdf_path: 'data/工艺包/工艺包.pdf',
    locator: 'chapter_index=1',
    total_pages: 10,
    matched_section_count: 1,
    matched_sections: [
      {
        title: 'Chapter 1',
        level: 1,
        start_page: 1,
        end_page: 5,
        page_count: 5,
        page_numbers: [1, 2, 3, 4, 5],
      },
    ],
    all_matched_page_numbers: [1, 2, 3, 4, 5],
    filtered_text_length: 5000,
    expert_outputs: { process_package: mockExtracted },
    warnings: ['Mock warning: this is a mock result, not real extraction'],
  };

  return {
    id: 'process_package-normal',
    label: '正常：章节抽取 + 专家输出',
    toolName: 'process_package',
    args: { pdf_path: 'data/工艺包/工艺包.pdf', chapter_index: 1 },
    steps: [
      { progress: 0, total: 3, message: 'PDF 已接收，解析 PDF 中…', uiEvent: { event_type: 'pdf_received', partial_pdf_path: 'data/工艺包/工艺包.pdf' } },
      {
        progress: 1, total: 3,
        message: 'Chapter extraction completed',
        uiEvent: {
          event_type: 'chapter_extracted', matched_section_count: 1, total_pages: 10, text_length: 5000,
          partial_matched_sections: [
            { title: 'Chapter 1', level: 1, start_page: 1, end_page: 5, page_count: 5, page_numbers: [1, 2, 3, 4, 5] },
          ],
          partial_pdf_path: 'data/工艺包/工艺包.pdf',
          partial_total_pages: 10,
        },
      },
      { progress: 1.5, total: 3, message: 'Running ProcessPackageExpert' },
      {
        progress: 2, total: 3,
        message: 'Process package expert completed',
        uiEvent: { event_type: 'expert_complete', success: true, has_data: true },
      },
      { progress: 3, total: 3, message: 'Process package extraction completed' },
    ],
    review: {
      reviewId: 'review-process-package-001',
      finalResult: result,
      result,
    },
  };
}

// ---------------------------------------------------------------------------
// 工具 3: plant_unit_topology（整厂装置拓扑，PlantUnitPage）
// ---------------------------------------------------------------------------

function plantUnitScenario(): MockScenario {
  // 与 src/core/models/plant/plant_unit.py 的 PlantUnitNode 对齐：
  // id / node_type / name / unit_name / position(像素中心) / feeds / products。
  const plantUnits = [
    {
      id: 'U-101', node_type: 'plant_unit', name: '常减压装置', unit_name: '常减压装置',
      feeds: ['原油'], products: ['石脑油', '柴油'], position: [280, 460],
    },
    {
      id: 'U-201', node_type: 'plant_unit', name: '催化裂化装置', unit_name: '催化裂化装置',
      feeds: ['蜡油'], products: ['汽油', '液化气'], position: [800, 240],
    },
    {
      id: 'U-301', node_type: 'plant_unit', name: '加氢精制装置', unit_name: '加氢精制装置',
      feeds: ['柴油'], products: ['精制柴油'], position: [800, 650],
    },
  ];
  const textDestinations = [
    { id: 'T-1', node_type: 'text_destination', name: '原料油', position: [120, 160] },
    { id: 'T-2', node_type: 'text_destination', name: '石脑油', position: [1060, 130] },
    { id: 'T-3', node_type: 'text_destination', name: '柴油', position: [1060, 400] },
    { id: 'T-4', node_type: 'text_destination', name: '汽油', position: [1060, 620] },
    { id: 'T-5', node_type: 'text_destination', name: '液化气', position: [1060, 810] },
  ];
  const edges = [
    { source_node_id: 'U-101', target_node_id: 'U-201', material_name: '蜡油', method: 'vlm' },
    { source_node_id: 'U-101', target_node_id: 'U-301', material_name: '柴油', method: 'vlm' },
  ];

  const result: Record<string, unknown> = {
    version: '1.0.0',
    workflow: 'plant_unit_topology',
    drawing_type: 'plant_unit_general',
    status: 'success',
    plant_unit_drawing: {
      drawing_id: 'plant_unit_drawing_1',
      drawing_name: 'Mock 全厂装置图',
      canvas_width: 1200,
      canvas_height: 900,
      nodes: [...plantUnits, ...textDestinations],
      edges,
      metadata: {
        unit_warnings: [],
        topology_warnings: [],
        topology_source: 'vlm',
      },
    },
    expert_outputs: {
      plant_unit_drawing_type: { drawing_type: 'plant_unit_general', confidence: 0.95, evidence: 'Mock: 管线连接清晰可见' },
      plant_unit: { plant_unit: plantUnits, text_destinations: textDestinations },
      plant_unit_topology: { edges, topology_source: 'vlm' },
    },
    drawing_type_detection: { drawing_type: 'plant_unit_general', evidence: 'Mock: 管线连接清晰可见', confidence: 0.95 },
    warnings: ['Mock warning: this is a mock result, not real extraction'],
    errors: [],
    image_path: 'mock://plant-unit/page-1',
  };

  return {
    id: 'plant_unit-normal',
    label: '正常：装置节点 + 拓扑',
    toolName: 'plant_unit_topology',
    args: { pdf_path: 'data/装置级/全厂.PDF', page_index: 0, dpi: 300 },
    steps: [
      {
        progress: 0, total: 4,
        message: 'PDF 解析完成，已生成图片',
        uiEvent: {
          event_type: 'images_loaded',
          image_paths: ['mock://plant-unit/page-1'],
          image_infos: [{ path: 'mock://plant-unit/page-1', width: 1200, height: 900 }],
        },
      },
      { progress: 0, total: 4, message: 'Starting plant-unit topology extraction' },
      { progress: 0.5, total: 4, message: 'Classifying drawing type' },
      {
        progress: 1, total: 4,
        message: 'Drawing type classified: plant_unit_general',
        uiEvent: { event_type: 'drawing_type_classified', drawing_type: 'plant_unit_general', confidence: 0.95 },
      },
      { progress: 1.5, total: 4, message: 'Extracting plant unit nodes' },
      {
        progress: 2, total: 4,
        message: '3 plant units extracted',
        uiEvent: {
          event_type: 'plant_units_extracted', unit_count: 3, text_destination_count: 5,
          partial_plant_units: plantUnits,
          partial_text_destinations: textDestinations,
        },
      },
      { progress: 2.5, total: 4, message: 'Extracting topology' },
      {
        progress: 3, total: 4,
        message: 'Topology extracted',
        uiEvent: { event_type: 'topology_extracted', edges_count: 2, topology_source: 'vlm', partial_edges: edges },
      },
      { progress: 4, total: 4, message: 'Plant-unit topology extraction completed' },
    ],
    review: {
      reviewId: 'review-plant-unit-001',
      finalResult: result,
      result,
    },
  };
}

// ---------------------------------------------------------------------------
// 工具 4: equipment_assembly（设备装配图，EquipmentAssemblyPage）
// ---------------------------------------------------------------------------

function equipmentAssemblyScenario(): MockScenario {
  const mockColumn: Record<string, unknown> = {
    column_id: 'T-101',
    column_type: 'tray',
    diameter: 2000,
    height: 30000,
    tray_count: 40,
    tray_type: 'sieve',
    tray_spacing: 600,
    nozzles: [
      { id: 'N1', label: 'Feed Inlet', diameter: 150, elevation: 15000 },
      { id: 'N2', label: 'Top Outlet', diameter: 200, elevation: 29500 },
      { id: 'N3', label: 'Bottom Outlet', diameter: 150, elevation: 500 },
    ],
    operating_conditions: { temperature_top: 120, temperature_bottom: 180, pressure: 0.5 },
  };

  const result: Record<string, unknown> = {
    status: 'partial',
    workflow: 'equipment_assembly',
    equipment_id: 'T-101',
    equipment_type: 'column_tray',
    type_detection: { equipment_type: 'column_tray', evidence: 'Mock: 板式塔，可见塔盘结构', confidence: 0.92 },
    assembly: { distillation_column: mockColumn },
    warnings: ['Mock warning: this is a mock result, not real extraction'],
    image_path: 'mock://equipment/page-1',
  };

  return {
    id: 'equipment_assembly-normal',
    label: '正常：塔装配信息',
    toolName: 'equipment_assembly',
    args: { pdf_path: 'data/设备装配/T-101.PDF', page_index: 0, dpi: 300, equipment_id: 'T-101' },
    steps: [
      { progress: 0, total: 3, message: 'Starting equipment assembly extraction' },
      { progress: 0.5, total: 3, message: 'Detecting equipment type' },
      {
        progress: 1, total: 3,
        message: 'Equipment type detected: column_tray',
        uiEvent: { event_type: 'type_detected', equipment_type: 'column_tray', confidence: 0.92 },
      },
      { progress: 1.5, total: 3, message: 'Extracting assembly data' },
      {
        progress: 2, total: 3,
        message: 'Assembly data extracted',
        uiEvent: { event_type: 'assembly_extracted', success: true },
      },
      { progress: 3, total: 3, message: 'Equipment assembly extraction completed' },
    ],
    review: {
      reviewId: 'review-equipment-assembly-001',
      finalResult: result,
      result,
    },
  };
}

// ---------------------------------------------------------------------------
// 工具 6: pfd_reflux（回流结构，PfdRefluxPage）
// ---------------------------------------------------------------------------

function pfdRefluxScenario(): MockScenario {
  const towers = [
    {
      id: 'T-201', tag: 'T-201', name: 'Main Distillation Column', has_reflux: true,
      condenser: { type: 'total', temperature: 80 },
      reboiler: { type: 'kettle', temperature: 180 },
      reflux_ratio: 2.5,
      operating_conditions: { temperature_top: 80, temperature_bottom: 180, pressure: 0.3 },
    },
  ];
  const reactors = [
    {
      id: 'R-101', tag: 'R-101', name: 'Feed Reactor', has_reflux: false,
      operating_conditions: { temperature: 300, pressure: 7.0 },
    },
  ];

  const result: Record<string, unknown> = {
    status: 'partial',
    workflow: 'pfd_reflux',
    expert_outputs: { pfd_reflux: { success: true, data: { towers, reactors } } },
    towers,
    reactors,
    warnings: ['Mock warning: this is a mock result, not real extraction'],
    image_path: 'mock://reflux/page-1',
  };

  return {
    id: 'pfd_reflux-normal',
    label: '正常：塔/反应器回流',
    toolName: 'pfd_reflux',
    args: { pdf_path: 'data/装置级/PFD.pdf', page_index: 0, dpi: 300, process_description: '' },
    steps: [
      { progress: 0, total: 2, message: 'Starting PFD reflux analysis' },
      {
        progress: 1, total: 2,
        message: 'Extraction completed',
        uiEvent: { event_type: 'extraction_complete', success: true, towers: 1, reactors: 1 },
      },
      { progress: 2, total: 2, message: 'PFD reflux analysis completed' },
    ],
    review: {
      reviewId: 'review-pfd-reflux-001',
      finalResult: result,
      result,
    },
  };
}

// ---------------------------------------------------------------------------
// 工具 7: composition_table（组分表，CompositionTablePage）
// ---------------------------------------------------------------------------

function compositionTableScenario(): MockScenario {
  const components = [
    { name: '氢气', molecular_weight: 2.02 },
    { name: '甲醇', molecular_weight: 32.04 },
    { name: '异戊烷', molecular_weight: 72.15 },
    { name: '1-戊烯', molecular_weight: 70.13 },
    { name: 'TAME', molecular_weight: 102.2 },
    { name: '水', molecular_weight: 18.01 },
  ];
  const streams = [
    {
      stream_id: '1',
      flow_rate: { value: 6300.0, unit: 'kg/h' },
      composition: [
        { component: '氢气', mole_fraction: null, mass_fraction: 0.0 },
        { component: '甲醇', mole_fraction: null, mass_fraction: 0.0 },
        { component: '异戊烷', mole_fraction: null, mass_fraction: 0.0743 },
        { component: '1-戊烯', mole_fraction: null, mass_fraction: 0.0847 },
        { component: 'TAME', mole_fraction: null, mass_fraction: 0.0 },
        { component: '水', mole_fraction: null, mass_fraction: 0.0 },
      ],
      temperature: { value: 25.0, unit: '℃' },
      pressure: { value: 0.68, unit: 'MPaG' },
      phase: '液相',
    },
    {
      stream_id: '2',
      flow_rate: { value: 4178.2, unit: 'kg/h' },
      composition: [
        { component: '氢气', mole_fraction: null, mass_fraction: 0.0 },
        { component: '甲醇', mole_fraction: null, mass_fraction: 0.0 },
        { component: '异戊烷', mole_fraction: null, mass_fraction: 0.01 },
        { component: '1-戊烯', mole_fraction: null, mass_fraction: 0.02 },
        { component: 'TAME', mole_fraction: null, mass_fraction: 0.95 },
        { component: '水', mole_fraction: null, mass_fraction: 0.02 },
      ],
      temperature: { value: 80.0, unit: '℃' },
      pressure: { value: 0.1, unit: 'MPaG' },
      phase: '液相',
    },
  ];

  const result: Record<string, unknown> = {
    status: 'success',
    aggregated: { components, streams },
    image_paths: ['mock://composition/page-1'],
    warnings: ['Mock warning: this is a mock result, not real extraction'],
  };

  return {
    id: 'composition_table-normal',
    label: '正常：组分 + 物流',
    toolName: 'composition_table',
    args: { pdf_path: 'data/组分表/组分表.pdf', start_page: 0, end_page: null, dpi: 300 },
    steps: [
      { progress: 0, total: 2, message: 'Starting composition table extraction' },
      {
        progress: 1, total: 2,
        message: '第 1/1 页提取完成',
        uiEvent: {
          event_type: 'composition_page_extracted', page_index: 0, has_table: true,
          partial_extracted: { components, streams },
        },
      },
      {
        progress: 2, total: 2,
        message: 'Composition table extraction completed',
        uiEvent: {
          event_type: 'aggregation_complete', component_count: components.length, stream_count: streams.length,
          partial_aggregated: { components, streams },
        },
      },
    ],
    review: {
      reviewId: 'review-composition-table-001',
      finalResult: result,
      result,
    },
  };
}

// ---------------------------------------------------------------------------
// 工具 8: progress_probe（progress 转发探测，ProgressProbePage，无审核）
// ---------------------------------------------------------------------------

function progressProbeScenario(): MockScenario {
  const count = 5;
  const now = Date.now() / 1000;
  const probes = Array.from({ length: count }, (_, i) => ({
    probe_seq: i + 1,
    server_ts: now + i,
    probe_count: count,
  }));

  return {
    id: 'progress_probe-normal',
    label: '正常：连续 progress 探测',
    toolName: 'progress_probe',
    args: { count, interval: 1.0 },
    steps: probes.map((p, i) => ({
      progress: i + 1,
      total: count,
      message: `probe ${i + 1}/${count}`,
      uiEvent: { event_type: 'progress_probe', ...p },
    })),
    review: {
      reviewId: 'review-progress-probe-001',
      finalResult: {
        status: 'success',
        workflow: 'progress_probe',
        probe_count: count,
        interval: 1.0,
        probes,
        message: `已发送 ${count} 个 progress 探测通知，查看 UI 是否动态刷新`,
      },
      result: {
        status: 'success',
        workflow: 'progress_probe',
        probe_count: count,
        interval: 1.0,
        probes,
        message: `已发送 ${count} 个 progress 探测通知，查看 UI 是否动态刷新`,
      },
    },
  };
}

// ---------------------------------------------------------------------------
// 失败 / 空结果场景（复用 pfd_topology 页面，验证错误传播）
// ---------------------------------------------------------------------------

function pfdTopologyErrorScenario(): MockScenario {
  const base = pfdTopologyScenario();
  const errorText = 'Mock error: deliberately failed after page 1 extraction (simulated)';
  return {
    id: 'pfd_topology-error',
    label: '错误：提取中途抛异常',
    toolName: 'pfd_topology',
    args: base.args,
    steps: base.steps.slice(0, 2),
    // 与后端一致：异常不会进入审核，直接以 isError 回发具体错误文本
    direct: { isError: true, errorText },
  };
}

function pfdTopologyStatusFailedScenario(): MockScenario {
  const base = pfdTopologyScenario();
  const errorText = 'Mock error: page 1 LLM extraction failed (simulated)';
  // 与后端 tools.py 页级 LLM 失败一致：status='failed' + errors 数组，不进审核
  const result: Record<string, unknown> = {
    version: '1.0.0',
    workflow: 'pfd_topology',
    status: 'failed',
    page_graphs: [],
    global_graph: {},
    image_path: '',
    image_paths: [],
    errors: [errorText],
    warnings: [errorText],
  };
  return {
    id: 'pfd_topology-status-failed',
    label: '失败：status=failed（页级 LLM 失败）',
    toolName: 'pfd_topology',
    args: base.args,
    steps: base.steps.slice(0, 2),
    direct: { result },
  };
}

/**
 * 通用 status='failed' 失败场景（页级 LLM 失败）。
 * 各页面仅依赖 status==='failed' + errors 数组，故不同工具可共用一个失败载荷。
 * @param toolName 工具名
 * @param label    场景标签
 * @param args     工具入参
 * @param steps    提取阶段 progress 序列（可省略，默认直接进入审核/回发）
 */
function statusFailedScenario(
  toolName: string,
  label: string,
  args: Record<string, unknown>,
  steps: ProgressStep[] = [],
): MockScenario {
  const errorText = `Mock error: ${toolName} LLM extraction failed (simulated)`;
  const result: Record<string, unknown> = {
    status: 'failed',
    workflow: toolName,
    errors: [errorText],
    warnings: [errorText],
  };
  return {
    id: `${toolName}-status-failed`,
    label,
    toolName,
    args,
    steps,
    // 与后端一致：status='failed' 不进审核，直接回发失败结果
    direct: { result },
  };
}

function pfdTopologyEmptyScenario(): MockScenario {
  const base = pfdTopologyScenario();
  // 提取阶段第 2 步已推送全部页 image_paths/image_infos，页数以此为准
  const imagesLoaded = base.steps[1].uiEvent!;
  const imagePaths = (imagesLoaded.image_paths ?? []) as string[];
  const imageInfos = (imagesLoaded.image_infos ?? []) as Array<{ path?: string; width?: number; height?: number }>;
  const pageCount = imagePaths.length;
  const emptyTopo = { equipment_nodes: [], boundary_nodes: [], edges: [] };
  // 与推送的页数保持一致（每页空拓扑），避免审核态页数跳变
  const pageGraphs = imagePaths.map((p, i) => ({
    page_index: i,
    page_label: `第 ${i + 1} 页`,
    pfd_drawing: {
      page_index: i,
      image_path: p,
      image_info: imageInfos[i] ?? { path: p },
      drawing_info: { drawing_type: 'PFD', page_count: pageCount },
      topology: emptyTopo,
    },
  }));
  const result: Record<string, unknown> = {
    version: '1.0.0',
    workflow: 'pfd_topology',
    status: 'success',
    page_graphs: pageGraphs,
    global_graph: { nodes: [], edges: [], cross_page_edges: [], node_index: {} },
    image_path: imagePaths[0] ?? '',
    image_paths: imagePaths,
    warnings: ['Mock warning: empty result'],
  };
  return {
    id: 'pfd_topology-empty',
    label: '空：无节点无边',
    toolName: 'pfd_topology',
    args: base.args,
    // 与后端一致：逐页推送空拓扑 partial_page_graphs，最后完成（总刻度 5）
    steps: [
      ...base.steps.slice(0, 2),
      ...pageGraphs.map((_, i) => ({
        progress: 3 + i,
        total: 5,
        message: `第 ${i + 1}/${pageCount} 页提取完成`,
        uiEvent: { partial_page_graphs: pageGraphs.slice(0, i + 1) },
      })),
      { progress: 5, total: 5, message: '分析完成（空结果）' },
    ],
    review: {
      reviewId: 'review-pfd-topology-empty-001',
      finalResult: result,
      result,
    },
  };
}

// ---------------------------------------------------------------------------
// 汇总导出
// ---------------------------------------------------------------------------

export interface ToolGroup {
  name: string;
  label: string;
  page: string;
  scenarios: MockScenario[];
}

export const MOCK_TOOLS: ToolGroup[] = [
  { name: 'pfd_topology', label: '装置级 PFD 拓扑', page: 'MultiPageTopologyPage', scenarios: [pfdTopologyScenario(), pfdTopologyEmptyScenario(), pfdTopologyErrorScenario(), pfdTopologyStatusFailedScenario()] },
  { name: 'plant_unit_topology', label: '整厂装置拓扑', page: 'PlantUnitPage', scenarios: [plantUnitScenario(), statusFailedScenario('plant_unit_topology', '失败：status=failed（页级 LLM 失败）', plantUnitScenario().args)] },
  { name: 'equipment_assembly', label: '设备装配图', page: 'EquipmentAssemblyPage', scenarios: [equipmentAssemblyScenario(), statusFailedScenario('equipment_assembly', '失败：status=failed（页级 LLM 失败）', equipmentAssemblyScenario().args)] },
  { name: 'process_package', label: '工艺包章节', page: 'GenericReviewPage', scenarios: [processPackageScenario(), statusFailedScenario('process_package', '失败：status=failed（页级 LLM 失败）', processPackageScenario().args)] },
  { name: 'pfd_reflux', label: '回流分析', page: 'PfdRefluxPage', scenarios: [pfdRefluxScenario(), statusFailedScenario('pfd_reflux', '失败：status=failed（页级 LLM 失败）', pfdRefluxScenario().args)] },
  { name: 'composition_table', label: '组分表', page: 'CompositionTablePage', scenarios: [compositionTableScenario(), statusFailedScenario('composition_table', '失败：status=failed（页级 LLM 失败）', compositionTableScenario().args)] },
  { name: 'progress_probe', label: 'Progress 探测', page: 'ProgressProbePage', scenarios: [progressProbeScenario()] },
];

/** 按 toolName 查找工具组。 */
export function findToolGroup(toolName: string): ToolGroup | undefined {
  return MOCK_TOOLS.find((t) => t.name === toolName);
}