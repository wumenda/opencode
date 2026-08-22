/**
 * 拓扑图组件（替代 topology_viewer.html / plant_unit_viewer.html 的 SVG 渲染部分）。
 *
 * 使用 @xyflow/react 渲染设备节点 + 边界节点 + 流股边。
 *
 * 支持两种数据格式：
 *   1. PFD 拓扑格式（extract_pfd_topology 产物）：
 *      nodes: { id, tag, node_type: 'equipment'|'boundary',
 *               boundary_type?: 'boundary_in'|'boundary_out'|'cross_drawing_in'|'cross_drawing_out',
 *               bbox?: [x1,y1,x2,y2]（归一化 [0,1] 坐标）, position?: [x,y], inferred? }
 *      edges: { source, target, material_name?, waypoints? }
 *
 *   2. 装置拓扑格式（extract_plant_unit_topology 产物）：
 *      nodes: { node_id, x, y, width, height, ... }
 *      edges: { _key, source_id, target_id, material_name?, waypoints? }
 *
 * 通过 fromPfdTopology() / fromPlantUnit() 适配器归一化后传入。
 */

import { useMemo } from 'react';
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  type NodeProps,
  Handle,
  Position,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

// ===================== 归一化数据模型 =====================

export interface NormalizedNode {
  id: string;
  tag?: string;
  nodeType: 'equipment' | 'boundary';
  boundaryType?: string;
  /** 像素坐标 [x1, y1, x2, y2]。 */
  bbox?: [number, number, number, number];
  /** 中心点（无 bbox 时回退）。 */
  position?: [number, number];
  inferred?: boolean;
  /** 原始数据（JSON 编辑时回传）。 */
  raw?: Record<string, unknown>;
}

export interface NormalizedEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
  waypoints?: Array<[number, number]>;
  raw?: Record<string, unknown>;
}

export interface TopologyGraphProps {
  nodes: NormalizedNode[];
  edges: NormalizedEdge[];
  /** 画布像素尺寸（用于归一化坐标缩放）。 */
  canvasWidth?: number;
  canvasHeight?: number;
  /** 背景图（PDF 页面原图）。 */
  imageUrl?: string;
  className?: string;
  /** 是否允许编辑节点位置。 */
  nodesDraggable?: boolean;
}

// ===================== 适配器 =====================

interface PlantUnitNode {
  node_id?: string;
  id?: string;
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  name?: string;
  label?: string;
  [k: string]: unknown;
}

interface PlantUnitEdge {
  _key?: string;
  id?: string;
  source_id?: string;
  target_id?: string;
  material_name?: string;
  waypoints?: Array<[number, number]>;
  [k: string]: unknown;
}

interface PlantUnitData {
  canvas_width?: number;
  canvas_height?: number;
  nodes?: PlantUnitNode[];
  edges?: PlantUnitEdge[];
}

/** 从装置拓扑格式归一化。 */
export function fromPlantUnit(data: PlantUnitData): {
  nodes: NormalizedNode[];
  edges: NormalizedEdge[];
  canvasWidth: number;
  canvasHeight: number;
} {
  const canvasWidth = data.canvas_width ?? 1000;
  const canvasHeight = data.canvas_height ?? 800;
  const nodes: NormalizedNode[] = (data.nodes || []).map((n) => {
    const id = String(n.node_id ?? n.id ?? '');
    const x = Number(n.x ?? 0);
    const y = Number(n.y ?? 0);
    const w = Number(n.width ?? 100);
    const h = Number(n.height ?? 60);
    return {
      id,
      tag: String(n.name ?? n.label ?? id),
      nodeType: 'equipment',
      bbox: [x, y, x + w, y + h],
      raw: n as Record<string, unknown>,
    };
  });
  const edges: NormalizedEdge[] = (data.edges || []).map((e, i) => ({
    id: String(e._key ?? e.id ?? `e${i}`),
    source: String(e.source_id ?? ''),
    target: String(e.target_id ?? ''),
    label: e.material_name,
    waypoints: e.waypoints,
    raw: e as Record<string, unknown>,
  }));
  return { nodes, edges, canvasWidth, canvasHeight };
}

interface PfdTopology {
  equipment_nodes?: Array<Record<string, unknown>>;
  boundary_nodes?: Array<Record<string, unknown>>;
  edges?: Array<Record<string, unknown>>;
}

interface PfdResult {
  topology?: PfdTopology | { topology: PfdTopology };
  equipment_nodes?: Array<Record<string, unknown>>;
  boundary_nodes?: Array<Record<string, unknown>>;
  edges?: Array<Record<string, unknown>>;
  expert_outputs?: Record<string, unknown>;
}

