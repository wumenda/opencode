/**
 * 可编辑自定义边组件。
 *
 * 优化点：
 *   - hover 高亮效果
 *   - 更清晰的选中 / 跨页边样式
 *   - 标签背景更精致
 *   - 折点更大更清晰，带 hover 效果
 *   - 增加快捷操作提示（选中时显示提示）
 *   - 路径点击区域更宽，命中更友好
 *   - 折点/中点添加器使用 EdgeLabelRenderer (HTML 层)，规避 SVG pointer-events: none
 */

import { memo, useCallback, useContext, useEffect, useState } from 'react';
import {
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
  useReactFlow,
  type EdgeProps,
  type XYPosition,
} from '@xyflow/react';
import { EdgeEditorContext } from './edgeEditorContext';

export interface BendPoint extends XYPosition {}

interface EditableEdgeData {
  bendPoints?: BendPoint[];
  label?: string;
  [k: string]: unknown;
}

function distanceToSegment(
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number,
): { dist: number; t: number } {
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  let t = 0;
  if (len2 > 0) t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2));
  const cx = ax + t * dx;
  const cy = ay + t * dy;
  return { dist: Math.hypot(px - cx, py - cy), t };
}

function EditableEdgeInner(props: EdgeProps) {
  const {
    id,
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    data,
    selected,
    markerEnd,
  } = props;
  const d = data as EditableEdgeData | undefined;
  const bends = d?.bendPoints ?? [];
  // 流股号：来源 raw.stream_number，无值则不显示标签（不展示边名称）
  const streamNumber = ((d as { raw?: Record<string, unknown> })?.raw?.stream_number ?? '') as string;
  const isCross = (d as { _export?: { kind?: string } })?._export?.kind === 'cross';
  const ctx = useContext(EdgeEditorContext);
  const rf = useReactFlow();
  const [hovered, setHovered] = useState(false);
  // 待删除折点索引（右键标红，左键确认删除）
  const [pendingDeleteIdx, setPendingDeleteIdx] = useState<number | null>(null);

  // 取消选中时清除标红
  useEffect(() => {
    if (!selected) setPendingDeleteIdx(null);
  }, [selected]);

  // Esc 取消标红
  useEffect(() => {
    if (pendingDeleteIdx === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        setPendingDeleteIdx(null);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [pendingDeleteIdx]);

  // 构建路径
  let path: string;
  let labelX: number;
  let labelY: number;
  if (bends.length === 0) {
    [path, labelX, labelY] = getSmoothStepPath({
      sourceX,
      sourceY,
      sourcePosition,
      targetX,
      targetY,
      targetPosition,
      borderRadius: 10,
    });
  } else {
    const pts: Array<[number, number]> = [
      [sourceX, sourceY],
      ...bends.map((b) => [b.x, b.y] as [number, number]),
      [targetX, targetY],
    ];
    // 带圆角的折线 (简单实现：相邻线段之间切角)
    path = buildRoundedPolyline(pts, 6);
    // 标签放中间点
    const mid = pts[Math.floor(pts.length / 2)];
    labelX = mid[0];
    labelY = mid[1];
  }

  // 双击路径：在最近线段上插入折点
  const onPathDoubleClick = useCallback(
    (e: React.MouseEvent) => {
      if (ctx?.readOnly) return;
      e.stopPropagation();
      e.preventDefault();
      const flowPos = rf.screenToFlowPosition({ x: e.clientX, y: e.clientY });
      const pts: Array<[number, number]> = [
        [sourceX, sourceY],
        ...bends.map((b) => [b.x, b.y] as [number, number]),
        [targetX, targetY],
      ];
      let bestIdx = 0;
      let bestDist = Infinity;
      for (let i = 0; i < pts.length - 1; i++) {
        const r = distanceToSegment(flowPos.x, flowPos.y, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]);
        if (r.dist < bestDist) {
          bestDist = r.dist;
          bestIdx = i;
        }
      }
      const next = [...bends];
      next.splice(bestIdx, 0, { x: flowPos.x, y: flowPos.y });
      ctx?.updateBends(id, next);
    },
    [ctx, rf, id, sourceX, sourceY, targetX, targetY, bends],
  );

  // 折点拖拽（左键）；左键点击已标红折点 -> 确认删除
  const onBendPointerDown = useCallback(
    (e: React.PointerEvent, idx: number) => {
      if (ctx?.readOnly) return;
      // 右键/中键不启动拖拽（右键由 onContextMenu 标红）
      if (e.button !== 0) return;
      e.stopPropagation();
      e.preventDefault();
      // 左键点击已标红折点 -> 确认删除
      if (pendingDeleteIdx === idx) {
        const next = bends.filter((_, i) => i !== idx);
        ctx?.updateBends(id, next, true);
        setPendingDeleteIdx(null);
        return;
      }
      // 点击其它折点 -> 取消标红
      if (pendingDeleteIdx !== null) setPendingDeleteIdx(null);
      e.nativeEvent.stopImmediatePropagation();
      const el = e.currentTarget as HTMLElement;
      el.setPointerCapture(e.pointerId);
      const move = (ev: PointerEvent) => {
        const fp = rf.screenToFlowPosition({ x: ev.clientX, y: ev.clientY });
        const next = bends.map((b, i) => (i === idx ? { x: fp.x, y: fp.y } : b));
        ctx?.updateBends(id, next, false);
      };
      const up = (ev: PointerEvent) => {
        el.releasePointerCapture(ev.pointerId);
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        const fp = rf.screenToFlowPosition({ x: ev.clientX, y: ev.clientY });
        const next = bends.map((b, i) => (i === idx ? { x: fp.x, y: fp.y } : b));
        ctx?.updateBends(id, next, true);
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    },
    [ctx, rf, id, bends, pendingDeleteIdx],
  );

  // 右键折点：标红待删除
  const onBendContextMenu = useCallback(
    (e: React.MouseEvent, idx: number) => {
      if (ctx?.readOnly) return;
      e.stopPropagation();
      e.preventDefault();
      setPendingDeleteIdx(idx);
    },
    [ctx],
  );

  // 双击折点：仅阻止冒泡到 <g> 的"添加折点"，避免误增折点
  // （删除改用右键标红 + 左键确认，防止误删）
  const onBendDoubleClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
  }, []);

  // 边样式
  const isHighlighted = selected || hovered;
  const stroke = selected ? 'var(--orange)' : isCross ? 'var(--cyan)' : 'var(--accent)';
  const strokeWidth = selected ? 3.2 : hovered ? 2.4 : bends.length > 0 ? 2 : 1.8;
  const strokeDasharray = isCross ? '8 5' : undefined;
  const animStyle: React.CSSProperties | undefined = isCross && isHighlighted
    ? { animation: 'dash-flow 0.8s linear infinite' }
    : undefined;

  // 所有折点 + 端点坐标（用于中点添加器）
  const allPts: Array<[number, number]> = [
    [sourceX, sourceY],
    ...bends.map((b) => [b.x, b.y] as [number, number]),
    [targetX, targetY],
  ];

  return (
    <g
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onDoubleClick={onPathDoubleClick}
    >
      {/* 外层辉光（选中/hover） */}
      {isHighlighted && (
        <path
          d={path}
          fill="none"
          stroke={stroke}
          strokeOpacity={0.18}
          strokeWidth={strokeWidth + 10}
          strokeLinecap="round"
          style={animStyle}
        />
      )}
      {/* 主边 */}
      <BaseEdge
        path={path}
        markerEnd={markerEnd}
        style={{
          stroke,
          strokeWidth,
          strokeDasharray,
          strokeLinecap: 'round',
          strokeLinejoin: 'round',
          ...animStyle,
        }}
      />
      {/* 标签：仅显示流股号；无 stream_number 则不显示 */}
      {streamNumber && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: 'absolute',
              transform: `translate(-50%,-50%) translate(${labelX}px,${labelY}px)`,
              pointerEvents: 'none',
              fontSize: 11,
              fontWeight: selected ? 600 : 500,
              background: selected
                ? 'linear-gradient(135deg, rgba(234,140,12,0.95), rgba(234,140,12,0.85))'
                : hovered
                ? 'rgba(37,99,235,0.92)'
                : 'rgba(255,255,255,0.94)',
              color: selected || hovered ? '#fff' : 'var(--text)',
              padding: '3px 10px',
              borderRadius: 999,
              whiteSpace: 'nowrap',
              boxShadow: selected
                ? '0 4px 14px rgba(234,140,12,0.35)'
                : hovered
                ? '0 4px 14px rgba(37,99,235,0.3)'
                : '0 2px 6px rgba(10,26,95,0.08)',
              border: selected
                ? '1px solid rgba(255,255,255,0.3)'
                : hovered
                ? '1px solid rgba(255,255,255,0.25)'
                : '1px solid var(--border)',
              backdropFilter: 'blur(4px)',
              transition: 'all 0.15s ease',
              fontFamily: 'var(--font-mono, monospace)',
              letterSpacing: '0.01em',
            }}
          >
            {streamNumber}
          </div>
        </EdgeLabelRenderer>
      )}
      {/* 折点 & 中点添加器（仅选中且可编辑时，用 HTML 层渲染确保可交互） */}
      {selected && !ctx?.readOnly && (
        <EdgeLabelRenderer>
          {/* 中点添加器 */}
          {allPts.slice(0, -1).map(([x1, y1], i) => {
            const [x2, y2] = allPts[i + 1];
            const mx = (x1 + x2) / 2;
            const my = (y1 + y2) / 2;
            return (
              <div
                key={`mp-${i}`}
                title="点击添加折点"
                className="nopan nodrag"
                style={{
                  position: 'absolute',
                  transform: `translate(-50%,-50%) translate(${mx}px,${my}px)`,
                  width: 22,
                  height: 22,
                  borderRadius: '50%',
                  background: 'rgba(37,99,235,0.1)',
                  border: '1.5px solid var(--accent)',
                  cursor: 'crosshair',
                  pointerEvents: 'all',
                  zIndex: 1000,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'background 0.15s, transform 0.15s',
                  color: 'var(--accent)',
                  fontSize: 13,
                  fontWeight: 'bold',
                  lineHeight: 1,
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'rgba(37,99,235,0.25)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'rgba(37,99,235,0.1)';
                }}
                onClick={(e) => {
                  e.stopPropagation();
                  const next = [...bends];
                  next.splice(i, 0, { x: mx, y: my });
                  ctx?.updateBends(id, next);
                }}
              >
                +
              </div>
            );
          })}

          {/* 折点拖拽手柄 */}
          {bends.map((b, i) => {
            const isPendingDelete = pendingDeleteIdx === i;
            return (
              <div
                key={`bend-${i}`}
                title={isPendingDelete ? '左键确认删除 · Esc 取消' : '拖拽移动 · 右键标记删除'}
                className="nopan nodrag"
                style={{
                  position: 'absolute',
                  transform: `translate(-50%,-50%) translate(${b.x}px,${b.y}px)`,
                  width: 16,
                  height: 16,
                  borderRadius: '50%',
                  background: isPendingDelete ? '#ef4444' : stroke,
                  border: '2.5px solid #fff',
                  cursor: isPendingDelete ? 'pointer' : 'move',
                  pointerEvents: 'all',
                  zIndex: 1001,
                  boxShadow: isPendingDelete
                    ? '0 0 0 4px rgba(239,68,68,0.25), 0 1px 4px rgba(239,68,68,0.4)'
                    : '0 1px 4px rgba(10,26,95,0.3)',
                }}
                onPointerDown={(e) => onBendPointerDown(e, i)}
                onContextMenu={(e) => onBendContextMenu(e, i)}
                onDoubleClick={onBendDoubleClick}
              />
            );
          })}

          {/* 无折点时的操作提示 */}
          {bends.length === 0 && (
            <div
              style={{
                position: 'absolute',
                transform: `translate(-50%,-50%) translate(${labelX}px,${labelY + 24}px)`,
                pointerEvents: 'none',
                fontSize: 10,
                color: 'var(--text-3, #94a3b8)',
                background: 'rgba(255,255,255,0.92)',
                padding: '2px 8px',
                borderRadius: 4,
                whiteSpace: 'nowrap',
                border: '1px solid var(--border, #e2e8f0)',
              }}
            >
              双击边线或点击 + 添加折点
            </div>
          )}
        </EdgeLabelRenderer>
      )}
    </g>
  );
}

/* ========== 辅助：圆角折线生成 ========== */
function buildRoundedPolyline(pts: Array<[number, number]>, r: number): string {
  if (pts.length < 2) return '';
  if (pts.length === 2) {
    return `M${pts[0][0]},${pts[0][1]} L${pts[1][0]},${pts[1][1]}`;
  }
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const [px, py] = pts[i - 1];
    const [cx, cy] = pts[i];
    const [nx, ny] = pts[i + 1];
    const d1 = Math.hypot(cx - px, cy - py);
    const d2 = Math.hypot(nx - cx, ny - cy);
    const k = Math.min(r / d1, r / d2, 0.4);
    const ix = cx - (cx - px) * k;
    const iy = cy - (cy - py) * k;
    const ox = cx + (nx - cx) * k;
    const oy = cy + (ny - cy) * k;
    d += ` L${ix},${iy} Q${cx},${cy} ${ox},${oy}`;
  }
  const last = pts[pts.length - 1];
  d += ` L${last[0]},${last[1]}`;
  return d;
}

export const EditableEdge = memo(EditableEdgeInner);
