/**
 * ViewContext：向节点组件注入视图状态（背景 opacity / 对比度增强 / 调整中节点 id）。
 *
 * 这些是临时 UI 状态，不应写入 node.data（避免污染导出数据）。
 * TopologyEditor 提供 value，PageBgNode / EquipmentNode / BoundaryNode 消费。
 */
import { createContext } from 'react';

export interface ViewContextValue {
  /** 背景图透明度 0.3–1.0。 */
  bgOpacity: number;
  /** 是否开启管道线增强（CSS contrast/brightness filter）。 */
  bgEnhance: boolean;
  /** 当前进入 bbox 调整模式的节点 id（null 表示无）。 */
  adjustingNodeId: string | null;
  /** 当前鼠标悬停的页面背景节点 id（全局视图页面高亮用，null 表示无）。 */
  hoveredPageId: string | null;
  /** 节点 bbox 拖拽结束回调（flow 坐标）。 */
  onNodeResize: (nodeId: string, next: { x: number; y: number; width: number; height: number }) => void;
}

export const ViewContext = createContext<ViewContextValue>({
  bgOpacity: 0.9,
  bgEnhance: false,
  adjustingNodeId: null,
  hoveredPageId: null,
  onNodeResize: () => {},
});
