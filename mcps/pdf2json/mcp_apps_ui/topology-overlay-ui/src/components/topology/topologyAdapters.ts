/**
 * 拓扑适配器：原始数据格式 ↔ ReactFlow 节点/边。
 *
 * 坐标模型：
 *   flow = pageOffset + local * scale   （逐轴 scale）
 *   - PFD：bbox/position 通常为归一化 [0,1]，scale = canvasW / canvasH
 *   - PlantUnit：x/y/width/height 为像素，scale = 1，pageOffset = 0
 *
 * 字段映射：
 *   - data.label ↔ raw.material_name（PFD/PlantUnit 边）
 *   - data.tag ↔ raw.tag（PFD 设备）/ raw.name（PlantUnit）
 *   - data.nodeType/data.boundaryType ↔ raw.node_type/raw.boundary_type
 *
 * 多页 id 策略：节点 id = `p{pageIndex}_{origId}`，跨页边引用这种 page-aware id；
 * 单页导出时剥离前缀还原 origId。
 */

import type { Node, Edge } from '@xyflow/react';
import type { BendPoint } from './EditableEdge';

// ===================== 类型 =====================

export interface ExportMeta {
  format: 'pfd' | 'plant_unit';
  scaleX: number;
  scaleY: number;
  pageOffsetX: number;
  pageOffsetY: number;
  /** local 空间下的原始尺寸（归一化或像素），拖拽时保留。 */
  origW: number;
  origH: number;
  pageIndex?: number;
}

export interface RFPort {
  id: string;
  direction: 'input' | 'output' | 'unknown';
  category?: string;
  label?: string;
  orientation: 'top' | 'bottom' | 'left' | 'right' | 'unknown';
  position?: [number, number] | null;
  parent_node_id?: string;
  channel?: string;
}

interface RFNodeData {
  tag?: string;
  nodeType?: 'equipment' | 'boundary';
  boundaryType?: string;
  inferred?: boolean;
  label?: string;
  width?: number;
  height?: number;
  ports?: RFPort[];
  raw?: Record<string, unknown>;
  _export?: ExportMeta;
  [k: string]: unknown;
}

interface RFEdgeData {
  label?: string;
  bendPoints?: BendPoint[];
  raw?: Record<string, unknown>;
  _export?: { kind: 'inner' | 'cross'; pageIndex?: number; fromPage?: number; toPage?: number };
  [k: string]: unknown;
}

// ===================== 工具 =====================

/** 解析 page-aware id "p0_xxx" → { pageIndex, nodeId }。 */
export function parsePageAwareId(id: string): { pageIndex: number; nodeId: string } | null {
  const m = String(id ?? '').match(/^p(\d+)_(.+)$/);
  if (!m) return null;
  return { pageIndex: parseInt(m[1], 10), nodeId: m[2] };
}

function pageId(pageIndex: number, origId: string): string {
  return `p${pageIndex}_${origId}`;
}

/** 把 raw.ports（后端 Port 字典数组）规整为前端 RFPort。 */
function parsePorts(raw: Record<string, unknown>): RFPort[] {
  const ports = raw.ports;
  if (!Array.isArray(ports)) return [];
  return (ports as Array<Record<string, unknown>>).map((p) => ({
    id: String(p.id ?? ''),
    direction: (p.direction as RFPort['direction']) ?? 'unknown',
    category: p.category != null ? String(p.category) : undefined,
    label: p.label != null ? String(p.label) : undefined,
    orientation: (p.orientation as RFPort['orientation']) ?? 'unknown',
    position: Array.isArray(p.position) ? (p.position as [number, number]) : null,
    parent_node_id: p.parent_node_id != null ? String(p.parent_node_id) : undefined,
    channel: p.channel != null ? String(p.channel) : undefined,
  })).filter((p) => p.id !== '');
}

/** 空串/undefined → null（RF Handle 接受 null 表示节点本身）。 */
function portIdToHandle(v: unknown): string | null {
  if (v == null) return null;
  const s = String(v);
  return s === '' ? null : s;
}

/** RFPort → 后端 raw.ports 字典（保持导出结构一致）。 */
function rfPortToRaw(p: RFPort): Record<string, unknown> {
  return {
    id: p.id,
    direction: p.direction,
    category: p.category ?? 'process',
    label: p.label ?? '',
    orientation: p.orientation,
    position: p.position ?? null,
    parent_node_id: p.parent_node_id ?? '',
    channel: p.channel ?? '',
  };
}

