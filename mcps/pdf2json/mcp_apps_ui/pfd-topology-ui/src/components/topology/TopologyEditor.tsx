/**
 * 拓扑编辑器：基于 @xyflow/react 的可编辑拓扑画布。
 *
 * 职责：
 *   - 节点拖拽、选中、增删
 *   - 边连接（onConnect）、端点重连（onReconnect）、折点编辑（EditableEdge）
 *   - 撤销/重做（useHistory）
 *   - 属性面板（PropertyPanel）
 *   - 浮动工具栏（撤销/重做/添加节点/删除/适配视图）
 *
 * 数据约定：
 *   - 接收已定位的 RF 节点/边（Node[]/Edge[]），坐标数学由调用方负责。
 *   - 节点 data.raw 保留原始记录，导出时由调用方做反归一化。
 *   - 边折点存于 edge.data.bendPoints（flow 坐标）。
 *
 * 通过 ref 暴露 getEdited() / reset()。
 */

import {
  forwardRef,
  useCallback,
  useContext,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Handle,
  Position,
  ConnectionMode,
  MarkerType,
  addEdge,
  reconnectEdge,
  useNodesState,
  useEdgesState,
  useReactFlow,
  type Node,
  type Edge,
  type Connection,
  type EdgeChange,
  type NodeChange,
  type OnReconnect,
  type NodeProps,
  type ReactFlowProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useHistory } from '@/core/hooks/useHistory';
import { EdgeEditorContext, type EdgeEditorContextValue } from './edgeEditorContext';
import { EditableEdge } from './EditableEdge';
import { PropertyPanel, type EditableField } from './PropertyPanel';
import { ViewContext, type ViewContextValue } from './viewContext';
import { ResizeHandle } from './ResizeHandle';
import { EdgeReviewBar } from './EdgeReviewBar';
import type { RFPort } from './topologyAdapters';

// ===================== 节点类型 =====================

const EQUIPMENT_COLOR = 'var(--accent)';
const BOUNDARY_IN_COLOR = 'var(--green)';
const BOUNDARY_OUT_COLOR = 'var(--orange)';
const CROSS_IN_COLOR = 'var(--purple)';
const CROSS_OUT_COLOR = 'var(--cyan)';

