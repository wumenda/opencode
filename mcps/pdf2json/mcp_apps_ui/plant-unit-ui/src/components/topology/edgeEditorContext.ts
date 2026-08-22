/**
 * EdgeEditorContext：向自定义边组件注入编辑能力。
 *
 * 避免把函数塞进 edge.data（data 会被序列化导出），改用 React context。
 */
import { createContext } from 'react';
import type { BendPoint } from './EditableEdge';

export interface EdgeEditorContextValue {
  /** 是否只读（只读时不渲染折点手柄）。 */
  readOnly: boolean;
  /**
   * 更新某条边的折点。
   * @param edgeId 边 id
   * @param bends 新折点列表
   * @param commitToHistory 是否提交到撤销/重做历史（拖拽中间帧传 false，松手时传 true）
   */
  updateBends: (edgeId: string, bends: BendPoint[], commitToHistory?: boolean) => void;
}

export const EdgeEditorContext = createContext<EdgeEditorContextValue | null>(null);
