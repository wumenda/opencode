/**
 * 节点 bbox 四角拖拽 handle。
 *
 * 拖拽时计算 delta（flow 坐标），调用 onResize 更新节点 width/height/position。
 * - 拖右下角：仅改 width/height
 * - 拖左上角：改 width/height + position（左上角固定反向）
 * - 拖右上角 / 左下角：混合
 *
 * 坐标系：handle 接收屏幕坐标，内部用 rf.screenToFlowPosition 转换。
 */
import { useCallback } from 'react';
import { useReactFlow } from '@xyflow/react';

export type Corner = 'tl' | 'tr' | 'bl' | 'br';

interface ResizeHandleProps {
  corner: Corner;
  /** 节点当前 position.x（flow 坐标，左上角）。 */
  nodeX: number;
  /** 节点当前 position.y（flow 坐标，左上角）。 */
  nodeY: number;
  /** 节点当前 width。 */
  nodeW: number;
  /** 节点当前 height。 */
  nodeH: number;
  /** 拖拽结束时回调，传入新的 {x, y, width, height}（flow 坐标）。 */
  onResizeEnd: (next: { x: number; y: number; width: number; height: number }) => void;
}

const MIN_W = 40;
const MIN_H = 24;

const HANDLE_STYLE: React.CSSProperties = {
  position: 'absolute',
  width: 10,
  height: 10,
  background: 'var(--accent)',
  border: '1.5px solid #fff',
  borderRadius: 2,
  zIndex: 5,
};

const OFFSET = -5; // 让 handle 中心落在节点角上

export function ResizeHandle({ corner, nodeX, nodeY, nodeW, nodeH, onResizeEnd }: ResizeHandleProps) {
  const rf = useReactFlow();

  const posStyle: React.CSSProperties = (() => {
    switch (corner) {
      case 'tl': return { left: OFFSET, top: OFFSET, cursor: 'nwse-resize' };
      case 'tr': return { right: OFFSET, top: OFFSET, cursor: 'nesw-resize' };
      case 'bl': return { left: OFFSET, bottom: OFFSET, cursor: 'nesw-resize' };
      case 'br': return { right: OFFSET, bottom: OFFSET, cursor: 'nwse-resize' };
    }
  })();

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      e.stopPropagation();
      e.preventDefault();
      const el = e.currentTarget as SVGElement;
      el.setPointerCapture(e.pointerId);

      const startFlow = rf.screenToFlowPosition({ x: e.clientX, y: e.clientY });

      const move = (ev: PointerEvent) => {
        const curFlow = rf.screenToFlowPosition({ x: ev.clientX, y: ev.clientY });
        const dx = curFlow.x - startFlow.x;
        const dy = curFlow.y - startFlow.y;
        let nx = nodeX, ny = nodeY, nw = nodeW, nh = nodeH;
        switch (corner) {
          case 'br':
            nw = Math.max(MIN_W, nodeW + dx);
            nh = Math.max(MIN_H, nodeH + dy);
            break;
          case 'tr':
            nw = Math.max(MIN_W, nodeW + dx);
            nh = Math.max(MIN_H, nodeH - dy);
            ny = nodeY + (nodeH - nh);
            break;
          case 'bl':
            nw = Math.max(MIN_W, nodeW - dx);
            nh = Math.max(MIN_H, nodeH + dy);
            nx = nodeX + (nodeW - nw);
            break;
          case 'tl':
            nw = Math.max(MIN_W, nodeW - dx);
            nh = Math.max(MIN_H, nodeH - dy);
            nx = nodeX + (nodeW - nw);
            ny = nodeY + (nodeH - nh);
            break;
        }
        onResizeEnd({ x: nx, y: ny, width: nw, height: nh });
      };
      const up = (ev: PointerEvent) => {
        el.releasePointerCapture(ev.pointerId);
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    },
    [rf, corner, nodeX, nodeY, nodeW, nodeH, onResizeEnd],
  );

  return <div style={{ ...HANDLE_STYLE, ...posStyle }} onPointerDown={onPointerDown} />;
}