function isNormalizedNum(v: number): boolean {
  return v >= 0 && v <= 1;
}

/**
 * 判断 bbox 是否为归一化坐标。
 * - 数组格式 [x1, y1, x2, y2]：检查每个值是否在 [0,1]
 * - 对象格式 {x, y, width, height}：视为像素坐标，永远不归一化
 */
function isBboxNormalized(bbox: unknown): boolean {
  if (Array.isArray(bbox) && bbox.length === 4) {
    return (bbox as number[]).every(isNormalizedNum);
  }
  return false;
}

/** 解析后的几何信息（local 空间）。 */
interface ParsedGeom {
  cxL: number;
  cyL: number;
  origW: number;
  origH: number;
  isNorm: boolean;
}

/**
 * 从 raw 节点解析几何信息，兼容两种格式：
 * - 数组：bbox=[x1,y1,x2,y2]（归一化或像素）/ position=[x,y]
 * - 对象：bbox={x,y,width,height}（像素）/ position={x,y}（像素）
 */
function parseGeom(raw: Record<string, unknown>): ParsedGeom | null {
  const bbox = raw.bbox;
  const position = raw.position;

  // 数组格式: bbox = [x1, y1, x2, y2]
  if (Array.isArray(bbox) && bbox.length === 4) {
    const [x1, y1, x2, y2] = bbox as [number, number, number, number];
    return {
      cxL: (x1 + x2) / 2,
      cyL: (y1 + y2) / 2,
      origW: x2 - x1,
      origH: y2 - y1,
      isNorm: (bbox as number[]).every(isNormalizedNum),
    };
  }

  // 对象格式: bbox = {x, y, width, height}
  if (bbox && typeof bbox === 'object') {
    const b = bbox as { x: number; y: number; width: number; height: number };
    return {
      cxL: b.x + b.width / 2,
      cyL: b.y + b.height / 2,
      origW: b.width,
      origH: b.height,
      isNorm: false,
    };
  }

  // 数组格式: position = [x, y]
  if (Array.isArray(position) && position.length === 2) {
    const [x, y] = position as [number, number];
    const isNorm = (position as number[]).every(isNormalizedNum);
    return {
      cxL: x,
      cyL: y,
      origW: isNorm ? 0.08 : 80,
      origH: isNorm ? 0.05 : 40,
      isNorm,
    };
  }

  // 对象格式: position = {x, y}
  if (position && typeof position === 'object') {
    const p = position as { x: number; y: number };
    return {
      cxL: p.x,
      cyL: p.y,
      origW: 80,
      origH: 40,
      isNorm: false,
    };
  }

  return null;
}

// ===================== PFD 单页 → RF =====================

interface PfdPageGraph {
  page_index?: number;
  page_label?: string;
  pfd_drawing?: Record<string, unknown>;
  [k: string]: unknown;
}

/** 解析 pfd_drawing 得到 equipment_nodes / boundary_nodes / edges（兼容多种嵌套）。 */
export function parsePfdDrawing(drawing: Record<string, unknown> | undefined): {
  equipmentNodes: Array<Record<string, unknown>>;
  boundaryNodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  topologyRef: Record<string, unknown> | null;
} {
  if (!drawing) return { equipmentNodes: [], boundaryNodes: [], edges: [], topologyRef: null };
  let topo: Record<string, unknown> | null = null;
  if (drawing.topology && typeof drawing.topology === 'object') {
    const t = drawing.topology as Record<string, unknown>;
    if (t.topology && typeof t.topology === 'object') {
      topo = t.topology as Record<string, unknown>;
    } else if (t.equipment_nodes) {
      topo = t;
    }
  }
  if (!topo) {
    if (drawing.equipment_nodes || drawing.boundary_nodes) {
      topo = drawing;
    } else if (Array.isArray(drawing.nodes)) {
      // 新格式：nodes 数组用 node_type 区分 equipment/boundary，edges 在顶层
      const allNodes = drawing.nodes as Array<Record<string, unknown>>;
      return {
        equipmentNodes: allNodes.filter((n) => n.node_type === 'equipment'),
        boundaryNodes: allNodes.filter((n) => n.node_type === 'boundary'),
        edges: (drawing.edges as Array<Record<string, unknown>>) || [],
        topologyRef: drawing,
      };
    } else {
      return { equipmentNodes: [], boundaryNodes: [], edges: [], topologyRef: null };
    }
  }
  return {
    equipmentNodes: (topo.equipment_nodes as Array<Record<string, unknown>>) || [],
    boundaryNodes: (topo.boundary_nodes as Array<Record<string, unknown>>) || [],
    edges: (topo.edges as Array<Record<string, unknown>>) || [],
    topologyRef: topo,
  };
}