export function boundaryColor(boundaryType?: string): string {
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

interface EquipData {
  tag?: string;
  inferred?: boolean;
  width?: number;
  height?: number;
  ports?: RFPort[];
  [k: string]: unknown;
}

function orientationToPosition(o: RFPort['orientation']): Position {
  switch (o) {
    case 'top': return Position.Top;
    case 'bottom': return Position.Bottom;
    case 'right': return Position.Right;
    case 'left': return Position.Left;
    default: return Position.Left;
  }
}

/** input→target，output/unknown→source（unknown 配合 ConnectionMode.Loose 允许双向）。 */
function portHandleType(d: RFPort['direction']): 'source' | 'target' {
  return d === 'input' ? 'target' : 'source';
}

/** 从节点 id 推导其所在页的背景节点 id（__pagebg_{pageIndex}），非页内节点返回 null。 */
function pageIdFromNodeId(id: string): string | null {
  if (id.startsWith('__pagebg_')) return id;
  const m = id.match(/^p(\d+)_/);
  if (m) return `__pagebg_${m[1]}`;
  return null;
}

/**
 * 渲染节点动态端口 Handle。同 orientation 的多个端口沿该边均匀分布。
 * 返回 null 表示无 ports，调用方回退到固定 Handle。
 */
function renderPortHandles(ports: RFPort[] | undefined, color: string): React.ReactNode[] | null {
  if (!ports || ports.length === 0) return null;
  const groups: Record<'top' | 'bottom' | 'left' | 'right', RFPort[]> = { top: [], bottom: [], left: [], right: [] };
  for (const p of ports) {
    // orientation 已知时按其分组；unknown 时按 direction 分配到左右两端
    const key: 'top' | 'bottom' | 'left' | 'right' =
      p.orientation === 'top' || p.orientation === 'bottom' || p.orientation === 'left' || p.orientation === 'right'
        ? p.orientation
        : p.direction === 'output'
          ? 'right'
          : 'left';
    groups[key].push(p);
  }
  const handles: React.ReactNode[] = [];
  (['top', 'bottom', 'left', 'right'] as const).forEach((orientation) => {
    const group = groups[orientation];
    if (group.length === 0) return;
    const pos = orientationToPosition(orientation);
    const n = group.length;
    group.forEach((p, i) => {
      const ratio = n === 1 ? 0.5 : i / (n - 1);
      const style: React.CSSProperties = { background: color };
      if (orientation === 'top' || orientation === 'bottom') {
        style.left = `${ratio * 100}%`;
        style.transform = 'translate(-50%, 0)';
      } else {
        style.top = `${ratio * 100}%`;
        style.transform = 'translate(0, -50%)';
      }
      handles.push(
        <Handle
          key={p.id}
          id={p.id}
          type={portHandleType(p.direction)}
          position={pos}
          style={style}
          title={`${p.id}${p.label ? ' · ' + p.label : ''} (${p.direction}/${p.orientation})`}
        />,
      );
    });
  });
  return handles;
}

/** RFPort → 后端 raw.ports 字典（保持导出结构一致）。 */
function toRawPort(p: RFPort): Record<string, unknown> {
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

const EquipmentNode = ({ id, data, positionAbsoluteX, positionAbsoluteY, selected }: NodeProps) => {
  const d = data as unknown as EquipData;
  const view = useContext(ViewContext);
  const w = d.width ?? 80;
  const h = d.height ?? 32;
  const portHandles = renderPortHandles(d.ports, EQUIPMENT_COLOR);
  const isAdjusting = view.adjustingNodeId === id;
  const isHighlighted = selected || isAdjusting;
  return (
    <div
      className={`relative flex items-center justify-center rounded-lg border-2 px-2 py-1 text-center transition-all duration-200 ${isHighlighted ? 'anim-node-selected-glow' : ''}`}
      style={{
        minWidth: 60,
        minHeight: 32,
        width: w,
        height: h,
        borderColor: isAdjusting ? 'var(--accent)' : selected ? 'var(--orange)' : EQUIPMENT_COLOR,
        background: isHighlighted
          ? 'var(--grad-equip)'
          : 'linear-gradient(135deg, rgba(37, 99, 235, 0.08) 0%, rgba(37, 99, 235, 0.02) 100%)',
        backdropFilter: 'blur(2px)',
        color: 'var(--text)',
        fontSize: 11,
        fontWeight: 500,
        fontFamily: 'var(--font-mono, monospace)',
        boxShadow: isAdjusting
          ? '0 0 0 3px rgba(37, 99, 235, 0.2), 0 4px 12px rgba(10,26,95,0.15)'
          : selected
          ? '0 0 0 3px rgba(234, 140, 12, 0.22), 0 4px 14px rgba(234,140,12,0.18)'
          : '0 1px 3px rgba(10,26,95,0.08), 0 0 0 1px rgba(37,99,235,0.04) inset',
        transform: isHighlighted ? 'translateY(-1px)' : 'translateY(0)',
      }}
    >
      {portHandles ?? (
        <>
          <Handle
            type="target"
            position={Position.Left}
            style={{
              background: EQUIPMENT_COLOR,
              width: 10,
              height: 10,
              border: '2px solid #fff',
              boxShadow: '0 1px 3px rgba(10,26,95,0.2)',
            }}
          />
          <Handle
            type="source"
            position={Position.Right}
            style={{
              background: EQUIPMENT_COLOR,
              width: 10,
              height: 10,
              border: '2px solid #fff',
              boxShadow: '0 1px 3px rgba(10,26,95,0.2)',
            }}
          />
        </>
      )}
      <span className="truncate" style={{ maxWidth: w - 8, letterSpacing: '0.01em' }}>
        {d.tag || ''}
      </span>
      {d.inferred && (
        <span
          className="ml-1 rounded-full px-1.5 text-[9px] font-medium"
          style={{
            background: 'linear-gradient(135deg, var(--orange), #f97316)',
            color: '#fff',
            boxShadow: '0 1px 3px rgba(234,140,12,0.3)',
          }}
        >
          推断
        </span>
      )}
      {isAdjusting && (
        <>
          <ResizeHandle corner="tl" nodeX={positionAbsoluteX} nodeY={positionAbsoluteY} nodeW={w} nodeH={h} onResizeEnd={(next) => view.onNodeResize(id, next)} />
          <ResizeHandle corner="tr" nodeX={positionAbsoluteX} nodeY={positionAbsoluteY} nodeW={w} nodeH={h} onResizeEnd={(next) => view.onNodeResize(id, next)} />
          <ResizeHandle corner="bl" nodeX={positionAbsoluteX} nodeY={positionAbsoluteY} nodeW={w} nodeH={h} onResizeEnd={(next) => view.onNodeResize(id, next)} />
          <ResizeHandle corner="br" nodeX={positionAbsoluteX} nodeY={positionAbsoluteY} nodeW={w} nodeH={h} onResizeEnd={(next) => view.onNodeResize(id, next)} />
        </>
      )}
    </div>
  );
};

interface BoundaryData {
  tag?: string;
  boundaryType?: string;
  width?: number;
  height?: number;
  ports?: RFPort[];
  [k: string]: unknown;
}

const BoundaryNode = ({ id, data, positionAbsoluteX, positionAbsoluteY, selected }: NodeProps) => {
  const d = data as unknown as BoundaryData;
  const view = useContext(ViewContext);
  const color = boundaryColor(d.boundaryType);
  const isInput = d.boundaryType?.includes('in');
  const isCross = d.boundaryType?.includes('cross');
  const portHandles = renderPortHandles(d.ports, color);
  const w = d.width ?? 60;
  const h = d.height ?? 24;
  const isAdjusting = view.adjustingNodeId === id;
  const isHighlighted = selected || isAdjusting;

  // 不同边界类型对应不同的渐变背景
  const gradBg = isCross
    ? (isInput ? 'var(--grad-cross-in)' : 'var(--grad-cross-out)')
    : (isInput ? 'var(--grad-bound-in)' : 'var(--grad-bound-out)');

  return (
    <div
      className={`relative flex items-center justify-center rounded-full border-2 px-2 py-0.5 text-center transition-all duration-200 ${isHighlighted ? 'anim-node-selected-glow' : ''}`}
      style={{
        minWidth: 50,
        minHeight: 24,
        width: w,
        height: h,
        borderColor: isAdjusting ? 'var(--accent)' : selected ? 'var(--orange)' : color,
        background: isHighlighted ? gradBg : `${color}18`,
        color,
        fontSize: 10,
        fontWeight: 600,
        fontFamily: 'var(--font-mono, monospace)',
        boxShadow: isAdjusting
          ? '0 0 0 3px rgba(37, 99, 235, 0.2), 0 3px 10px rgba(10,26,95,0.15)'
          : selected
          ? `0 0 0 3px rgba(234, 140, 12, 0.22), 0 3px 12px rgba(234,140,12,0.18)`
          : `0 1px 4px rgba(10,26,95,0.08), 0 0 0 1px ${color}0C inset`,
        transform: isHighlighted ? 'translateY(-1px) scale(1.02)' : 'translateY(0) scale(1)',
        backdropFilter: 'blur(2px)',
      }}
    >
      {portHandles ?? (
        <Handle
          type={isInput ? 'source' : 'target'}
          position={isInput ? Position.Right : Position.Left}
          style={{
            background: color,
            width: 9,
            height: 9,
            border: '2px solid #fff',
            boxShadow: '0 1px 3px rgba(10,26,95,0.2)',
          }}
        />
      )}
      <span className="truncate" style={{ maxWidth: 80, letterSpacing: '0.02em' }}>{d.tag || ''}</span>
      {isAdjusting && (
        <>
          <ResizeHandle corner="tl" nodeX={positionAbsoluteX} nodeY={positionAbsoluteY} nodeW={w} nodeH={h} onResizeEnd={(next) => view.onNodeResize(id, next)} />
          <ResizeHandle corner="tr" nodeX={positionAbsoluteX} nodeY={positionAbsoluteY} nodeW={w} nodeH={h} onResizeEnd={(next) => view.onNodeResize(id, next)} />
          <ResizeHandle corner="bl" nodeX={positionAbsoluteX} nodeY={positionAbsoluteY} nodeW={w} nodeH={h} onResizeEnd={(next) => view.onNodeResize(id, next)} />
          <ResizeHandle corner="br" nodeX={positionAbsoluteX} nodeY={positionAbsoluteY} nodeW={w} nodeH={h} onResizeEnd={(next) => view.onNodeResize(id, next)} />
        </>
      )}
    </div>
  );
};

/** 页面背景图节点（多页平铺时用）。opacity / contrast 由 ViewContext 控制。 */
const PageBgNode = ({ id, data }: NodeProps) => {
  const d = data as unknown as { url?: string; width?: number; height?: number };
  const view = useContext(ViewContext);
  const filter = view.bgEnhance ? 'contrast(1.3) brightness(1.05)' : undefined;
  const hovered = view.hoveredPageId === id;
  // 悬停视觉效果分离到独立覆盖层，避免对含大 PNG 的容器做过渡
  // 导致浏览器将其提升为合成层并重栅格化（出现"先模糊再变清晰"）。
  return (
    <div
      style={{
        width: d.width ?? 600,
        height: d.height ?? 800,
        position: 'relative',
        pointerEvents: 'auto',
        borderRadius: 8,
      }}
    >
      {d.url && (
        <img
          src={d.url}
          alt=""
          style={{
            width: '100%',
            height: '100%',
            objectFit: 'contain',
            opacity: view.bgOpacity,
            filter,
            pointerEvents: 'none',
          }}
          draggable={false}
        />
      )}
      {/* 悬停覆盖层：无 transition，避免合成层重栅格化导致 PNG 模糊 */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          borderRadius: 8,
          border: '2px solid',
          borderColor: hovered ? 'var(--accent)' : 'transparent',
          boxShadow: hovered ? '0 18px 40px rgba(0,0,0,0.35)' : '0 0 0 0 rgba(0,0,0,0)',
          pointerEvents: 'none',
        }}
      />
    </div>
  );
};

const nodeTypes = {
  equipment: EquipmentNode,
  boundary: BoundaryNode,
  pageBg: PageBgNode,
};

const edgeTypes = { editable: EditableEdge };

// ===================== 编辑器 =====================

export interface TopologyEditorHandle {
  /** 获取编辑后的 RF 节点/边（调用方做反归一化导出）。 */
  getEdited: () => { nodes: Node[]; edges: Edge[] };
  /** 重置画布数据（切换模式/重载时用）。 */
  reset: (nodes: Node[], edges: Edge[]) => void;
  /** 聚焦到指定节点（居中并缩放）。 */
  focusNode: (nodeId: string) => void;
}

export interface TopologyEditorProps {
  initialNodes: Node[];
  initialEdges: Edge[];
  readOnly?: boolean;
  /** 是否允许节点/边数据编辑（拖拽/连接/增删/右键）。只读界面时设为 false 可保留工具栏但锁定数据操作。 */
  editable?: boolean;
  className?: string;
  /** 属性面板可编辑字段定义（不同任务类型字段不同）。 */
  nodeFields?: EditableField[];
  edgeFields?: EditableField[];
  /** 数据变更回调（用于父组件感知 dirty）。 */
  onChange?: () => void;
  /** 节点双击回调（用于多页视图双击页面背景进入单页编辑）。 */
  onNodeDoubleClick?: (node: Node) => void;
  /**
   * 背景网格开关。
   * - undefined（默认）：渲染 Dots 背景（其它页面兼容行为）
   * - true：渲染 Lines 网格
   * - false：不渲染背景
   */
  showGrid?: boolean;
}

type Snapshot = { nodes: Node[]; edges: Edge[] };

function TopologyEditorInner(
  { initialNodes, initialEdges, readOnly = false, editable = true, className = '', nodeFields, edgeFields, onChange, onNodeDoubleClick, showGrid }: TopologyEditorProps,
  ref: React.Ref<TopologyEditorHandle>,
) {
  // 数据是否可编辑：readOnly 控制界面（工具栏/提示）是否显示，editable 控制节点/边数据操作。
  const canEdit = !readOnly && editable;
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);
  const rf = useReactFlow();

  // 选中元素
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);

  // 视图状态：背景透明度 / 管道线增强 / bbox 调整中节点
  const [bgOpacity, setBgOpacity] = useState(0.9);
  const [bgEnhance, setBgEnhance] = useState(false);
  const [adjustingNodeId, setAdjustingNodeId] = useState<string | null>(null);
  const [hoveredPageId, setHoveredPageId] = useState<string | null>(null);

  // 边逐条审核模式
  const [reviewing, setReviewing] = useState(false);
  const [reviewIndex, setReviewIndex] = useState(0);
  const [reconnecting, setReconnecting] = useState(false);

  // 手动补边模式（沿原图管道描绘折点）
  const [edgeAdding, setEdgeAdding] = useState(false);
  const [edgeAddSource, setEdgeAddSource] = useState<Node | null>(null);
  const [edgeAddBends, setEdgeAddBends] = useState<Array<{ x: number; y: number }>>([]);
  const [edgeAddMouse, setEdgeAddMouse] = useState<{ x: number; y: number } | null>(null);

  // Ctrl 连边模式状态
  const [linkingMode, setLinkingMode] = useState(false);
  const [linkingSource, setLinkingSource] = useState<Node | null>(null);
  const [linkingMouse, setLinkingMouse] = useState<{ x: number; y: number } | null>(null);

  // 快捷键帮助浮层（? 键唤起）
  const [showShortcuts, setShowShortcuts] = useState(false);

  // linkingMode 的同步 ref——避免 useEffect 时序问题导致 d3-drag 仍能启动
  const linkingModeRef = useRef(false);
  // linkingSource 的同步 ref——供 onNodeDragStop 读取最新值（避免闭包过期）
  const linkingSourceRef = useRef<Node | null>(linkingSource);
  linkingSourceRef.current = linkingSource;
  // 拖拽连边兜底：记录源节点拖拽前的原始位置
  const dragSourcePosRef = useRef<{ id: string; x: number; y: number } | null>(null);

  // 最新状态引用（供历史栈 commit 使用，避免闭包过期）
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  nodesRef.current = nodes;
  edgesRef.current = edges;

  const history = useHistory<Snapshot>({ nodes: initialNodes, edges: initialEdges });

  const commit = useCallback(() => {
    history.commit({ nodes: nodesRef.current, edges: edgesRef.current });
    onChange?.();
  }, [history, onChange]);

  // 重置历史当外部重置 initialNodes/edges 时（key 变化）
  const resetKey = useRef(`${initialNodes.length}-${initialEdges.length}`);
  useEffect(() => {
    const k = `${initialNodes.length}-${initialEdges.length}`;
    if (k !== resetKey.current) {
      resetKey.current = k;
      setNodes(initialNodes);
      setEdges(initialEdges);
      history.reset({ nodes: initialNodes, edges: initialEdges });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialNodes, initialEdges]);

  // 背景图异步加载完成后同步到已挂载的 pageBg 节点（不重建画布，保留用户编辑）
  useEffect(() => {
    setNodes((ns) => {
      let changed = false;
      const next = ns.map((n) => {
        if (n.type !== 'pageBg') return n;
        const init = initialNodes.find(
          (x) => x.id === n.id && x.type === 'pageBg',
        ) as Node | undefined;
        const nextUrl = (init?.data as { url?: string } | undefined)?.url;
        const curUrl = (n.data as { url?: string }).url;
        if (nextUrl && nextUrl !== curUrl) {
          changed = true;
          return { ...n, data: { ...n.data, url: nextUrl } };
        }
        return n;
      });
      return changed ? next : ns;
    });
  }, [initialNodes]);

  // 撤销/重做
  const applySnapshot = useCallback(
    (snap: Snapshot) => {
      setNodes(snap.nodes);
      setEdges(snap.edges);
      onChange?.();
    },
    [setNodes, setEdges, onChange],
  );
  const undo = useCallback(() => {
    const r = history.undo();
    if (r) applySnapshot(r);
  }, [history, applySnapshot]);
  const redo = useCallback(() => {
    const r = history.redo();
    if (r) applySnapshot(r);
  }, [history, applySnapshot]);

  // 节点拖拽开始：连边模式下记录源节点原始位置（兜底，防止 nodesDraggable 时序问题）
  const onNodeDragStart: NonNullable<ReactFlowProps['onNodeDragStart']> = useCallback(
    (_evt, node) => {
      if (linkingModeRef.current && node.type !== 'pageBg') {
        dragSourcePosRef.current = { id: node.id, x: node.position.x, y: node.position.y };
      } else {
        dragSourcePosRef.current = null;
      }
    },
    [],
  );

  // 节点拖拽结束：连边模式下查找目标节点并创建边，恢复源节点位置
  const onNodeDragStop: NonNullable<ReactFlowProps['onNodeDragStop']> = useCallback(
    (evt, node) => {
      // ReactFlow 事件可能是 MouseEvent | TouchEvent，此处仅处理鼠标场景
      // （触屏连边由原生 Handle 拖拽 onConnect 处理）
      const e = evt as MouseEvent;
      const dragInfo = dragSourcePosRef.current;
      dragSourcePosRef.current = null;

      if (linkingModeRef.current && dragInfo && dragInfo.id === node.id) {
        // 恢复源节点位置（拖拽中可能被移动了）
        setNodes((ns) =>
          ns.map((n) =>
            n.id === dragInfo.id ? { ...n, position: { x: dragInfo.x, y: dragInfo.y } } : n,
          ),
        );

        // 查找拖拽落点处的目标节点
        const el = document.elementFromPoint(e.clientX, e.clientY);
        const nodeEl = el?.closest('.react-flow__node') as HTMLElement | null;
        const targetId = nodeEl?.getAttribute('data-id');

        if (targetId && targetId !== node.id) {
          const targetNode = nodesRef.current.find((n) => n.id === targetId);
          if (targetNode && targetNode.type !== 'pageBg') {
            // 拖拽到目标节点 → 创建边（拖拽语义：拖拽的节点为源）
            const newEdge: Edge = {
              id: `e_ctrl_${Date.now()}`,
              source: node.id,
              target: targetId,
              sourceHandle: null,
              targetHandle: null,
              type: 'editable',
              data: {
                bendPoints: [],
                label: '',
                raw: { source_port_id: '', target_port_id: '' },
              },
            };
            setEdges((eds) => addEdge(newEdge, eds));
            // 拖拽连边后清空 click 选择，避免与后续 click 语义冲突
            setLinkingSource(null);
            setLinkingMouse(null);
            setTimeout(() => commit(), 0);
            return;
          }
        }

        // 没拖到目标节点 → 视为 click：处理 linkingSource（与 onNodeClick 语义一致）。
        // 场景：Ctrl 按下后 state linkingMode 异步未更新，d3-drag 仍启动，
        // 此时 onNodeClick 不会触发，需在此统一处理 click 语义，否则首次点击无法设源。
        const currentSource = linkingSourceRef.current;
        if (node.type === 'pageBg') {
          setLinkingSource(null);
          setLinkingMouse(null);
        } else if (!currentSource) {
          setLinkingSource(node);
          setLinkingMouse({ x: e.clientX, y: e.clientY });
        } else if (currentSource.id === node.id) {
          setLinkingSource(null);
          setLinkingMouse(null);
        } else {
          // 创建边（click 语义：已选源 → 当前节点）
          const newEdge: Edge = {
            id: `e_ctrl_${Date.now()}`,
            source: currentSource.id,
            target: node.id,
            sourceHandle: null,
            targetHandle: null,
            type: 'editable',
            data: {
              bendPoints: [],
              label: '',
              raw: { source_port_id: '', target_port_id: '' },
            },
          };
          setEdges((eds) => addEdge(newEdge, eds));
          setLinkingSource(null);
          setLinkingMouse(null);
          setTimeout(() => commit(), 0);
        }
        return;
      }

      commit();
    },
    [setNodes, setEdges, commit],
  );

  // 连接：添加边（拖拽端口连边时 sourceHandle/targetHandle 即 port.id，空即连接节点本身）
  const onConnect = useCallback(
    (conn: Connection) => {
      const newEdge: Edge = {
        ...conn,
        id: `e_new_${Date.now()}`,
        type: 'editable',
        data: {
          bendPoints: [],
          label: '',
          raw: {
            source_port_id: conn.sourceHandle ?? '',
            target_port_id: conn.targetHandle ?? '',
          },
        },
      };
      setEdges((eds) => addEdge(newEdge, eds));
      commit();
    },
    [setEdges, commit],
  );

  // ===== 边逐条审核模式 =====
  // 待审核边：非跨页边（_export.kind === 'inner'），按当前 edges 顺序
  const reviewEdges = useMemo(
    () => edges.filter((e) => (e.data as { _export?: { kind?: string } })?._export?.kind === 'inner'),
    [edges],
  );
  const currentReviewEdge = reviewing && reviewEdges[reviewIndex] ? reviewEdges[reviewIndex] : null;

  // 审核模式：切换到当前边时 fitView 到端点范围
  useEffect(() => {
    if (!reviewing || !currentReviewEdge) return;
    const e = currentReviewEdge;
    const src = nodesRef.current.find((n) => n.id === e.source);
    const tgt = nodesRef.current.find((n) => n.id === e.target);
    if (!src || !tgt) return;
    const sw = (src.measured?.width ?? (src.data as { width?: number }).width ?? 80) as number;
    const sh = (src.measured?.height ?? (src.data as { height?: number }).height ?? 32) as number;
    const tw = (tgt.measured?.width ?? (tgt.data as { width?: number }).width ?? 80) as number;
    const th = (tgt.measured?.height ?? (tgt.data as { height?: number }).height ?? 32) as number;
    const minX = Math.min(src.position.x, tgt.position.x) - 40;
    const minY = Math.min(src.position.y, tgt.position.y) - 40;
    const maxX = Math.max(src.position.x + sw, tgt.position.x + tw) + 40;
    const maxY = Math.max(src.position.y + sh, tgt.position.y + th) + 40;
    rf.fitBounds({ x: minX, y: minY, width: maxX - minX, height: maxY - minY }, { duration: 300 });
  }, [reviewing, currentReviewEdge, rf]);

  // 审核模式下：当前边高亮，其它边淡化；选中节点时：高亮该节点+连接边，其它淡化
  const displayEdges = useMemo(() => {
    if (reviewing && currentReviewEdge) {
      return edges.map((e) => {
        if (e.id === currentReviewEdge.id) {
          return { ...e, selected: true, style: { ...e.style, stroke: 'var(--orange)', strokeWidth: 3 } };
        }
        return { ...e, style: { ...e.style, opacity: 0.15 } };
      });
    }
    if (selectedNodeId && !linkingMode && !edgeAdding) {
      return edges.map((e) => {
        const isConnected = e.source === selectedNodeId || e.target === selectedNodeId;
        if (isConnected) {
          return { ...e, style: { ...e.style, stroke: 'var(--orange)', strokeWidth: 3, opacity: 1 } };
        }
        return { ...e, style: { ...e.style, opacity: 0.15 } };
      });
    }
    return edges;
  }, [edges, reviewing, currentReviewEdge, selectedNodeId, linkingMode, edgeAdding]);

  // 审核模式下：端点节点保持，其它非背景节点淡化；选中节点时同理
  const displayNodes = useMemo(() => {
    if (reviewing && currentReviewEdge) {
      return nodes.map((n) => {
        if (n.id === currentReviewEdge.source || n.id === currentReviewEdge.target) {
          return { ...n, style: { ...n.style } };
        }
        if (n.type === 'pageBg') return n;
        return { ...n, style: { ...n.style, opacity: 0.2 } };
      });
    }
    if (selectedNodeId && !linkingMode && !edgeAdding) {
      return nodes.map((n) => {
        if (n.id === selectedNodeId) {
          return { ...n, style: { ...n.style, opacity: 1 } };
        }
        if (n.type === 'pageBg') return n;
        return { ...n, style: { ...n.style, opacity: 0.2 } };
      });
    }
    return nodes;
  }, [nodes, reviewing, currentReviewEdge, selectedNodeId, linkingMode, edgeAdding]);

  // 审核模式：进入
  const enterReview = useCallback(() => {
    if (reviewEdges.length === 0) return;
    setReviewing(true);
    setReviewIndex(0);
    setReconnecting(false);
  }, [reviewEdges.length]);

  // 审核模式：退出
  const exitReview = useCallback(() => {
    setReviewing(false);
    setReconnecting(false);
  }, []);

  // 审核模式：下一条
  const reviewNext = useCallback(() => {
    setReviewIndex((i) => Math.min(i + 1, reviewEdges.length - 1));
    setReconnecting(false);
  }, [reviewEdges.length]);

  // 审核模式：上一条
  const reviewPrev = useCallback(() => {
    setReviewIndex((i) => Math.max(i - 1, 0));
    setReconnecting(false);
  }, []);

  // 审核模式：保留（等同跳过下一条）
  const reviewKeep = reviewNext;
  const reviewSkip = reviewNext;

  // 审核模式：删除当前边后下一条
  const reviewDelete = useCallback(() => {
    if (!currentReviewEdge) return;
    const e = currentReviewEdge;
    setEdges((es) => es.filter((x) => x.id !== e.id));
    setTimeout(() => {
      commit();
      // 删除后索引不增（后续边自动前移），但若已是末尾则回退
      setReviewIndex((i) => Math.min(i, Math.max(0, reviewEdges.length - 2)));
    }, 0);
  }, [currentReviewEdge, setEdges, commit, reviewEdges.length]);

  // 审核模式：重连（进入重连状态，用户用 ReactFlow 原生 onReconnect 拖拽端点）
  const reviewReconnect = useCallback(() => {
    setReconnecting(true);
    // 选中当前边以显示端点 handle（ReactFlow edgesReconnectable 已开启）
    if (currentReviewEdge) {
      setEdges((es) => es.map((x) => ({ ...x, selected: x.id === currentReviewEdge.id })));
    }
  }, [currentReviewEdge, setEdges]);

  // ===== 手动补边模式 =====
  const enterEdgeAdd = useCallback(() => {
    setEdgeAdding(true);
    setEdgeAddSource(null);
    setEdgeAddBends([]);
    setEdgeAddMouse(null);
  }, []);

  const exitEdgeAdd = useCallback(() => {
    setEdgeAdding(false);
    setEdgeAddSource(null);
    setEdgeAddBends([]);
    setEdgeAddMouse(null);
  }, []);

  const finishEdgeAdd = useCallback(
    (targetNode: Node) => {
      if (!edgeAddSource) return;
      const newEdge: Edge = {
        id: `e_add_${Date.now()}`,
        source: edgeAddSource.id,
        target: targetNode.id,
        sourceHandle: null,
        targetHandle: null,
        type: 'editable',
        data: {
          bendPoints: edgeAddBends,
          label: '',
          raw: { source_port_id: '', target_port_id: '' },
          _export: { kind: 'inner' as const, pageIndex: undefined },
        },
      };
      // 推断 pageIndex（从源节点 _export 取）
      const srcMeta = (edgeAddSource.data as { _export?: { pageIndex?: number } })?._export;
      if (srcMeta?.pageIndex != null) {
        (newEdge.data as { _export: { kind: string; pageIndex?: number } })._export.pageIndex = srcMeta.pageIndex;
      }
      setEdges((eds) => addEdge(newEdge, eds));
      exitEdgeAdd();
      setTimeout(() => commit(), 0);
    },
    [edgeAddSource, edgeAddBends, setEdges, exitEdgeAdd, commit],
  );

  // 端点重连：同步更新 raw.source_port_id/target_port_id（reconnectEdge 仅改 handle）
  const onReconnect = useCallback<OnReconnect>(
    (oldEdge, newConn) => {
      setEdges((eds) => {
        const updated = reconnectEdge(oldEdge, newConn, eds);
        return updated.map((e) => {
          if (e.id !== oldEdge.id) return e;
          const data = (e.data ?? {}) as { raw?: Record<string, unknown> };
          const raw = { ...(data.raw ?? {}) };
          raw.source_port_id = e.sourceHandle ?? '';
          raw.target_port_id = e.targetHandle ?? '';
          return { ...e, data: { ...data, raw } };
        });
      });
      commit();
      setReconnecting(false);
      // 重连后审核下一条
      if (reviewing) setTimeout(() => reviewNext(), 0);
    },
    [setEdges, commit, reviewing, reviewNext],
  );

  // 折点更新（来自 EditableEdge）
  const updateBends = useCallback<EdgeEditorContextValue['updateBends']>(
    (edgeId, bends, commitToHistory = true) => {
      setEdges((eds) =>
        eds.map((e) => (e.id === edgeId ? { ...e, data: { ...e.data, bendPoints: bends } } : e)),
      );
      if (commitToHistory) {
        // 延迟 commit 以拿到最新 edges
        setTimeout(() => commit(), 0);
      }
    },
    [setEdges, commit],
  );

  const edgeCtxValue = useMemo<EdgeEditorContextValue>(
    () => ({ readOnly: !canEdit, updateBends }),
    [canEdit, updateBends],
  );

  const onNodeResize = useCallback(
    (nodeId: string, next: { x: number; y: number; width: number; height: number }) => {
      setNodes((ns) =>
        ns.map((n) => {
          if (n.id !== nodeId) return n;
          const data = n.data as { width?: number; height?: number; raw?: Record<string, unknown>; _export?: { origW?: number; origH?: number; scaleX?: number; scaleY?: number } };
          // 同步反算 raw.bbox 归一化坐标（若原坐标系为归一化）
          const ex = data._export;
          let raw = data.raw;
          if (ex && ex.scaleX && ex.scaleY && data.raw) {
            const cxL = (next.x + next.width / 2) / ex.scaleX;
            const cyL = (next.y + next.height / 2) / ex.scaleY;
            const wL = next.width / ex.scaleX;
            const hL = next.height / ex.scaleY;
            // 仅当原 raw.bbox 是数组格式时才回写（保持原格式）；构造新数组而非 mutate 共享引用
            if (Array.isArray(data.raw.bbox)) {
              raw = {
                ...data.raw,
                bbox: [cxL - wL / 2, cyL - hL / 2, cxL + wL / 2, cyL + hL / 2],
              };
            }
          }
          return {
            ...n,
            position: { x: next.x, y: next.y },
            data: { ...n.data, width: next.width, height: next.height, ...(raw !== data.raw ? { raw } : {}) },
          };
        }),
      );
      setTimeout(() => commit(), 0);
    },
    [setNodes, commit],
  );

  const viewCtxValue = useMemo<ViewContextValue>(
    () => ({ bgOpacity, bgEnhance, adjustingNodeId, hoveredPageId, onNodeResize }),
    [bgOpacity, bgEnhance, adjustingNodeId, hoveredPageId, onNodeResize],
  );

  // 默认边样式：终点箭头指示方向（source -> target）
  const defaultEdgeOptions = useMemo(
    () => ({
      markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: 'var(--accent)' },
    }),
    [],
  );

  // 选中变化
  const onSelectionChange = useCallback(
    ({ nodes: selNodes, edges: selEdges }: { nodes: Node[]; edges: Edge[] }) => {
      setSelectedNodeId(selNodes.length > 0 ? selNodes[0].id : null);
      setSelectedEdgeId(selEdges.length > 0 ? selEdges[0].id : null);
    },
    [],
  );

  // 删除选中（Delete 键触发，无确认）
  const deleteSelected = useCallback(() => {
    const selNodes = nodesRef.current.filter((n) => n.selected && n.type !== 'pageBg');
    const selEdges = edgesRef.current.filter((e) => e.selected);
    if (selNodes.length === 0 && selEdges.length === 0) return;
    const nodeIds = new Set(selNodes.map((n) => n.id));
    // pageBg 永远保留，只删除选中的非背景节点
    setNodes((ns) => ns.filter((n) => n.type === 'pageBg' || !n.selected));
    setEdges((es) =>
      es.filter((e) => !e.selected && !nodeIds.has(e.source) && !nodeIds.has(e.target)),
    );
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
    setTimeout(() => commit(), 0);
  }, [setNodes, setEdges, commit]);

  // 删除指定节点（属性面板按钮触发，带 confirm + 连带边提示）
  const deleteNodeById = useCallback(
    (nodeId: string) => {
      const n = nodesRef.current.find((x) => x.id === nodeId);
      if (!n || n.type === 'pageBg') return;
      const affected = edgesRef.current.filter((e) => e.source === nodeId || e.target === nodeId);
      const label = (n.data as { tag?: string }).tag ?? nodeId;
      if (affected.length > 0) {
        if (!window.confirm(`删除节点 "${label}" 将连带删除 ${affected.length} 条边，确认？`)) return;
      } else if (!window.confirm(`删除节点 "${label}"？`)) return;
      setNodes((ns) => ns.filter((x) => x.id !== nodeId));
      setEdges((es) => es.filter((e) => e.source !== nodeId && e.target !== nodeId));
      setSelectedNodeId(null);
      setSelectedEdgeId(null);
      setTimeout(() => commit(), 0);
    },
    [setNodes, setEdges, commit],
  );

  // 删除指定边（属性面板按钮触发，带 confirm）
  const deleteEdgeById = useCallback(
    (edgeId: string) => {
      const e = edgesRef.current.find((x) => x.id === edgeId);
      if (!e) return;
      if (!window.confirm(`删除边 "${edgeId}"？\n(${e.source} → ${e.target})`)) return;
      setEdges((es) => es.filter((x) => x.id !== edgeId));
      setSelectedEdgeId(null);
      setTimeout(() => commit(), 0);
    },
    [setEdges, commit],
  );

  // 反转边方向（交换 source/target，折点逆序）
  const reverseEdge = useCallback(
    (edgeId: string) => {
      const e = edgesRef.current.find((x) => x.id === edgeId);
      if (!e) return;
      if (!window.confirm(`反转边方向 "${edgeId}"？\n(${e.source} → ${e.target}) 改为 (${e.target} → ${e.source})`)) return;
      setEdges((es) =>
        es.map((x) => {
          if (x.id !== edgeId) return x;
          const data = (x.data ?? {}) as { bendPoints?: Array<{ x: number; y: number }> };
          const bends = data.bendPoints ? [...data.bendPoints].reverse() : data.bendPoints;
          return { ...x, source: x.target, target: x.source, data: { ...data, bendPoints: bends } };
        }),
      );
      setTimeout(() => commit(), 0);
    },
    [setEdges, commit],
  );

  // 在指定 flow 坐标添加节点（右键菜单触发）
  const addNodeAt = useCallback(
    (type: 'equipment' | 'boundary', flowPos: { x: number; y: number }) => {
      const id = `n_new_${Date.now()}`;
      const w = type === 'equipment' ? 80 : 60;
      const h = type === 'equipment' ? 32 : 24;
      // 从同页现有节点推导导出 meta：无 meta 的新节点在 rfToPfdPage 导出时会被跳过（静默丢失）
      const ref = nodesRef.current.find(
        (n) => n.type !== 'pageBg' && (n.data as { _export?: unknown })._export,
      );
      const refMeta = (ref?.data as { _export?: { pageIndex?: number; scaleX?: number; scaleY?: number } } | undefined)?._export;
      const scaleX = refMeta?.scaleX || 1;
      const scaleY = refMeta?.scaleY || 1;
      const node: Node = {
        id,
        type,
        position: { x: flowPos.x - w / 2, y: flowPos.y - h / 2 },
        data: {
          tag: type === 'equipment' ? '新设备' : '新边界',
          nodeType: type,
          boundaryType: type === 'boundary' ? 'boundary_in' : undefined,
          width: w,
          height: h,
          raw: {
            id,
            tag: type === 'equipment' ? '新设备' : undefined,
            label: type === 'boundary' ? '新边界' : undefined,
            node_type: type,
            boundary_type: type === 'boundary' ? 'boundary_in' : undefined,
          },
          ...(refMeta
            ? {
                _export: {
                  ...refMeta,
                  // local 空间原始尺寸 = flow 尺寸 / scale（归一化页得到 [0,1] 小数）
                  origW: w / scaleX,
                  origH: h / scaleY,
                },
              }
            : {}),
        },
        draggable: true,
      };
      setNodes((ns) => [...ns, node]);
      setSelectedNodeId(id);
      setTimeout(() => commit(), 0);
    },
    [setNodes, commit],
  );

  // 右键菜单
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; flowX: number; flowY: number } | null>(null);
  const onPaneContextMenu = useCallback<NonNullable<ReactFlowProps['onPaneContextMenu']>>(
    (e) => {
      if (!canEdit) return;
      e.preventDefault();
      setNodeContextMenu(null);
      const flowPos = rf.screenToFlowPosition({ x: e.clientX, y: e.clientY });
      setContextMenu({ x: e.clientX, y: e.clientY, flowX: flowPos.x, flowY: flowPos.y });
    },
    [rf, canEdit],
  );
  const closeContextMenu = useCallback(() => setContextMenu(null), []);

  // 节点右键菜单（添加端口）
  const [nodeContextMenu, setNodeContextMenu] = useState<{ x: number; y: number; nodeId: string } | null>(null);
  const onNodeContextMenu = useCallback<NonNullable<ReactFlowProps['onNodeContextMenu']>>(
    (e, node) => {
      if (!canEdit) return;
      if (node.type === 'pageBg') return;
      e.preventDefault();
      setContextMenu(null);
      setNodeContextMenu({ x: e.clientX, y: e.clientY, nodeId: node.id });
    },
    [canEdit],
  );
  const closeNodeContextMenu = useCallback(() => setNodeContextMenu(null), []);

  // 添加节点（在视口中心）
  const addNode = useCallback(
    (type: 'equipment' | 'boundary') => {
      const center = rf.getViewport().zoom
        ? rf.screenToFlowPosition({ x: window.innerWidth / 2, y: window.innerHeight / 2 })
        : { x: 100, y: 100 };
      const id = `n_new_${Date.now()}`;
      const node: Node = {
        id,
        type,
        position: { x: center.x - 40, y: center.y - 16 },
        data: {
          tag: type === 'equipment' ? '新设备' : '新边界',
          nodeType: type,
          boundaryType: type === 'boundary' ? 'boundary_in' : undefined,
          width: type === 'equipment' ? 80 : 60,
          height: type === 'equipment' ? 32 : 24,
          raw: {
            id,
            tag: type === 'equipment' ? '新设备' : undefined,
            label: type === 'boundary' ? '新边界' : undefined,
            node_type: type,
            boundary_type: type === 'boundary' ? 'boundary_in' : undefined,
          },
        },
        draggable: true,
      };
      setNodes((ns) => [...ns, node]);
      setTimeout(() => commit(), 0);
    },
    [rf, setNodes, commit],
  );

  // 属性面板更新（仅 patch data；raw 字段映射由 denormalize 在导出时统一处理，
  // 因为 data 字段名与 raw 字段名不一致，如 label vs material_name）
  const updateNodeData = useCallback(
    (nodeId: string, patch: Record<string, unknown>) => {
      setNodes((ns) => ns.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ...patch } } : n)));
      setTimeout(() => commit(), 0);
    },
    [setNodes, commit],
  );
  const updateEdgeData = useCallback(
    (edgeId: string, patch: Record<string, unknown>) => {
      setEdges((es) => es.map((e) => (e.id === edgeId ? { ...e, data: { ...e.data, ...patch } } : e)));
      setTimeout(() => commit(), 0);
    },
    [setEdges, commit],
  );

  // 添加端口（属性面板「+端口」按钮 / 节点右键菜单触发）：追加到 data.ports 与 data.raw.ports
  const addPort = useCallback(
    (nodeId: string, direction: RFPort['direction'] = 'unknown') => {
      const node = nodesRef.current.find((n) => n.id === nodeId);
      if (!node) return;
      const data = node.data as { ports?: RFPort[]; raw?: Record<string, unknown> };
      const existing = data.ports ?? [];
      const newPort: RFPort = {
        id: `port_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`,
        direction,
        orientation: direction === 'input' ? 'left' : direction === 'output' ? 'right' : 'left',
        label: '',
      };
      const newPorts = [...existing, newPort];
      const raw = { ...(data.raw ?? {}), ports: newPorts.map(toRawPort) };
      setNodes((ns) =>
        ns.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ports: newPorts, raw } } : n)),
      );
      setTimeout(() => commit(), 0);
    },
    [setNodes, commit],
  );

  // 更新端口字段（direction/orientation/label）
  const updatePort = useCallback(
    (nodeId: string, portId: string, patch: Partial<RFPort>) => {
      const node = nodesRef.current.find((n) => n.id === nodeId);
      if (!node) return;
      const data = node.data as { ports?: RFPort[]; raw?: Record<string, unknown> };
      const existing = data.ports ?? [];
      const newPorts = existing.map((p) => (p.id === portId ? { ...p, ...patch } : p));
      const raw = { ...(data.raw ?? {}), ports: newPorts.map(toRawPort) };
      setNodes((ns) =>
        ns.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ports: newPorts, raw } } : n)),
      );
      setTimeout(() => commit(), 0);
    },
    [setNodes, commit],
  );

  // 删除端口 + 连带删除引用该 port.id 的边（sourceHandle/targetHandle 匹配）
  const deletePort = useCallback(
    (nodeId: string, portId: string) => {
      const node = nodesRef.current.find((n) => n.id === nodeId);
      if (!node) return;
      const data = node.data as { ports?: RFPort[]; raw?: Record<string, unknown> };
      const existing = data.ports ?? [];
      const affected = edgesRef.current.filter(
        (e) =>
          (e.source === nodeId && e.sourceHandle === portId) ||
          (e.target === nodeId && e.targetHandle === portId),
      );
      if (affected.length > 0) {
        if (!window.confirm(`删除端口 "${portId}" 将连带删除 ${affected.length} 条引用该端口的边，确认？`)) return;
      }
      const newPorts = existing.filter((p) => p.id !== portId);
      const raw = { ...(data.raw ?? {}), ports: newPorts.map(toRawPort) };
      setNodes((ns) =>
        ns.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ports: newPorts, raw } } : n)),
      );
      if (affected.length > 0) {
        setEdges((es) =>
          es.filter(
            (e) =>
              !(
                (e.source === nodeId && e.sourceHandle === portId) ||
                (e.target === nodeId && e.targetHandle === portId)
              ),
          ),
        );
      }
      setTimeout(() => commit(), 0);
    },
    [setNodes, setEdges, commit],
  );

  // Ctrl 连边：监听 Ctrl 按下/松开
  useEffect(() => {
    if (!canEdit) return;
    const isInput = (t: EventTarget | null) => {
      const el = t as HTMLElement | null;
      return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && linkingSource) {
        setLinkingSource(null);
        setLinkingMouse(null);
        return;
      }
      if (e.key === 'Control' && !e.repeat && !isInput(e.target)) {
        linkingModeRef.current = true;
        setLinkingMode(true);
      }
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.key === 'Control') {
        linkingModeRef.current = false;
        setLinkingMode(false);
        setLinkingSource(null);
        setLinkingMouse(null);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
    };
  }, [canEdit, linkingSource]);

  // Ctrl 连边：跟随鼠标更新临时边终点（屏幕坐标）
  useEffect(() => {
    if (!linkingSource) return;
    const onMove = (e: MouseEvent) => {
      setLinkingMouse({ x: e.clientX, y: e.clientY });
    };
    window.addEventListener('mousemove', onMove);
    return () => window.removeEventListener('mousemove', onMove);
  }, [linkingSource]);

  // 补边模式：跟随鼠标更新临时虚线终点（屏幕坐标）
  useEffect(() => {
    if (!edgeAdding || !edgeAddSource) return;
    const onMove = (e: MouseEvent) => {
      setEdgeAddMouse({ x: e.clientX, y: e.clientY });
    };
    window.addEventListener('mousemove', onMove);
    return () => window.removeEventListener('mousemove', onMove);
  }, [edgeAdding, edgeAddSource]);

  // 双击节点：equipment/boundary 进入 bbox 调整模式；pageBg 透传给外部回调（全局->单页）
  const handleNodeDoubleClick = useCallback<NonNullable<ReactFlowProps['onNodeDoubleClick']>>(
    (evt, node) => {
      if (!canEdit) {
        onNodeDoubleClick?.(node);
        return;
      }
      if (node.type === 'equipment' || node.type === 'boundary') {
        evt.stopPropagation();
        setAdjustingNodeId((cur) => (cur === node.id ? null : node.id));
        return;
      }
      onNodeDoubleClick?.(node);
    },
    [canEdit, onNodeDoubleClick],
  );

  // Ctrl 连边：点击节点（用 ref 判断模式，避免 state 异步导致首次点击被忽略）
  const onNodeClick = useCallback<NonNullable<ReactFlowProps['onNodeClick']>>(
    (_evt, node) => {
      // 补边模式：分支处理
      if (edgeAdding) {
        if (node.type === 'pageBg') {
          exitEdgeAdd();
          return;
        }
        if (!edgeAddSource) {
          setEdgeAddSource(node);
          return;
        }
        if (node.id === edgeAddSource.id) {
          exitEdgeAdd();
          return;
        }
        // 点击目标节点 -> 完成
        finishEdgeAdd(node);
        return;
      }
      // 非连边模式下点击页面背景 -> 清除选中（收起属性面板）
      if (!linkingModeRef.current && node.type === 'pageBg') {
        setSelectedNodeId(null);
        setSelectedEdgeId(null);
        return;
      }
      // Ctrl 连边模式（原有逻辑）
      if (!linkingModeRef.current) return;
      if (node.type === 'pageBg') {
        // 点页面背景视为取消
        setLinkingSource(null);
        setLinkingMouse(null);
        return;
      }
      if (!linkingSource) {
        setLinkingSource(node);
        return;
      }
      if (linkingSource.id === node.id) {
        // 点同一个节点 → 取消
        setLinkingSource(null);
        setLinkingMouse(null);
        return;
      }
      // 第二次点击：创建边（sourceHandle/targetHandle = null，port_id 为空串）
      const newEdge: Edge = {
        id: `e_ctrl_${Date.now()}`,
        source: linkingSource.id,
        target: node.id,
        sourceHandle: null,
        targetHandle: null,
        type: 'editable',
        data: {
          bendPoints: [],
          label: '',
          raw: { source_port_id: '', target_port_id: '' },
        },
      };
      setEdges((eds) => addEdge(newEdge, eds));
      setLinkingSource(null);
      setLinkingMouse(null);
      setTimeout(() => commit(), 0);
    },
    [edgeAdding, edgeAddSource, exitEdgeAdd, finishEdgeAdd, linkingModeRef, linkingSource, setEdges, commit],
  );

  // Ctrl 连边：点空白取消
  const onPaneClick = useCallback<NonNullable<ReactFlowProps['onPaneClick']>>((evt) => {
    // 补边模式：点空白添加折点
    if (edgeAdding && edgeAddSource) {
      const flowPos = rf.screenToFlowPosition({ x: evt.clientX, y: evt.clientY });
      setEdgeAddBends((bs) => [...bs, flowPos]);
      return;
    }
    if (adjustingNodeId) {
      setAdjustingNodeId(null);
      return;
    }
    if (linkingSource) {
      setLinkingSource(null);
      setLinkingMouse(null);
    }
  }, [edgeAdding, edgeAddSource, adjustingNodeId, linkingSource, rf]);

  // 键盘快捷键（在所有 callback 定义之后注册，避免 TDZ）
  useEffect(() => {
    if (!canEdit) return;
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !e.shiftKey) {
        e.preventDefault();
        undo();
      } else if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'y' || (e.key.toLowerCase() === 'z' && e.shiftKey))) {
        e.preventDefault();
        redo();
      } else if (edgeAdding && e.key === 'Escape') {
        e.preventDefault();
        exitEdgeAdd();
        return;
      } else if (reviewing) {
        if (e.key === 'ArrowLeft') { e.preventDefault(); reviewPrev(); return; }
        if (e.key === 'ArrowRight') { e.preventDefault(); reviewNext(); return; }
        if (e.key === 'Escape') { e.preventDefault(); exitReview(); return; }
        if (e.key === 'Delete' && currentReviewEdge) { e.preventDefault(); reviewDelete(); return; }
      } else if (e.key === 'Escape' && adjustingNodeId) {
        e.preventDefault();
        setAdjustingNodeId(null);
        return;
      } else if ((e.key === 'Delete' || e.key === 'Backspace') && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        deleteSelected();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [undo, redo, deleteSelected, canEdit, adjustingNodeId, reviewing, reviewPrev, reviewNext, exitReview, reviewDelete, currentReviewEdge, edgeAdding, exitEdgeAdd]);

  // ? 键唤起/关闭快捷键浮层（任意模式下可用，INPUT/TEXTAREA 中忽略）
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === '?' && !e.ctrlKey && !e.metaKey) {
        const target = e.target as HTMLElement;
        if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) return;
        e.preventDefault();
        setShowShortcuts((v) => !v);
      } else if (e.key === 'Escape' && showShortcuts) {
        setShowShortcuts(false);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [showShortcuts]);

  // 暴露 API
  useImperativeHandle(
    ref,
    (): TopologyEditorHandle => ({
      getEdited: () => ({ nodes: nodesRef.current, edges: edgesRef.current }),
      reset: (ns, es) => {
        setNodes(ns);
        setEdges(es);
        history.reset({ nodes: ns, edges: es });
        setSelectedNodeId(null);
        setSelectedEdgeId(null);
      },
      focusNode: (nodeId: string) => {
        const node = nodesRef.current.find((n) => n.id === nodeId);
        if (node) {
          const w = node.measured?.width ?? 100;
          const h = node.measured?.height ?? 50;
          rf.setCenter(node.position.x + w / 2, node.position.y + h / 2, { zoom: 1.2, duration: 300 });
          setSelectedNodeId(nodeId);
        }
      },
    }),
    [setNodes, setEdges, history, rf, setSelectedNodeId],
  );

  const selectedNode = selectedNodeId ? nodes.find((n) => n.id === selectedNodeId) ?? null : null;
  const selectedEdge = selectedEdgeId ? edges.find((e) => e.id === selectedEdgeId) ?? null : null;

  return (
    <ViewContext.Provider value={viewCtxValue}>
    <EdgeEditorContext.Provider value={edgeCtxValue}>
      <div
        className={`relative h-full w-full ${className}`}
        style={linkingMode ? { cursor: 'crosshair' } : undefined}
      >
        {linkingMode && (
          <style>{`.react-flow__pane{cursor:crosshair !important;}`}</style>
        )}
        <ReactFlow
          nodes={displayNodes}
          edges={displayEdges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeDragStart={canEdit ? onNodeDragStart : undefined}
          onNodeDragStop={onNodeDragStop}
          onConnect={canEdit ? onConnect : undefined}
          onReconnect={canEdit ? onReconnect : undefined}
          onSelectionChange={onSelectionChange}
          onNodeClick={canEdit ? onNodeClick : undefined}
          onPaneClick={canEdit ? onPaneClick : undefined}
          onNodeMouseEnter={(_, node) => {
            // 仅全局视图（不可编辑）时高亮所在页；单页编辑模式不触发悬停动效
            if (canEdit) return;
            const pageId = pageIdFromNodeId(node.id);
            if (pageId) setHoveredPageId(pageId);
          }}
          onNodeMouseLeave={() => setHoveredPageId(null)}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          defaultEdgeOptions={defaultEdgeOptions}
          connectionMode={ConnectionMode.Loose}
          nodesDraggable={canEdit && !linkingMode && !reviewing && !edgeAdding}
          nodesConnectable={canEdit}
          edgesReconnectable={canEdit}
          elementsSelectable={canEdit}
          zoomOnDoubleClick={false}
          fitView
          fitViewOptions={{ padding: 0.1 }}
          minZoom={0.05}
          maxZoom={3}
          proOptions={{ hideAttribution: true }}
          deleteKeyCode={null}
          onPaneContextMenu={canEdit ? onPaneContextMenu : undefined}
          onNodeContextMenu={canEdit ? onNodeContextMenu : undefined}
          onNodeDoubleClick={handleNodeDoubleClick}
        >
          {showGrid === false ? null : (
            <Background
              variant={showGrid === true ? BackgroundVariant.Lines : BackgroundVariant.Dots}
              color={'var(--border)'}
              gap={20}
              size={1}
            />
          )}
          <Controls
            className="!rounded-xl !border !border-border/80 !bg-bg-2/85 !backdrop-blur !shadow-card-strong overflow-hidden"
            showInteractive={false}
          />
          <MiniMap
            pannable
            zoomable
            className="!rounded-xl !border !border-border/80 !bg-bg-2/85 !backdrop-blur !shadow-card-strong overflow-hidden"
            style={{ width: 140, height: 92, borderRadius: 12 }}
            maskColor="rgba(15,23,42,0.55)"
            nodeStrokeColor="rgba(255,255,255,0.7)"
            nodeStrokeWidth={1.5}
            nodeColor={(n) => {
              if (n.type === 'boundary') return boundaryColor((n.data as { boundaryType?: string }).boundaryType);
              if (n.type === 'pageBg') return 'rgba(148,163,184,0.2)';
              return EQUIPMENT_COLOR;
            }}
          />
        </ReactFlow>

        {/* 浮动工具栏 */}
        {!readOnly && (
          <div className="glass-panel anim-slide-up-fade absolute left-3 top-3 z-10 flex items-center gap-1 rounded-xl border border-border/80 p-1.5 shadow-card-strong">
            <div className="flex items-center gap-0.5 pr-1">
              <ToolbarBtn title="撤销 (Ctrl+Z)" disabled={!canEdit || !history.canUndo} onClick={undo} icon>↶</ToolbarBtn>
              <ToolbarBtn title="重做 (Ctrl+Y)" disabled={!canEdit || !history.canRedo} onClick={redo} icon>↷</ToolbarBtn>
            </div>
            <Divider />
            <div className="flex items-center gap-0.5 px-0.5">
              <ToolbarBtn title="添加设备节点" onClick={() => addNode('equipment')} disabled={!canEdit}>＋设备</ToolbarBtn>
              <ToolbarBtn title="添加边界节点" onClick={() => addNode('boundary')} disabled={!canEdit}>＋边界</ToolbarBtn>
            </div>
            <Divider />
            <div className="flex items-center gap-0.5 px-0.5">
              <ToolbarBtn title="删除选中 (Delete)" onClick={deleteSelected} danger icon disabled={!canEdit}>🗑</ToolbarBtn>
              <ToolbarBtn title="适配视图到全部" onClick={() => rf.fitView({ padding: 0.12, duration: 300 })} icon>⊡</ToolbarBtn>
            </div>
            <Divider />
            <div className="flex items-center gap-0.5 pl-0.5">
              <ToolbarBtn
                title={`逐条审核边（共 ${reviewEdges.length} 条待审）`}
                disabled={!canEdit || reviewEdges.length === 0}
                onClick={enterReview}
                badge={reviewEdges.length > 0 ? reviewEdges.length : undefined}
              >
                审边
              </ToolbarBtn>
              <ToolbarBtn title="补边（沿原图管道描绘折点）" onClick={enterEdgeAdd} disabled={!canEdit}>补边</ToolbarBtn>
            </div>
            <Divider />
            {/* 视图控制：背景透明度 + 增强管道线（并入顶部工具栏，不单独容器） */}
            <div className="flex items-center gap-3 pl-1">
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-text3 font-medium whitespace-nowrap">背景透明度</span>
                <input
                  type="range"
                  min={0.3}
                  max={1}
                  step={0.05}
                  value={bgOpacity}
                  onChange={(e) => setBgOpacity(parseFloat(e.target.value))}
                  className="nice-range w-24"
                  title={`背景透明度 ${Math.round(bgOpacity * 100)}%`}
                />
                <span className="text-[10px] font-mono text-accent font-semibold">{Math.round(bgOpacity * 100)}%</span>
              </div>
              <button
                type="button"
                onClick={() => setBgEnhance((v) => !v)}
                title="高亮管线（对比原图管道走向）"
                className={`flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-medium border transition ${
                  bgEnhance
                    ? 'border-accent/50 bg-accent/10 text-accent'
                    : 'border-border/60 text-text-2 hover:bg-bg-3/70'
                }`}
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 12h6l3-7 3 14 3-7h1" />
                </svg>
                高亮管线
              </button>
            </div>
          </div>
        )}

        {/* 属性面板 */}
        {!readOnly && canEdit && (selectedNode || selectedEdge) && (
          <div className="anim-fade-in-scale absolute bottom-3 right-3 top-3 z-10 w-[280px]">
            <PropertyPanel
              node={selectedNode}
              edge={selectedEdge}
              nodeFields={nodeFields}
              edgeFields={edgeFields}
              onUpdateNode={updateNodeData}
              onUpdateEdge={updateEdgeData}
              onDeleteNode={deleteNodeById}
              onDeleteEdge={deleteEdgeById}
              onReverseEdge={reverseEdge}
              onAddPort={addPort}
              onUpdatePort={updatePort}
              onDeletePort={deletePort}
              onJumpNode={(id: string) => {
                const node = nodesRef.current.find((n) => n.id === id);
                if (node) {
                  const w = node.measured?.width ?? 100;
                  const h = node.measured?.height ?? 50;
                  rf.setCenter(node.position.x + w / 2, node.position.y + h / 2, { zoom: 1.2, duration: 300 });
                  setSelectedNodeId(id);
                }
              }}
            />
          </div>
        )}

        {/* 右键菜单：画布添加节点 */}
        {!readOnly && contextMenu && (
          <>
            {/* 透明遮罩关闭菜单 */}
            <div className="fixed inset-0 z-20" onClick={closeContextMenu} onContextMenu={(e) => { e.preventDefault(); closeContextMenu(); }} />
            <div
              className="anim-fade-in-scale fixed z-30 min-w-48 rounded-xl border border-border/80 bg-bg-2/95 p-1.5 shadow-card-strong backdrop-blur-md"
              style={{ left: contextMenu.x, top: contextMenu.y }}
            >
              <div className="mb-1 px-2 py-1 text-[10px] font-semibold text-text-3 uppercase tracking-wider">画布操作</div>
              <button
                type="button"
                onClick={() => {
                  addNodeAt('equipment', { x: contextMenu.flowX, y: contextMenu.flowY });
                  closeContextMenu();
                }}
                className="group flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[12px] text-text transition hover:bg-accent hover:text-white"
              >
                <span className="flex h-6 w-6 items-center justify-center rounded-md border border-accent/40 bg-accent/10 text-accent group-hover:bg-white/20 group-hover:border-white/30 group-hover:text-white transition">
                  <span className="text-sm leading-none">▭</span>
                </span>
                <div className="flex flex-col">
                  <span className="font-medium">添加设备节点</span>
                  <span className="text-[10px] text-text-3 group-hover:text-white/70">矩形 · 代表工艺设备</span>
                </div>
              </button>
              <button
                type="button"
                onClick={() => {
                  addNodeAt('boundary', { x: contextMenu.flowX, y: contextMenu.flowY });
                  closeContextMenu();
                }}
                className="group flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[12px] text-text transition hover:bg-accent hover:text-white"
              >
                <span className="flex h-6 w-6 items-center justify-center rounded-full border border-green/40 bg-green/10 text-green group-hover:bg-white/20 group-hover:border-white/30 group-hover:text-white transition">
                  <span className="text-sm leading-none">◉</span>
                </span>
                <div className="flex flex-col">
                  <span className="font-medium">添加边界节点</span>
                  <span className="text-[10px] text-text-3 group-hover:text-white/70">圆形 · 代表输入/输出</span>
                </div>
              </button>
            </div>
          </>
        )}

        {/* 右键菜单：节点添加端口 */}
        {!readOnly && nodeContextMenu && (
          <>
            <div className="fixed inset-0 z-20" onClick={closeNodeContextMenu} onContextMenu={(e) => { e.preventDefault(); closeNodeContextMenu(); }} />
            <div
              className="anim-fade-in-scale fixed z-30 min-w-48 rounded-xl border border-border/80 bg-bg-2/95 p-1.5 shadow-card-strong backdrop-blur-md"
              style={{ left: nodeContextMenu.x, top: nodeContextMenu.y }}
            >
              <div className="mb-1 px-2 py-1 text-[10px] font-semibold text-text-3 uppercase tracking-wider">节点端口</div>
              <button
                type="button"
                onClick={() => {
                  addPort(nodeContextMenu.nodeId, 'input');
                  closeNodeContextMenu();
                }}
                className="group flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[12px] text-text transition hover:bg-green hover:text-white"
              >
                <span className="flex h-6 w-6 items-center justify-center rounded-md border border-green/40 bg-green/10 text-green group-hover:bg-white/20 group-hover:border-white/30 group-hover:text-white transition">
                  ←
                </span>
                <div className="flex flex-col">
                  <span className="font-medium">添加输入端口</span>
                  <span className="text-[10px] text-text-3 group-hover:text-white/70">物料/能量入口</span>
                </div>
              </button>
              <button
                type="button"
                onClick={() => {
                  addPort(nodeContextMenu.nodeId, 'output');
                  closeNodeContextMenu();
                }}
                className="group flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[12px] text-text transition hover:bg-orange hover:text-white"
              >
                <span className="flex h-6 w-6 items-center justify-center rounded-md border border-orange/40 bg-orange/10 text-orange group-hover:bg-white/20 group-hover:border-white/30 group-hover:text-white transition">
                  →
                </span>
                <div className="flex flex-col">
                  <span className="font-medium">添加输出端口</span>
                  <span className="text-[10px] text-text-3 group-hover:text-white/70">物料/能量出口</span>
                </div>
              </button>
            </div>
          </>
        )}

        {/* 操作提示（始终显示底部） */}
        {!readOnly && !reviewing && !edgeAdding && !linkingMode && (
          <div className="pointer-events-none absolute bottom-3 left-1/2 z-10 -translate-x-1/2">
            <div className="anim-slide-up-fade glass-panel rounded-xl border border-border/70 px-4 py-2 text-[11px] text-text-2 shadow-card">
              <div className="flex items-center gap-x-3 gap-y-1 flex-wrap justify-center">
                <Hint icon="🖱" label="右键" desc="添加节点" />
                <HintDivider />
                <Hint icon="👆" label="双击节点" desc="调整尺寸" />
                <HintDivider />
                <Hint icon="〰" label="双击边" desc="加折点" />
                <HintDivider />
                <Hint icon="⇌" label="拖端点" desc="重连" />
                <HintDivider />
                <Hint icon="Ctrl" label="Ctrl+点" desc="连边" />
                <HintDivider />
                <Hint icon="?" label="?" desc="快捷键" />
              </div>
            </div>
          </div>
        )}

        {/* 边逐条审核浮动栏 */}
        {!readOnly && reviewing && currentReviewEdge && (
          <EdgeReviewBar
            edges={reviewEdges}
            nodes={nodes}
            index={reviewIndex}
            reconnecting={reconnecting}
            onKeep={reviewKeep}
            onDelete={reviewDelete}
            onReconnect={reviewReconnect}
            onSkip={reviewSkip}
            onPrev={reviewPrev}
            onNext={reviewNext}
            onExit={exitReview}
          />
        )}

        {/* 补边模式：浮动提示 */}
        {!readOnly && edgeAdding && (
          <div className="anim-slide-up-fade absolute left-1/2 top-3 z-20 -translate-x-1/2 pointer-events-none">
            <div className="flex items-center gap-2 rounded-xl border border-cyan/50 bg-gradient-to-r from-cyan/15 via-cyan/10 to-cyan/15 px-4 py-2 text-[12px] text-cyan shadow-card-strong backdrop-blur-md">
              <span className="relative flex h-2.5 w-2.5 shrink-0">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-cyan opacity-75" />
                <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-cyan" />
              </span>
              {edgeAddSource
                ? (
                  <span className="font-medium">
                    补边模式：源 <span className="font-mono bg-white/20 rounded px-1.5 py-0.5">{(edgeAddSource.data as { tag?: string }).tag || edgeAddSource.id}</span>
                    <span className="mx-1 opacity-70">→</span>
                    点空白加折点，点目标完成
                    <span className="ml-2 text-cyan-2/80 text-[11px]">（Esc 取消 · 已加 {edgeAddBends.length} 折点）</span>
                  </span>
                )
                : <span className="font-medium">补边模式：点击源节点开始（Esc 取消）</span>}
            </div>
          </div>
        )}

        {/* 补边模式：跟随鼠标的临时虚线 */}
        {!readOnly && edgeAdding && edgeAddSource && edgeAddMouse && (() => {
          const srcData = (edgeAddSource.data ?? {}) as { width?: number; height?: number };
          const w = srcData.width ?? 80;
          const h = srcData.height ?? 32;
          const srcFlow = {
            x: edgeAddSource.position.x + w / 2,
            y: edgeAddSource.position.y + h / 2,
          };
          const srcScreen = rf.flowToScreenPosition(srcFlow);
          const bendScreens = edgeAddBends.map((b) => rf.flowToScreenPosition(b));
          const pts = [srcScreen, ...bendScreens, edgeAddMouse];
          const d = pts.map((p, i) => (i === 0 ? `M${p.x},${p.y}` : `L${p.x},${p.y}`)).join(' ');
          return (
            <svg
              className="pointer-events-none fixed inset-0 z-30"
              style={{ width: '100vw', height: '100vh' }}
            >
              <defs>
                <filter id="edgeAddGlow" x="-50%" y="-50%" width="200%" height="200%">
                  <feGaussianBlur stdDeviation="3" result="b" />
                  <feMerge>
                    <feMergeNode in="b" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
              </defs>
              <path
                d={d}
                fill="none"
                stroke="var(--cyan)"
                strokeWidth={3}
                strokeDasharray="7 4"
                filter="url(#edgeAddGlow)"
                style={{ animation: 'dash-flow 0.8s linear infinite' }}
              />
              {bendScreens.map((p, i) => (
                <g key={i}>
                  <circle cx={p.x} cy={p.y} r={8} fill="var(--cyan)" fillOpacity={0.15} />
                  <circle cx={p.x} cy={p.y} r={5} fill="var(--cyan)" stroke="#fff" strokeWidth={2} />
                </g>
              ))}
              <g>
                <circle cx={srcScreen.x} cy={srcScreen.y} r={9} fill="var(--green)" fillOpacity={0.18} />
                <circle cx={srcScreen.x} cy={srcScreen.y} r={6} fill="var(--green)" stroke="#fff" strokeWidth={2} />
              </g>
              <circle cx={edgeAddMouse.x} cy={edgeAddMouse.y} r={4.5} fill="var(--cyan)" stroke="#fff" strokeWidth={1.5} opacity={0.9} />
            </svg>
          );
        })()}

        {/* Ctrl 连边模式：顶部提示 + 跟随鼠标的临时边 */}
        {!readOnly && linkingMode && (
          <div className="anim-slide-up-fade absolute left-1/2 top-3 z-20 -translate-x-1/2 pointer-events-none">
            <div className="flex items-center gap-2 rounded-xl border border-orange/50 bg-gradient-to-r from-orange/15 via-orange/10 to-orange/15 px-4 py-2 text-[12px] text-orange shadow-card-strong backdrop-blur-md">
              <span className="relative flex h-2.5 w-2.5 shrink-0">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-orange opacity-75" />
                <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-orange" />
              </span>
              {linkingSource
                ? (
                  <span className="font-medium">
                    连线模式：源 <span className="font-mono bg-white/20 rounded px-1.5 py-0.5">{(linkingSource.data as { tag?: string }).tag || linkingSource.id}</span>
                    <span className="mx-1 opacity-70">→</span>
                    点击目标节点完成
                    <span className="ml-2 text-orange-2/80 text-[11px]">（Esc/松开 Ctrl 取消）</span>
                  </span>
                )
                : <span className="font-medium">连线模式：按住 Ctrl，依次点击源 → 目标节点（松开 Ctrl 取消）</span>}
            </div>
          </div>
        )}
        {!readOnly && linkingSource && linkingMouse && (() => {
          const srcData = (linkingSource.data ?? {}) as { width?: number; height?: number };
          const w = srcData.width ?? 80;
          const h = srcData.height ?? 32;
          const srcFlow = {
            x: linkingSource.position.x + w / 2,
            y: linkingSource.position.y + h / 2,
          };
          const srcScreen = rf.flowToScreenPosition(srcFlow);
          return (
            <svg
              className="pointer-events-none fixed inset-0 z-30"
              style={{ width: '100vw', height: '100vh' }}
            >
              <defs>
                <filter id="linkGlow" x="-50%" y="-50%" width="200%" height="200%">
                  <feGaussianBlur stdDeviation="2.5" result="b" />
                  <feMerge>
                    <feMergeNode in="b" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
              </defs>
              <g filter="url(#linkGlow)">
                <line
                  x1={srcScreen.x}
                  y1={srcScreen.y}
                  x2={linkingMouse.x}
                  y2={linkingMouse.y}
                  stroke="var(--orange)"
                  strokeWidth={2.5}
                  strokeDasharray="6 4"
                  style={{ animation: 'dash-flow 0.7s linear infinite' }}
                />
              </g>
              <g>
                <circle cx={srcScreen.x} cy={srcScreen.y} r={9} fill="var(--orange)" fillOpacity={0.18} />
                <circle cx={srcScreen.x} cy={srcScreen.y} r={6} fill="var(--orange)" stroke="#fff" strokeWidth={2} />
              </g>
              <circle cx={linkingMouse.x} cy={linkingMouse.y} r={5} fill="var(--orange)" stroke="#fff" strokeWidth={1.5} opacity={0.95} />
            </svg>
          );
        })()}

        {/* 快捷键浮层（? 键唤起） */}
        {showShortcuts && (
          <div
            className="anim-fade-in-scale fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-sm"
            onClick={() => setShowShortcuts(false)}
          >
            <div
              className="glass-panel w-[420px] rounded-2xl border border-border/80 bg-bg-2/98 p-5 shadow-card-strong"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="mb-4 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-accent to-purple text-white text-sm font-bold shadow">⌨</span>
                  <h4 className="text-base font-bold text-text">快捷键列表</h4>
                </div>
                <button
                  type="button"
                  className="flex h-8 w-8 items-center justify-center rounded-lg text-text-3 hover:bg-bg-3 hover:text-text transition"
                  onClick={() => setShowShortcuts(false)}
                  title="关闭 (Esc)"
                >
                  ✕
                </button>
              </div>

              <div className="space-y-4">
                <ShortcutGroup title="通用操作">
                  <ShortcutRow label="撤销" keys={['Ctrl', 'Z']} />
                  <ShortcutRow label="重做" keys={['Ctrl', 'Y']} />
                  <ShortcutRow label="删除选中" keys={['Delete']} />
                  <ShortcutRow label="显示此帮助" keys={['?']} />
                </ShortcutGroup>

                <ShortcutGroup title="连接与编辑">
                  <ShortcutRow label="快速连边（点源→点目标）" keys={['Ctrl + 点击']} />
                  <ShortcutRow label="选中边后加折点" keys={['双击边']} />
                  <ShortcutRow label="调整节点 bbox 尺寸" keys={['双击节点']} />
                  <ShortcutRow label="拖拽边端点重连" keys={['拖端点']} />
                </ShortcutGroup>

                <ShortcutGroup title="审核模式">
                  <ShortcutRow label="上一条 / 下一条" keys={['←', '→']} />
                  <ShortcutRow label="保留当前边" keys={['Enter']} />
                  <ShortcutRow label="删除当前边" keys={['Delete']} />
                  <ShortcutRow label="退出审核" keys={['Esc']} />
                </ShortcutGroup>
              </div>

              <div className="mt-4 pt-3 border-t border-border/60 text-center text-[11px] text-text-3">
                按 <kbd className="rounded bg-bg-3 px-1.5 py-0.5 font-mono text-[10px] mx-0.5">?</kbd> 或 <kbd className="rounded bg-bg-3 px-1.5 py-0.5 font-mono text-[10px] mx-0.5">Esc</kbd> 关闭
              </div>
            </div>
          </div>
        )}
      </div>
    </EdgeEditorContext.Provider>
    </ViewContext.Provider>
  );
}

