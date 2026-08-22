/**
 * 页面标识头：为每个审核页面提供独特的视觉标识（图标 + 标题 + 主题色）。
 *
 * 各页面颜色分配：
 *   cyan   - 整厂装置拓扑（plant_unit_topology）
 *   orange - 设备装配图（equipment_assembly）
 *   green  - 工艺包章节（process_package）
 *   purple - 拓扑叠加（topology_overlay）
 *   yellow - PFD 回流结构（pfd_reflux）
 *   red    - 组分表（composition_table）
 */

import type { ReactNode } from 'react';

type PageColor = 'cyan' | 'orange' | 'green' | 'purple' | 'yellow' | 'red';

const COLOR_STYLES: Record<PageColor, { badge: string; bar: string; border: string }> = {
  cyan: { badge: 'bg-cyan/10 text-cyan', bar: 'bg-cyan', border: 'border-cyan/30' },
  orange: { badge: 'bg-orange/10 text-orange', bar: 'bg-orange', border: 'border-orange/30' },
  green: { badge: 'bg-green/10 text-green', bar: 'bg-green', border: 'border-green/30' },
  purple: { badge: 'bg-purple/10 text-purple', bar: 'bg-purple', border: 'border-purple/30' },
  yellow: { badge: 'bg-yellow/10 text-yellow', bar: 'bg-yellow', border: 'border-yellow/30' },
  red: { badge: 'bg-red/10 text-red', bar: 'bg-red', border: 'border-red/30' },
};

const ICONS: Record<string, ReactNode> = {
  // 整厂装置拓扑：网络/图谱节点
  plantUnit: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="5" r="2" />
      <circle cx="5" cy="19" r="2" />
      <circle cx="19" cy="19" r="2" />
      <path d="M12 7v3M11 12l-5 5M13 12l5 5" />
    </svg>
  ),
  // 设备装配图：扳手
  equipment: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14.7 6.3a4 4 0 0 1-5.4 5.4L4 17v3h3l5.3-5.3a4 4 0 0 1 5.4-5.4l-2.3 2.3-2.7-2.7 2.3-2.3z" />
    </svg>
  ),
  // 工艺包章节：文档
  document: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6M8 13h8M8 17h6" />
    </svg>
  ),
  // 拓扑叠加：层叠
  layers: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
    </svg>
  ),
  // PFD 回流结构：循环箭头
  reflux: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 12a9 9 0 0 1 15-6.7L21 8M21 3v5h-5" />
      <path d="M21 12a9 9 0 0 1-15 6.7L3 16M3 21v-5h5" />
    </svg>
  ),
  // 组分表：表格
  table: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M3 9h18M3 15h18M9 3v18M15 3v18" />
    </svg>
  ),
  // Progress 探测：信号脉冲
  signal: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 12h4M8 12h2M14 12h2M20 12h2" />
      <path d="M2 12a10 10 0 0120 0" strokeDasharray="2 3" />
    </svg>
  ),
};

interface PageHeaderProps {
  icon: keyof typeof ICONS;
  title: string;
  subtitle: string;
  color: PageColor;
}

export function PageHeader({ icon, title, subtitle, color }: PageHeaderProps) {
  const s = COLOR_STYLES[color];
  return (
    <div className={`flex items-center gap-3 border-b ${s.border} bg-bg-2/60 px-4 py-2.5`}>
      <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${s.badge}`}>
        {ICONS[icon]}
      </div>
      <div className="flex flex-col">
        <h2 className="text-sm font-bold leading-tight text-text">{title}</h2>
        <span className="font-mono text-[11px] leading-tight text-text-3">{subtitle}</span>
      </div>
      <span className={`ml-auto h-1.5 w-12 rounded-full ${s.bar}`} />
    </div>
  );
}