export interface PageLayout {
  pageIndex: number;
  offsetX: number;
  offsetY: number;
  canvasW: number;
  canvasH: number;
  imageUrl?: string;
  label: string;
}

/**
 * 把一个 PFD 页转成 RF 节点/边（含 page 背景）。
 * @param pageOffset 该页在全局 flow 空间的左上角偏移（单页模式传 {0,0}）
 */
export function pfdPageToRF(
  page: PfdPageGraph,
  layout: PageLayout,
): { nodes: Node[]; edges: Edge[] } {
  const pageIndex = layout.pageIndex;
  const { offsetX, offsetY, canvasW, canvasH } = layout;
  const parsed = parsePfdDrawing(page.pfd_drawing as Record<string, unknown> | undefined);

  const nodes: Node[] = [];

  // 页面背景图节点
  nodes.push({
    id: `__pagebg_${pageIndex}`,
    type: 'pageBg',
    position: { x: offsetX, y: offsetY },
    data: { url: layout.imageUrl, width: canvasW, height: canvasH },
    draggable: false,
    selectable: false,
    zIndex: -1,
    style: { width: canvasW, height: canvasH },
  });

  const makeNode = (
    raw: Record<string, unknown>,
    nodeType: 'equipment' | 'boundary',
  ): Node | null => {
    const origId = String(raw.id ?? raw.tag ?? '');
    if (!origId) return null;
    const id = pageId(pageIndex, origId);

    const geom = parseGeom(raw);
    if (!geom) return null;

    let scaleX = 1, scaleY = 1;
    if (geom.isNorm) { scaleX = canvasW; scaleY = canvasH; }

    const { cxL, cyL, origW, origH } = geom;
    const flowCx = offsetX + cxL * scaleX;
    const flowCy = offsetY + cyL * scaleY;
    const flowW = origW * scaleX;
    const flowH = origH * scaleY;
    const boundaryType = raw.boundary_type as string | undefined;

    const data: RFNodeData = {
      tag: String(raw.tag ?? raw.label ?? raw.id ?? ''),
      nodeType,
      boundaryType,
      inferred: Boolean(raw.inferred),
      width: Math.max(40, flowW),
      height: Math.max(24, flowH),
      ports: parsePorts(raw),
      raw,
      _export: {
        format: 'pfd',
        scaleX, scaleY,
        pageOffsetX: offsetX, pageOffsetY: offsetY,
        origW, origH, pageIndex,
      },
    };
    return {
      id,
      type: nodeType,
      position: { x: flowCx - data.width! / 2, y: flowCy - data.height! / 2 },
      data: data as unknown as Record<string, unknown>,
      draggable: true,
    };
  };

  for (const n of parsed.equipmentNodes) {
    const r = makeNode(n, 'equipment');
    if (r) nodes.push(r);
  }
  for (const n of parsed.boundaryNodes) {
    const r = makeNode(n, 'boundary');
    if (r) nodes.push(r);
  }

  // 边
  const edges: Edge[] = parsed.edges.map((e, i) => {
    const origId = String(e.id ?? e._key ?? `e${i}`);
    const src = String(e.source ?? e.source_node_id ?? '');
    const tgt = String(e.target ?? e.target_node_id ?? '');
    const label = (e.material_name ?? e.stream_name ?? '') as string;
    const wps = e.waypoints as Array<[number, number]> | undefined;
    const bends: BendPoint[] = (wps ?? []).map(([x, y]) => ({
      x: offsetX + x * scaleXHelper(parsed, canvasW),
      y: offsetY + y * scaleYHelper(parsed, canvasH),
    }));
    const sourceHandle = portIdToHandle(e.source_port_id);
    const targetHandle = portIdToHandle(e.target_port_id);
    return {
      id: pageId(pageIndex, origId),
      source: pageId(pageIndex, src),
      target: pageId(pageIndex, tgt),
      sourceHandle,
      targetHandle,
      type: 'editable',
      label,
      data: {
        label,
        bendPoints: bends,
        raw: e,
        _export: { kind: 'inner' as const, pageIndex },
      } as unknown as Record<string, unknown>,
    };
  });

  return { nodes, edges };
}