function ToolbarBtn({
  children,
  onClick,
  disabled,
  title,
  icon,
  accent,
  danger,
  badge,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  title?: string;
  icon?: boolean;
  accent?: boolean;
  danger?: boolean;
  badge?: number;
}) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={`relative flex ${icon ? 'h-8 w-8' : 'h-8'} min-w-8 items-center justify-center ${icon ? '' : 'px-2.5'} rounded-lg text-[12px] font-medium transition-all duration-150 disabled:opacity-35 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-text-3 disabled:hover:shadow-none disabled:hover:translate-y-0
        ${danger
          ? 'text-text-2 hover:bg-red/15 hover:text-red hover:shadow-[0_2px_8px_rgba(220,38,38,0.2)] hover:-translate-y-0.5'
          : accent
          ? 'text-text-2 hover:bg-accent hover:text-white hover:shadow-[0_2px_10px_rgba(37,99,235,0.3)] hover:-translate-y-0.5 active:translate-y-0'
          : 'text-text-2 hover:bg-accent/10 hover:text-accent hover:-translate-y-0.5 active:translate-y-0'
        }`}
    >
      {children}
      {badge != null && (
        <span className="absolute -top-1 -right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-gradient-to-br from-orange to-red px-1 text-[9.5px] font-bold text-white shadow-md ring-1 ring-white/40">
          {badge > 99 ? '99+' : badge}
        </span>
      )}
    </button>
  );
}

