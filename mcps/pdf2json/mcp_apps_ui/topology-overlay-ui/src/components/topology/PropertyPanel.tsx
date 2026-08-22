/**
 * 属性面板：编辑选中节点/边的字段。
 *
 * 优化点：
 *   - 可折叠的详情区
 *   - 关闭按钮
 *   - 清晰 section 划分
 *   - 更好的端口编辑器卡片
 *   - 边 source/target 可点击跳转
 *   - 精致的表单样式
 */

import { memo, type ReactNode, useState } from 'react';
import type { Node, Edge } from '@xyflow/react';
import type { RFPort } from './topologyAdapters';

export interface EditableField {
  /** data 上的字段名（同时写回 raw）。 */
  key: string;
  label: string;
  type: 'text' | 'select' | 'checkbox';
  options?: string[];
}

/** PFD 拓扑节点可编辑字段。 */
export const PFD_NODE_FIELDS: EditableField[] = [
  { key: 'tag', label: '位号 tag', type: 'text' },
  { key: 'nodeType', label: '节点类型', type: 'select', options: ['equipment', 'boundary'] },
  { key: 'boundaryType', label: '边界类型', type: 'select', options: ['boundary_in', 'boundary_out', 'cross_drawing_in', 'cross_drawing_out'] },
  { key: 'inferred', label: '推断节点', type: 'checkbox' },
];

/** PFD 拓扑边可编辑字段。 */
export const PFD_EDGE_FIELDS: EditableField[] = [
  { key: 'label', label: '物料名称', type: 'text' },
];

/** 装置拓扑节点可编辑字段。 */
export const PLANT_UNIT_NODE_FIELDS: EditableField[] = [
  { key: 'tag', label: '名称', type: 'text' },
  { key: 'layer', label: '层级 layer', type: 'text' },
];

/** 装置拓扑边可编辑字段。 */
export const PLANT_UNIT_EDGE_FIELDS: EditableField[] = [
  { key: 'label', label: '物料名称', type: 'text' },
];

export interface PropertyPanelProps {
  node: Node | null;
  edge: Edge | null;
  nodeFields?: EditableField[];
  edgeFields?: EditableField[];
  onUpdateNode: (nodeId: string, patch: Record<string, unknown>) => void;
  onUpdateEdge: (edgeId: string, patch: Record<string, unknown>) => void;
  onDeleteNode?: (nodeId: string) => void;
  onDeleteEdge?: (edgeId: string) => void;
  onReverseEdge?: (edgeId: string) => void;
  onAddPort?: (nodeId: string) => void;
  onUpdatePort?: (nodeId: string, portId: string, patch: Partial<RFPort>) => void;
  onDeletePort?: (nodeId: string, portId: string) => void;
  /** 点击跳转节点（边source/target） */
  onJumpNode?: (nodeId: string) => void;
  /** 关闭面板按钮 */
  onClose?: () => void;
}