// 边 waypoints 的 scale 推断：与节点一致，按页内 bbox 是否归一化判断
function scaleXHelper(parsed: ReturnType<typeof parsePfdDrawing>, canvasW: number): number {
  const sample = parsed.equipmentNodes[0]?.bbox;
  return isBboxNormalized(sample) ? canvasW : 1;
}
function scaleYHelper(parsed: ReturnType<typeof parsePfdDrawing>, canvasH: number): number {
  const sample = parsed.equipmentNodes[0]?.bbox;
  return isBboxNormalized(sample) ? canvasH : 1;
}

// ===================== PlantUnit → RF =====================

interface PlantUnitDrawing {
  canvas_width?: number;
  canvas_height?: number;
  nodes?: Array<Record<string, unknown>>;
  edges?: Array<Record<string, unknown>>;
  [k: string]: unknown;
}

export function plantUnitToRF(drawing: PlantUnitDrawing, imageUrl?: string): { nodes: Node[]; edges: Edge[] } {
  const canvasW = drawing.canvas_width ?? 1200;
  const canvasH = drawing.canvas_height ?? 900;

  const nodes: Node[] = [];
  if (imageUrl) {
    nodes.push({
      id: '__pagebg_0',
      type: 'pageBg',
      position: { x: 0, y: 0 },
      data: { url: imageUrl, width: canvasW, height: canvasH },
      draggable: false,
      selectable: false,
      zIndex: -1,
      style: { width: canvasW, height: canvasH },
    });
  }

  for (const raw of drawing.nodes ?? []) {
    const id = String(raw.node_id ?? raw.id ?? '');
    if (!id) continue;
    const x = Number(raw.x ?? 0);
    const y = Number(raw.y ?? 0);
    const w = Number(raw.width ?? 100);
    const h = Number(raw.height ?? 60);
    const data: RFNodeData = {
      tag: String(raw.display_name ?? raw.name ?? raw.unit_name ?? raw.label ?? id),
      nodeType: 'equipment',
      width: w,
      height: h,
      raw,
      _export: {
        format: 'plant_unit',
        scaleX: 1, scaleY: 1,
        pageOffsetX: 0, pageOffsetY: 0,
        origW: w, origH: h, pageIndex: 0,
      },
    };
    nodes.push({
      id,
      type: 'equipment',
      position: { x, y },
      data: data as unknown as Record<string, unknown>,
      draggable: true,
    });
  }

  const edges: Edge[] = (drawing.edges ?? []).map((e, i) => {
    const id = String(e._key ?? e.id ?? `e${i}`);
    const src = String(e.source_id ?? e.source_node_id ?? '');
    const tgt = String(e.target_id ?? e.target_node_id ?? '');
    const label = (e.material_name ?? e.medium ?? e.stream_name ?? '') as string;
    const wps = e.waypoints as Array<[number, number]> | undefined;
    const bends: BendPoint[] = (wps ?? []).map(([x, y]) => ({ x, y }));
    return {
      id,
      source: src,
      target: tgt,
      type: 'editable',
      label,
      data: {
        label,
        bendPoints: bends,
        raw: e,
        _export: { kind: 'inner' as const, pageIndex: 0 },
      } as unknown as Record<string, unknown>,
    };
  });

  return { nodes, edges };
}

// ===================== 跨页连接 → RF =====================

export interface CrossLink {
  fromPage: number;
  fromNode: string;
  toPage: number;
  toNode: string;
  label: string;
  bendPoints?: Array<{ x: number; y: number }>;
}