/* ========== 工具栏分隔符 ========== */
function Divider() {
  return <span className="mx-0.5 h-5 w-px bg-gradient-to-b from-transparent via-border/70 to-transparent" />;
}

/* ========== 底部操作提示 Hint ========== */
function Hint({ icon, label, desc }: { icon: string; label: string; desc: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <kbd className="inline-flex items-center rounded-md border border-border/70 bg-bg-3/80 px-1.5 py-0.5 font-mono text-[10px] text-text shadow-sm">
        {icon} {label}
      </kbd>
      <span className="text-text-3">{desc}</span>
    </span>
  );
}
function HintDivider() {
  return <span className="text-border/60">·</span>;
}

/* ========== 快捷键浮层辅助组件 ========== */
function ShortcutGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <span className="h-3 w-1 rounded-full bg-gradient-to-b from-accent to-purple" />
        <h5 className="text-[11px] font-bold text-text-3 uppercase tracking-[0.08em]">{title}</h5>
      </div>
      <div className="space-y-1.5 pl-3">{children}</div>
    </div>
  );
}
function ShortcutRow({ label, keys }: { label: string; keys: string[] }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 hover:bg-bg-3/50 transition">
      <span className="text-[12px] text-text-2">{label}</span>
      <div className="flex items-center gap-1">
        {keys.map((k, i) => (
          <span key={i} className="flex items-center gap-1">
            {i > 0 && <span className="text-text-3 text-[10px]">+</span>}
            <kbd className="min-w-[24px] text-center rounded-md border border-border/70 bg-bg-3 px-1.5 py-0.5 font-mono text-[10px] text-text shadow-inner">
              {k}
            </kbd>
          </span>
        ))}
      </div>
    </div>
  );
}

const TopologyEditorForwarded = forwardRef(TopologyEditorInner);

export const TopologyEditor = forwardRef<TopologyEditorHandle, TopologyEditorProps>(
  function TopologyEditor(props, ref) {
    return (
      <ReactFlowProvider>
        <TopologyEditorForwarded ref={ref} {...props} />
      </ReactFlowProvider>
    );
  },
);

// 重新导出工具类型供调用方使用
export type { Node as RFNode, Edge as RFEdge } from '@xyflow/react';
export type { NodeChange, EdgeChange };