/** 从 PFD 拓扑格式归一化。支持多种嵌套结构。 */
export function fromPfdTopology(
  data: PfdResult,
): { nodes: NormalizedNode[]; edges: NormalizedEdge[] } {
  let topology: PfdTopology;
  if (data.topology && 'topology' in (data.topology as object)) {
    topology = (data.topology as { topology: PfdTopology }).topology;
  } else if (data.topology) {
    topology = data.topology as PfdTopology;
  } else if (data.equipment_nodes) {
    topology = {
      equipment_nodes: data.equipment_nodes,
      boundary_nodes: data.boundary_nodes || [],
      edges: data.edges || [],
    };
  } else {
    topology = { equipment_nodes: [], boundary_nodes: [], edges: [] };
  }

  const equipNodes: NormalizedNode[] = (topology.equipment_nodes || []).map((n) => ({
    id: String(n.id ?? n.tag ?? ''),
    tag: String(n.tag ?? n.id ?? ''),
    nodeType: 'equipment' as const,
    bbox: n.bbox as [number, number, number, number] | undefined,
    position: n.position as [number, number] | undefined,
    inferred: n.inferred as boolean | undefined,
    raw: n,
  }));

  const boundaryNodes: NormalizedNode[] = (topology.boundary_nodes || []).map((n) => ({
    id: String(n.id ?? n.label ?? ''),
    tag: String(n.label ?? n.description ?? n.id ?? ''),
    nodeType: 'boundary' as const,
    boundaryType: String(n.boundary_type ?? ''),
    bbox: n.bbox as [number, number, number, number] | undefined,
    position: n.position as [number, number] | undefined,
    inferred: n.inferred as boolean | undefined,
    raw: n,
  }));

  const edges: NormalizedEdge[] = (topology.edges || []).map((e, i) => ({
    id: String(e.id ?? e._key ?? `e${i}`),
    source: String(e.source ?? e.source_node_id ?? ''),
    target: String(e.target ?? e.target_node_id ?? ''),
    label: (e.material_name ?? e.stream_name ?? undefined) as string | undefined,
    waypoints: e.waypoints as Array<[number, number]> | undefined,
    raw: e,
  }));

  return { nodes: [...equipNodes, ...boundaryNodes], edges };
}

// ===================== 自定义节点 =====================

const EQUIPMENT_COLOR = 'var(--accent)';
const BOUNDARY_IN_COLOR = 'var(--green)';
const BOUNDARY_OUT_COLOR = 'var(--orange)';
const CROSS_IN_COLOR = 'var(--purple)';
const CROSS_OUT_COLOR = 'var(--cyan)';

function boundaryColor(boundaryType?: string): string {
  switch (boundaryType) {
    case 'boundary_in':
      return BOUNDARY_IN_COLOR;
    case 'boundary_out':
      return BOUNDARY_OUT_COLOR;
    case 'cross_drawing_in':
      return CROSS_IN_COLOR;
    case 'cross_drawing_out':
      return CROSS_OUT_COLOR;
    default:
      return BOUNDARY_IN_COLOR;
  }
}

interface EquipmentNodeData {
  tag?: string;
  inferred?: boolean;
  [k: string]: unknown;
}

const EquipmentNodeComponent = ({ data }: NodeProps) => {
  const d = data as unknown as EquipmentNodeData;
  return (
    <div
      className="flex items-center justify-center rounded-md border-2 px-2 py-1 text-center"
      style={{
        minWidth: 60,
        minHeight: 32,
        borderColor: EQUIPMENT_COLOR,
        background: 'rgba(59, 130, 246, 0.10)',
        color: 'var(--text)',
        fontSize: 11,
        fontFamily: 'var(--font-mono, monospace)',
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: EQUIPMENT_COLOR }} />
      <span className="truncate" style={{ maxWidth: 120 }}>
        {d.tag || ''}
      </span>
      {d.inferred && (
        <span
          className="ml-1 rounded px-1 text-[9px]"
          style={{ background: 'var(--orange)', color: '#fff' }}
        >
          推断
        </span>
      )}
      <Handle type="source" position={Position.Right} style={{ background: EQUIPMENT_COLOR }} />
    </div>
  );
};

interface BoundaryNodeData {
  tag?: string;
  boundaryType?: string;
  [k: string]: unknown;
}