export function crossLinksToRF(links: CrossLink[]): Edge[] {
  return links.map((l, i) => ({
    id: `__cross_${i}`,
    source: pageId(l.fromPage, l.fromNode),
    target: pageId(l.toPage, l.toNode),
    type: 'editable',
    label: l.label,
    data: {
      label: l.label,
      bendPoints: (l.bendPoints ?? []).map((b) => ({ x: b.x, y: b.y })),
      raw: {},
      _export: { kind: 'cross' as const, fromPage: l.fromPage, toPage: l.toPage },
    } as unknown as Record<string, unknown>,
    style: { stroke: 'var(--cyan)', strokeDasharray: '6 4' },
  }));
}

// ===================== RF → 原始格式（导出） =====================

function flowToLocalCenter(node: Node): { cx: number; cy: number; meta: ExportMeta } | null {
  const data = node.data as RFNodeData;
  const meta = data._export;
  if (!meta) return null;
  const w = data.width ?? 80;
  const h = data.height ?? 32;
  const flowCx = node.position.x + w / 2;
  const flowCy = node.position.y + h / 2;
  const cx = (flowCx - meta.pageOffsetX) / meta.scaleX;
  const cy = (flowCy - meta.pageOffsetY) / meta.scaleY;
  return { cx, cy, meta };
}

/**
 * 导出单页 PFD：返回更新后的 pfd_drawing（保留原结构）。
 * 单页模式 pageOffset={0,0}；多页全局模式传入该页的 pageOffset。
 * 节点坐标由 meta.pageOffset（建图时写入）还原；边 bendPoints 由传入 pageOffset 还原。
 */
export function rfToPfdPage(
  rfNodes: Node[],
  rfEdges: Edge[],
  pageIndex: number,
  pageOffset: { x: number; y: number },
  canvasW: number,
  canvasH: number,
  originalPage: PfdPageGraph,
): Record<string, unknown> {
  const parsed = parsePfdDrawing(originalPage.pfd_drawing as Record<string, unknown> | undefined);
  const origEquipById = new Map(parsed.equipmentNodes.map((n) => [String(n.id ?? n.tag), n]));
  const origBdById = new Map(parsed.boundaryNodes.map((n) => [String(n.id ?? n.label), n]));

  // 该页是否归一化坐标（用首个设备 bbox 判断）
  const sampleBbox = parsed.equipmentNodes[0]?.bbox;
  const isNorm = isBboxNormalized(sampleBbox);
  const scaleX = isNorm ? canvasW : 1;
  const scaleY = isNorm ? canvasH : 1;

  const equipmentNodes: Array<Record<string, unknown>> = [];
  const boundaryNodes: Array<Record<string, unknown>> = [];

  for (const node of rfNodes) {
    if (node.type === 'pageBg') continue;
    const data = node.data as RFNodeData;
    const meta = data._export;
    if (!meta || meta.pageIndex !== pageIndex) continue;
    const origId = parsePageAwareId(node.id)?.nodeId ?? node.id;
    const orig = (node.type === 'boundary' ? origBdById : origEquipById).get(origId) ?? data.raw ?? {};
    const raw: Record<string, unknown> = { ...orig };
    raw.id = origId;
    if (node.type === 'equipment') raw.tag = data.tag ?? orig.tag;
    else raw.label = data.tag ?? orig.label;
    raw.node_type = node.type === 'boundary' ? 'boundary' : 'equipment';
    if (node.type === 'boundary') raw.boundary_type = data.boundaryType;
    if (data.inferred != null) raw.inferred = data.inferred;
    // 端口回写：data.ports → raw.ports
    if (data.ports != null) {
      raw.ports = data.ports.map(rfPortToRaw);
    }

    const lc = flowToLocalCenter(node);
    if (lc) {
      const newBbox = [
        lc.cx - meta.origW / 2, lc.cy - meta.origH / 2,
        lc.cx + meta.origW / 2, lc.cy + meta.origH / 2,
      ];
      if (orig.bbox || isNorm) raw.bbox = newBbox;
      else raw.position = [lc.cx, lc.cy];
    }
    (node.type === 'boundary' ? boundaryNodes : equipmentNodes).push(raw);
  }

  const edges: Array<Record<string, unknown>> = [];
  for (const e of rfEdges) {
    const data = e.data as RFEdgeData;
    const ex = data._export;
    if (!ex || ex.kind !== 'inner' || ex.pageIndex !== pageIndex) continue;
    const raw: Record<string, unknown> = { ...(data.raw ?? {}) };
    raw.id = parsePageAwareId(e.id)?.nodeId ?? e.id;
    raw.source = parsePageAwareId(e.source)?.nodeId ?? e.source;
    raw.target = parsePageAwareId(e.target)?.nodeId ?? e.target;
    // 端口回写：edge.sourceHandle/targetHandle → raw.source_port_id/target_port_id
    raw.source_port_id = e.sourceHandle ?? '';
    raw.target_port_id = e.targetHandle ?? '';
    if (data.label != null) raw.material_name = data.label;
    const bends = data.bendPoints ?? [];
    if (bends.length > 0) {
      raw.waypoints = bends.map((b) => [
        (b.x - pageOffset.x) / scaleX,
        (b.y - pageOffset.y) / scaleY,
      ]);
    }
    edges.push(raw);
  }

  // 回填到原 pfd_drawing 结构（保留嵌套层级）
  const drawing = { ...(originalPage.pfd_drawing as Record<string, unknown> ?? {}) };
  const fillTopo = (topo: Record<string, unknown>) => ({
    ...topo,
    equipment_nodes: equipmentNodes,
    boundary_nodes: boundaryNodes,
    edges,
  });
  if (drawing.topology && typeof drawing.topology === 'object') {
    const t = drawing.topology as Record<string, unknown>;
    if (t.topology && typeof t.topology === 'object') {
      t.topology = fillTopo(t.topology as Record<string, unknown>);
    } else {
      drawing.topology = fillTopo(t);
    }
  } else {
    drawing.equipment_nodes = equipmentNodes;
    drawing.boundary_nodes = boundaryNodes;
    drawing.edges = edges;
  }
  return drawing;
}

