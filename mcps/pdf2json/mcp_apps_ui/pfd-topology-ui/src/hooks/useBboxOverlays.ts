import { useMemo } from 'react';
import type { BboxOverlay } from '@/components/common';

/**
 * 从节点列表（含 x/y/width/height + 画布宽高）计算归一化 bbox 叠加层。
 * 抽取自 PlantUnitPage，供其它拓扑页复用。
 */
export function useBboxOverlays(
  nodes: Array<Record<string, unknown>> | undefined,
  canvasWidth?: number,
  canvasHeight?: number,
): BboxOverlay[] {
  return useMemo(() => {
    if (!nodes || !canvasWidth || !canvasHeight) return [];
    return nodes.map((node) => {
      const x = Number(node.x ?? 0);
      const y = Number(node.y ?? 0);
      const w = Number(node.width ?? 0);
      const h = Number(node.height ?? 0);
      return {
        bbox: [
          x / canvasWidth,
          y / canvasHeight,
          (x + w) / canvasWidth,
          (y + h) / canvasHeight,
        ] as [number, number, number, number],
        label: String(node.display_name ?? node.name ?? node.node_id ?? ''),
      };
    });
  }, [nodes, canvasWidth, canvasHeight]);
}