const BoundaryNodeComponent = ({ data }: NodeProps) => {
  const d = data as unknown as BoundaryNodeData;
  const color = boundaryColor(d.boundaryType);
  const isInput = d.boundaryType?.includes('in');
  return (
    <div
      className="flex items-center justify-center rounded-full border-2 px-2 py-0.5 text-center"
      style={{
        minWidth: 50,
        minHeight: 24,
        borderColor: color,
        background: `${color}1A`,
        color,
        fontSize: 10,
        fontFamily: 'var(--font-mono, monospace)',
      }}
    >
      <Handle
        type={isInput ? 'source' : 'target'}
        position={isInput ? Position.Right : Position.Left}
        style={{ background: color }}
      />
      <span className="truncate" style={{ maxWidth: 80 }}>{d.tag || ''}</span>
    </div>
  );
};

const nodeTypes = {
  equipment: EquipmentNodeComponent,
  boundary: BoundaryNodeComponent,
};

// ===================== 主组件 =====================

export function TopologyGraph({
  nodes,
  edges,
  canvasWidth = 1000,
  canvasHeight = 1000,
  imageUrl,
  className = '',
  nodesDraggable = false,
}: TopologyGraphProps) {
  // 把归一化节点转换为 @xyflow/react 节点格式
  const rfNodes: Node[] = useMemo(() => {
    return nodes.map((n) => {
      // 计算中心点和尺寸
      let cx: number, cy: number, w = 80, h = 32;
      if (n.bbox) {
        const [x1, y1, x2, y2] = n.bbox;
        // bbox 可能是归一化 [0,1] 坐标 -> 缩放到 canvas
        const isNormalized =
          x1 >= 0 && x1 <= 1 && y1 >= 0 && y1 <= 1 && x2 >= 0 && x2 <= 1 && y2 >= 0 && y2 <= 1;
        const scale = isNormalized ? Math.max(canvasWidth, canvasHeight) : 1;
        cx = ((x1 + x2) / 2) * scale;
        cy = ((y1 + y2) / 2) * scale;
        w = Math.max(60, (x2 - x1) * scale);
        h = Math.max(28, (y2 - y1) * scale);
      } else if (n.position) {
        const [px, py] = n.position;
        const isNormalized = px >= 0 && px <= 1 && py >= 0 && py <= 1;
        const scale = isNormalized ? Math.max(canvasWidth, canvasHeight) : 1;
        cx = px * scale;
        cy = py * scale;
      } else {
        cx = 0;
        cy = 0;
      }

      return {
        id: n.id,
        type: n.nodeType,
        position: { x: cx - w / 2, y: cy - h / 2 },
        data: {
          tag: n.tag,
          inferred: n.inferred,
          boundaryType: n.boundaryType,
          raw: n.raw,
        } as unknown as Record<string, unknown>,
        draggable: nodesDraggable,
        style: { width: w, height: h },
      };
    });
  }, [nodes, canvasWidth, canvasHeight, nodesDraggable]);

  const rfEdges: Edge[] = useMemo(() => {
    return edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      label: e.label,
      type: 'smoothstep',
      labelStyle: { fontSize: 10, fill: 'var(--text2)' },
      labelBgStyle: { fill: 'var(--bg2)' },
      style: { stroke: 'var(--accent)', strokeWidth: 1.5 },
    }));
  }, [edges]);

  // 背景图节点（如果提供）
  const bgNode: Node | null = useMemo(() => {
    if (!imageUrl) return null;
    return {
      id: '__bg__',
      type: 'image' as never,
      position: { x: 0, y: 0 },
      data: { url: imageUrl },
      draggable: false,
      selectable: false,
      zIndex: -1,
      style: { width: canvasWidth, height: canvasHeight, pointerEvents: 'none' },
    } as Node;
  }, [imageUrl, canvasWidth, canvasHeight]);

  const allNodes = bgNode ? [bgNode, ...rfNodes] : rfNodes;

  const defaultEdgeOptions = useMemo(
    () => ({
      type: 'smoothstep',
      style: { stroke: 'var(--accent)', strokeWidth: 1.5 },
    }),
    [],
  );

  return (
    <div className={`h-full w-full ${className}`}>
      <ReactFlow
        nodes={allNodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        defaultEdgeOptions={defaultEdgeOptions}
        fitView
        fitViewOptions={{ padding: 0.1 }}
        minZoom={0.1}
        maxZoom={3}
        proOptions={{ hideAttribution: true }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          color={'var(--border)'}
          gap={20}
          size={1}
        />
        <Controls
          className="!border !border-border !bg-bg-2/80 !shadow-card"
          showInteractive={false}
        />
        <MiniMap
          pannable
          zoomable
          className="!border !border-border !bg-bg-2/80"
          maskColor="rgba(0,0,0,0.5)"
          nodeColor={(n) => {
            if (n.type === 'boundary') {
              return boundaryColor((n.data as { boundaryType?: string }).boundaryType);
            }
            return EQUIPMENT_COLOR;
          }}
        />
      </ReactFlow>
    </div>
  );
}