/** 导出 PlantUnit drawing。 */
export function rfToPlantUnit(
  rfNodes: Node[],
  rfEdges: Edge[],
  original: PlantUnitDrawing,
): PlantUnitDrawing {
  const out: PlantUnitDrawing = {
    ...original,
    nodes: [],
    edges: [],
  };
  const origById = new Map((original.nodes ?? []).map((n) => [String(n.node_id ?? n.id), n]));

  for (const node of rfNodes) {
    if (node.type === 'pageBg') continue;
    const data = node.data as RFNodeData;
    const meta = data._export;
    if (!meta) continue;
    const orig = origById.get(node.id) ?? data.raw ?? {};
    const raw: Record<string, unknown> = { ...orig };
    raw.node_id = node.id;
    raw.name = data.tag ?? orig.name;
    raw.display_name = data.tag ?? orig.display_name;
    const w = data.width ?? meta.origW;
    const h = data.height ?? meta.origH;
    raw.x = node.position.x;
    raw.y = node.position.y;
    raw.width = w;
    raw.height = h;
    out.nodes!.push(raw);
  }

  for (const e of rfEdges) {
    const data = e.data as RFEdgeData;
    const ex = data._export;
    if (!ex || ex.kind !== 'inner') continue;
    const raw: Record<string, unknown> = { ...(data.raw ?? {}) };
    raw._key = e.id;
    raw.source_id = e.source;
    raw.target_id = e.target;
    if (data.label != null) raw.material_name = data.label;
    const bends = data.bendPoints ?? [];
    if (bends.length > 0) {
      raw.waypoints = bends.map((b) => [b.x, b.y]);
    }
    out.edges!.push(raw);
  }

  return out;
}

/** 导出跨页连接（全局模式）。 */
export function rfToCrossLinks(rfEdges: Edge[]): CrossLink[] {
  const out: CrossLink[] = [];
  for (const e of rfEdges) {
    const data = e.data as RFEdgeData;
    const ex = data._export;
    if (!ex || ex.kind !== 'cross') continue;
    const src = parsePageAwareId(e.source);
    const tgt = parsePageAwareId(e.target);
    if (!src || !tgt) continue;
    out.push({
      fromPage: src.pageIndex,
      fromNode: src.nodeId,
      toPage: tgt.pageIndex,
      toNode: tgt.nodeId,
      label: data.label ?? '',
      bendPoints: (data.bendPoints ?? []).map((b) => ({ x: b.x, y: b.y })),
    });
  }
  return out;
}

/** 判断 RF 边是否为跨页边。 */
export function isCrossEdge(e: Edge): boolean {
  return (e.data as RFEdgeData)?._export?.kind === 'cross';
}