function PropertyPanelInner({
  node,
  edge,
  nodeFields = PFD_NODE_FIELDS,
  edgeFields = PFD_EDGE_FIELDS,
  onUpdateNode,
  onUpdateEdge,
  onDeleteNode,
  onDeleteEdge,
  onReverseEdge,
  onAddPort,
  onUpdatePort,
  onDeletePort,
  onJumpNode,
  onClose,
}: PropertyPanelProps) {
  const [detailOpen, setDetailOpen] = useState(true);
  const [portsOpen, setPortsOpen] = useState(true);

  if (node) {
    const data = (node.data ?? {}) as Record<string, unknown>;
    const isBoundary = node.type === 'boundary';
    const isEquipment = node.type === 'equipment';
    const raw = (data.raw ?? {}) as Record<string, unknown>;
    const metadata = raw.metadata as Record<string, unknown> | undefined;
    const color = isBoundary
      ? ((node.data as { boundaryType?: string }).boundaryType?.includes('out') ? 'orange' : 'green')
      : 'accent';
    const headerTitle = isEquipment ? '设备节点' : isBoundary ? '边界节点' : '节点属性';

    return (
      <div className="glass-panel anim-fade-in-scale flex max-h-full flex-col rounded-lg overflow-hidden">
        {/* 头部 */}
        <PanelHeader title={headerTitle} id={node.id} color={color} onClose={onClose} />

        <div className="thin-scroll overflow-y-auto px-3 pb-3 pt-2">
          {/* 可编辑字段区 */}
          {nodeFields
            .filter((f) => f.key !== 'boundaryType' || isBoundary)
            .map((f) => (
              <FieldRow
                key={f.key}
                field={f}
                value={data[f.key]}
                onChange={(v) => onUpdateNode(node.id, { [f.key]: v })}
              />
            ))}

          {/* 位置信息 */}
          <div className="pp-section">
            <div className="pp-section-title">
              <span>位置信息</span>
            </div>
            <div className="grid grid-cols-2 gap-2 text-[11px] font-mono">
              <InfoCell label="X" value={Math.round(node.position.x)} />
              <InfoCell label="Y" value={Math.round(node.position.y)} />
              {typeof data.width === 'number' && <InfoCell label="宽" value={Math.round(data.width)} />}
              {typeof data.height === 'number' && <InfoCell label="高" value={Math.round(data.height)} />}
            </div>
          </div>

          {/* 只读详情（可折叠） */}
          <CollapsibleSection
            title="原始详情"
            open={detailOpen}
            onToggle={() => setDetailOpen((v) => !v)}
            count={
              [
                !isBoundary && raw.equipment_type,
                raw.bbox != null,
                raw.position != null,
                metadata && Object.keys(metadata).length > 0,
              ].filter(Boolean).length
            }
          >
            <ReadOnlyDetails
              entries={[
                !isBoundary ? { label: '设备类型', value: raw.equipment_type as string | undefined } : null,
                { label: 'bbox', value: raw.bbox != null ? fmtCoord(raw.bbox) : undefined },
                { label: '原始位置', value: raw.position != null ? fmtCoord(raw.position) : undefined },
                metadata && Object.keys(metadata).length > 0
                  ? { label: 'metadata', value: JSON.stringify(metadata) }
                  : null,
              ]}
            />
          </CollapsibleSection>

          {/* 端口编辑器（可折叠） */}
          {isEquipment || isBoundary ? (
            <CollapsibleSection
              title="端口"
              open={portsOpen}
              onToggle={() => setPortsOpen((v) => !v)}
              count={Array.isArray(data.ports) ? (data.ports as unknown[]).length : 0}
            >
              <PortListEditor
                ports={data.ports}
                readOnly={!onAddPort || !onUpdatePort || !onDeletePort}
                onAdd={() => onAddPort?.(node.id)}
                onUpdatePort={(portId, patch) => onUpdatePort?.(node.id, portId, patch)}
                onDeletePort={(portId) => onDeletePort?.(node.id, portId)}
              />
            </CollapsibleSection>
          ) : null}

          {/* 删除按钮 */}
          {onDeleteNode && node.type !== 'pageBg' && (
            <div className="pp-section">
              <button
                type="button"
                onClick={() => onDeleteNode(node.id)}
                className="w-full flex items-center justify-center gap-1.5 rounded-lg border border-red/30 bg-red/5 py-2 text-[12px] font-medium text-red transition hover:bg-red hover:text-white hover:border-red"
              >
                <span>🗑</span> 删除该节点
              </button>
            </div>
          )}
        </div>
      </div>
    );
  }

  if (edge) {
    const data = (edge.data ?? {}) as Record<string, unknown>;
    const raw = (data.raw ?? {}) as Record<string, unknown>;
    const cond = raw.condition as Record<string, unknown> | undefined;
    const bendCount = ((data.bendPoints as unknown[]) ?? []).length;

    return (
      <div className="glass-panel anim-fade-in-scale flex max-h-full flex-col rounded-lg overflow-hidden">
        <PanelHeader title="流股连接" id={edge.id} color="accent" onClose={onClose} />

        <div className="thin-scroll overflow-y-auto px-3 pb-3 pt-2">
          {/* Source / Target 跳转卡片 */}
          <div className="mb-3 flex flex-col gap-2">
            <EndpointChip
              label="源节点"
              nodeId={edge.source}
              tag={(edge.source?.toString?.() ?? edge.source) as string}
              onClick={() => onJumpNode?.(edge.source)}
              color="green"
            />
            <div className="flex justify-center">
              <div className="text-accent text-[12px]">↓ 流向</div>
            </div>
            <EndpointChip
              label="目标节点"
              nodeId={edge.target}
              tag={(edge.target?.toString?.() ?? edge.target) as string}
              onClick={() => onJumpNode?.(edge.target)}
              color="orange"
            />
          </div>

          {/* 可编辑字段 */}
          {edgeFields.map((f) => (
            <FieldRow
              key={f.key}
              field={f}
              value={data[f.key]}
              onChange={(v) => onUpdateEdge(edge.id, { [f.key]: v })}
            />
          ))}

          {/* 边信息 */}
          <div className="pp-section">
            <div className="pp-section-title">
              <span>边信息</span>
            </div>
            <div className="grid grid-cols-2 gap-2 text-[11px] font-mono">
              <InfoCell label="折点数" value={bendCount} />
              {typeof (data._export as { kind?: string } | undefined)?.kind === 'string' && (
                <InfoCell
                  label="类型"
                  value={(data._export as { kind: string }).kind === 'cross' ? '跨页边' : '页内边'}
                />
              )}
            </div>
          </div>

          {/* 只读详情 */}
          <CollapsibleSection
            title="详细参数"
            open={detailOpen}
            onToggle={() => setDetailOpen((v) => !v)}
            count={
              [
                raw.stream_number, raw.medium, raw.source_port_id, raw.target_port_id,
                cond?.temperature, cond?.pressure, cond?.mass_flow, cond?.volume_flow, cond?.mole_flow, cond?.phase,
              ].filter(Boolean).length
            }
          >
            <ReadOnlyDetails
              entries={[
                { label: '流股号', value: (raw.stream_number as string | undefined) || undefined },
                { label: '介质', value: (raw.medium as string | undefined) || undefined },
                { label: '源端口', value: (raw.source_port_id as string | undefined) || '（节点）' },
                { label: '目标端口', value: (raw.target_port_id as string | undefined) || '（节点）' },
                cond?.temperature != null ? { label: '温度', value: String(cond.temperature) } : null,
                cond?.pressure != null ? { label: '压力', value: String(cond.pressure) } : null,
                cond?.mass_flow != null ? { label: '质量流量', value: String(cond.mass_flow) } : null,
                cond?.volume_flow != null ? { label: '体积流量', value: String(cond.volume_flow) } : null,
                cond?.mole_flow != null ? { label: '摩尔流量', value: String(cond.mole_flow) } : null,
                cond?.phase ? { label: '相态', value: String(cond.phase) } : null,
              ]}
            />
          </CollapsibleSection>

          {/* 操作按钮 */}
          <div className="pp-section flex flex-col gap-2">
            {onReverseEdge && (
              <button
                type="button"
                onClick={() => onReverseEdge(edge.id)}
                className="w-full flex items-center justify-center gap-1.5 rounded-lg border border-accent/30 bg-accent/5 py-2 text-[12px] font-medium text-accent transition hover:bg-accent hover:text-white hover:border-accent"
              >
                <span>⇄</span> 反转边方向
              </button>
            )}
            {onDeleteEdge && (
              <button
                type="button"
                onClick={() => onDeleteEdge(edge.id)}
                className="w-full flex items-center justify-center gap-1.5 rounded-lg border border-red/30 bg-red/5 py-2 text-[12px] font-medium text-red transition hover:bg-red hover:text-white hover:border-red"
              >
                <span>🗑</span> 删除该边
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }
  return null;
}

/* ============ 子组件 ============ */

function PanelHeader({
  title,
  id,
  color = 'accent',
  onClose,
}: {
  title: string;
  id: string;
  color?: 'accent' | 'green' | 'orange' | 'purple' | 'cyan';
  onClose?: () => void;
}) {
  const colorDot: Record<string, string> = {
    accent: 'bg-accent',
    green: 'bg-green',
    orange: 'bg-orange',
    purple: 'bg-purple',
    cyan: 'bg-cyan',
  };
  return (
    <div className="flex items-center justify-between border-b border-border px-3 py-2.5 bg-bg3/40">
      <div className="flex items-center gap-2">
        <span className={`inline-block w-2 h-2 rounded-full ${colorDot[color] ?? colorDot.accent} shadow-sm`} />
        <span className="text-[12px] font-bold text-text">{title}</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="rounded bg-bg2 px-1.5 py-0.5 font-mono text-[9px] text-text3 border border-border">
          {id}
        </span>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            title="关闭面板 (Esc)"
            className="w-6 h-6 flex items-center justify-center rounded hover:bg-bg-3/70 text-text3 hover:text-text transition"
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
}

function FieldRow({
  field,
  value,
  onChange,
}: {
  field: EditableField;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  return (
    <label className="pp-field">
      <span className="pp-field-label">{field.label}</span>
      {field.type === 'text' && (
        <input
          type="text"
          className="pp-input"
          value={value == null ? '' : String(value)}
          onChange={(e) => onChange(e.target.value)}
          placeholder={`输入${field.label}`}
        />
      )}
      {field.type === 'select' && (
        <select
          className="pp-select"
          value={value == null ? '' : String(value)}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">（未选择）</option>
          {field.options?.map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>
      )}
      {field.type === 'checkbox' && (
        <label className="flex items-center gap-2 py-1 cursor-pointer select-none">
          <input
            type="checkbox"
            className="nice-checkbox"
            checked={Boolean(value)}
            onChange={(e) => onChange(e.target.checked)}
          />
          <span className="text-[11px] text-text2">
            {Boolean(value) ? '已启用' : '未启用'}
          </span>
        </label>
      )}
    </label>
  );
}

function InfoCell({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-center justify-between rounded bg-bg3/60 px-2 py-1">
      <span className="text-[9px] uppercase tracking-wider text-text3">{label}</span>
      <span className="text-[11px] text-text">{value}</span>
    </div>
  );
}

function EndpointChip({
  label,
  nodeId: _nodeId,
  tag,
  onClick,
  color,
}: {
  label: string;
  nodeId: string;
  tag: string;
  onClick?: () => void;
  color: 'green' | 'orange';
}) {
  const bg = color === 'green' ? 'bg-green/10 border-green/30 hover:bg-green/15' : 'bg-orange/10 border-orange/30 hover:bg-orange/15';
  const text = color === 'green' ? 'text-green' : 'text-orange';
  const dot = color === 'green' ? 'bg-green' : 'bg-orange';
  return (
    <div
      className={`flex items-center justify-between rounded-lg border ${bg} px-2.5 py-1.5 cursor-pointer transition group`}
      onClick={onClick}
    >
      <div className="flex items-center gap-2">
        <span className={`w-1.5 h-1.5 rounded-full ${dot}`} />
        <span className="text-[10px] text-text3">{label}</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className={`font-mono text-[11px] font-semibold ${text}`}>{tag}</span>
        {onClick && (
          <span className="text-[10px] text-text3 opacity-0 group-hover:opacity-100 transition">
            ⤴ 定位
          </span>
        )}
      </div>
    </div>
  );
}

function CollapsibleSection({
  title,
  open,
  onToggle,
  count,
  children,
}: {
  title: string;
  open: boolean;
  onToggle: () => void;
  count?: number;
  children: ReactNode;
}) {
  return (
    <div className="pp-section">
      <button
        type="button"
        className="w-full pp-section-title cursor-pointer select-none group hover:bg-bg3/30 -mx-1 px-1 rounded transition"
        onClick={onToggle}
      >
        <span className="flex items-center gap-1.5">
          <span
            className="inline-block transition-transform text-text3 group-hover:text-accent"
            style={{ transform: open ? 'rotate(90deg)' : 'rotate(0deg)' }}
          >
            ▶
          </span>
          {title}
          {typeof count === 'number' && (
            <span className="rounded bg-bg3 px-1.5 text-[9px] font-semibold text-text3">
              {count}
            </span>
          )}
        </span>
        <span className="text-[9px] text-text3 group-hover:text-accent">
          {open ? '收起' : '展开'}
        </span>
      </button>
      {open && <div className="anim-slide-up-fade mt-1">{children}</div>}
    </div>
  );
}

function ReadOnlyDetails({ entries }: { entries: Array<{ label: string; value: ReactNode | undefined } | null> }) {
  const visible = entries.filter(
    (e): e is { label: string; value: ReactNode | undefined } =>
      e !== null && e.value != null && e.value !== '',
  );
  if (visible.length === 0) {
    return <div className="text-[10px] text-text3 italic px-1">— 无数据 —</div>;
  }
  return (
    <div className="flex flex-col gap-1">
      {visible.map((e, i) => (
        <div key={i} className="flex items-start gap-2 rounded bg-bg3/40 px-2 py-1.5">
          <span className="w-20 shrink-0 text-[10px] font-medium text-text3">{e.label}</span>
          <span className="break-all text-[11px] text-text2 flex-1">{e.value}</span>
        </div>
      ))}
    </div>
  );
}

function PortListEditor({
  ports,
  readOnly,
  onAdd,
  onUpdatePort,
  onDeletePort,
}: {
  ports: unknown;
  readOnly?: boolean;
  onAdd?: () => void;
  onUpdatePort?: (portId: string, patch: Partial<RFPort>) => void;
  onDeletePort?: (portId: string) => void;
}) {
  const list: RFPort[] = Array.isArray(ports)
    ? (ports as Array<Record<string, unknown>>)
        .map((p) => ({
          id: String(p.id ?? ''),
          direction: (p.direction as RFPort['direction']) ?? 'unknown',
          orientation: (p.orientation as RFPort['orientation']) ?? 'unknown',
          label: p.label != null ? String(p.label) : undefined,
        }))
        .filter((p) => p.id !== '')
    : [];
  return (
    <div className="flex flex-col gap-1.5">
      {!readOnly && onAdd && (
        <button
          type="button"
          onClick={onAdd}
          className="w-full flex items-center justify-center gap-1.5 rounded-lg border-2 border-dashed border-border py-1.5 text-[11px] text-text3 hover:text-accent hover:border-accent/50 hover:bg-accent/5 transition"
        >
          <span className="text-sm">+</span> 添加端口
        </button>
      )}
      {list.length === 0 && readOnly && (
        <div className="text-[10px] text-text3 italic text-center py-2">未定义端口</div>
      )}
      {list.map((p) => {
        const colorChip =
          p.direction === 'input'
            ? 'bg-green/80'
            : p.direction === 'output'
            ? 'bg-orange/80'
            : 'bg-text3/60';
        return (
          <div key={p.id} className="port-card">
            <div className="flex items-center gap-2 mb-1.5">
              <span className={`inline-block w-2 h-2 rounded-full ${colorChip}`} />
              <span className="rounded bg-bg3 px-1.5 py-0.5 font-mono text-[9px] text-text2 flex-1 truncate">
                {p.id}
              </span>
              {!readOnly && onDeletePort && (
                <button
                  type="button"
                  onClick={() => onDeletePort(p.id)}
                  title="删除端口"
                  className="w-5 h-5 flex items-center justify-center rounded text-[11px] text-text3 hover:bg-red/10 hover:text-red transition"
                >
                  ✕
                </button>
              )}
            </div>
            {!readOnly && onUpdatePort ? (
              <div className="grid grid-cols-2 gap-x-2 gap-y-1">
                <label className="flex items-center gap-1 text-[9px] text-text3 col-span-1">
                  <span className="w-8 shrink-0">方向</span>
                  <select
                    className="flex-1 rounded border border-border bg-bg px-1 py-0.5 text-[10px] text-text outline-none focus:border-accent"
                    value={p.direction}
                    onChange={(e) =>
                      onUpdatePort(p.id, { direction: e.target.value as RFPort['direction'] })
                    }
                  >
                    <option value="unknown">?</option>
                    <option value="input">入</option>
                    <option value="output">出</option>
                  </select>
                </label>
                <label className="flex items-center gap-1 text-[9px] text-text3 col-span-1">
                  <span className="w-8 shrink-0">朝向</span>
                  <select
                    className="flex-1 rounded border border-border bg-bg px-1 py-0.5 text-[10px] text-text outline-none focus:border-accent"
                    value={p.orientation}
                    onChange={(e) =>
                      onUpdatePort(p.id, { orientation: e.target.value as RFPort['orientation'] })
                    }
                  >
                    <option value="unknown">?</option>
                    <option value="left">←</option>
                    <option value="right">→</option>
                    <option value="top">↑</option>
                    <option value="bottom">↓</option>
                  </select>
                </label>
                <label className="flex items-center gap-1 text-[9px] text-text3 col-span-2">
                  <span className="w-8 shrink-0">标签</span>
                  <input
                    type="text"
                    className="flex-1 rounded border border-border bg-bg px-1.5 py-0.5 text-[10px] text-text outline-none focus:border-accent"
                    value={p.label ?? ''}
                    placeholder="端口描述..."
                    onChange={(e) => onUpdatePort(p.id, { label: e.target.value })}
                  />
                </label>
              </div>
            ) : (
              <div className="text-[9px] text-text3">
                {p.direction} · {p.orientation}
                {p.label ? ' · ' + p.label : ''}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** 格式化坐标数组为可读字符串。 */
function fmtCoord(v: unknown): string {
  if (Array.isArray(v))
    return `[${(v as number[]).map((x) => (typeof x === 'number' ? x.toFixed(3) : String(x))).join(', ')}]`;
  if (v && typeof v === 'object') return JSON.stringify(v);
  return String(v ?? '');
}

export const PropertyPanel = memo(PropertyPanelInner);
