/**
 * 边逐条审核浮动栏。
 *
 * 优化点：
 *   - 玻璃拟态 + 更清晰的视觉层次
 *   - 顶部进度条（带百分比高亮）
 *   - 更明显的动作按钮（带图标 + 悬停微动效）
 *   - 重连状态带强调色和提示
 *   - 快捷键提示更直观
 *   - 源/目标标签带类型色点
 */
import type { Edge, Node } from '@xyflow/react';

interface EdgeReviewBarProps {
  edges: Edge[];
  nodes: Node[];
  index: number;
  reconnecting: boolean;
  onKeep: () => void;
  onDelete: () => void;
  onReconnect: () => void;
  onSkip: () => void;
  onPrev: () => void;
  onNext: () => void;
  onExit: () => void;
}

function nodeLabel(nodes: Node[], id: string): { label: string; type?: string } {
  const n = nodes.find((x) => x.id === id);
  if (!n) return { label: id };
  const data = n.data as { tag?: string; equipment_type?: string };
  return { label: data.tag || id, type: data.equipment_type };
}

function typeDotColor(type?: string): string {
  if (!type) return 'var(--border)';
  const t = type.toLowerCase();
  if (t.includes('pump') || t.includes('泵')) return 'var(--red)';
  if (t.includes('valve') || t.includes('阀')) return 'var(--orange)';
  if (t.includes('heat') || t.includes('exch') || t.includes('换')) return 'var(--yellow)';
  if (t.includes('vessel') || t.includes('column') || t.includes('塔') || t.includes('罐')) return 'var(--green)';
  if (t.includes('compress') || t.includes('压')) return 'var(--purple)';
  return 'var(--accent)';
}

export function EdgeReviewBar({
  edges, nodes, index, reconnecting,
  onKeep, onDelete, onReconnect, onSkip, onPrev, onNext, onExit,
}: EdgeReviewBarProps) {
  const total = edges.length;
  const progress = total > 0 ? ((index + 1) / total) * 100 : 0;
  const e = edges[index];
  const src = e ? nodeLabel(nodes, e.source) : { label: '?' };
  const tgt = e ? nodeLabel(nodes, e.target) : { label: '?' };

  return (
    <div className="anim-slide-up-fade absolute left-1/2 top-2 z-20 w-[94%] max-w-3xl -translate-x-1/2">
      <div className="glass-panel rounded-xl border border-border/80 shadow-card-strong overflow-hidden">
        {/* 进度条 */}
        <div className="h-1.5 w-full bg-bg-3/60 overflow-hidden">
          <div
            className="h-full rounded-r-full transition-all duration-300 ease-out"
            style={{
              width: `${progress}%`,
              background: reconnecting
                ? 'linear-gradient(90deg, var(--orange), var(--yellow))'
                : 'linear-gradient(90deg, var(--green), var(--accent))',
            }}
          />
        </div>

        <div className="flex items-center gap-3 px-4 py-3">
          {/* 退出按钮 */}
          <button
            type="button"
            onClick={onExit}
            title="退出审核 (Esc)"
            className="group flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-border/60 text-text-3 hover:bg-red/10 hover:text-red hover:border-red/40 transition"
          >
            <span className="text-[14px] leading-none group-hover:scale-110 transition">✕</span>
          </button>

          {/* 进度与边信息 */}
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <div className="flex flex-col">
              <span className="text-[10px] font-medium text-text-3 tracking-wider uppercase">审核进度</span>
              <span className="font-mono text-sm font-semibold text-text leading-tight">
                {total > 0 ? index + 1 : 0}<span className="text-text-3 font-normal"> / {total}</span>
                <span className="ml-2 text-[11px] text-accent font-medium">{progress.toFixed(0)}%</span>
              </span>
            </div>

            <div className="mx-1 h-8 w-px bg-border/60" />

            {/* 边连接信息 */}
            <div className="flex min-w-0 items-center gap-2">
              <div className="flex items-center gap-1.5 min-w-0 max-w-[220px]">
                <span
                  className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{
                    backgroundColor: typeDotColor(src.type),
                    boxShadow: `0 0 0 2px rgba(255,255,255,0.85), 0 0 0 4px ${typeDotColor(src.type)}33`,
                  }}
                />
                <span className="truncate rounded-md bg-bg-3/60 px-2 py-0.5 font-mono text-[12px] text-text border border-border/40">
                  {src.label}
                </span>
              </div>

              <span className="shrink-0 text-accent font-bold text-sm">→</span>

              <div className="flex items-center gap-1.5 min-w-0 max-w-[220px]">
                <span
                  className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{
                    backgroundColor: typeDotColor(tgt.type),
                    boxShadow: `0 0 0 2px rgba(255,255,255,0.85), 0 0 0 4px ${typeDotColor(tgt.type)}33`,
                  }}
                />
                <span className="truncate rounded-md bg-bg-3/60 px-2 py-0.5 font-mono text-[12px] text-text border border-border/40">
                  {tgt.label}
                </span>
              </div>
            </div>
          </div>

          {/* 上一条/下一条 */}
          <div className="flex items-center gap-1 border-l border-border/60 pl-3">
            <button
              type="button"
              onClick={onPrev}
              disabled={index <= 0}
              title="上一条 (←)"
              className="flex h-7 w-7 items-center justify-center rounded-lg border border-border/60 text-text-2 hover:bg-accent hover:text-white hover:border-accent disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-text-2 disabled:hover:border-border/60 transition"
            >
              ‹
            </button>
            <button
              type="button"
              onClick={onNext}
              disabled={index >= total - 1}
              title="下一条 (→)"
              className="flex h-7 w-7 items-center justify-center rounded-lg border border-border/60 text-text-2 hover:bg-accent hover:text-white hover:border-accent disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-text-2 disabled:hover:border-border/60 transition"
            >
              ›
            </button>
          </div>

          {/* 动作按钮组 */}
          <div className="ml-1 flex items-center gap-2 border-l border-border/60 pl-3">
            {reconnecting ? (
              <div className="flex items-center gap-2 rounded-lg border border-orange/40 bg-orange/10 px-3 py-1.5">
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-orange opacity-75" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-orange" />
                </span>
                <span className="text-[12px] font-semibold text-orange whitespace-nowrap">
                  拖拽端点到新节点（Esc 取消）
                </span>
              </div>
            ) : (
              <>
                <ReviewBtn
                  onClick={onKeep}
                  color="green"
                  icon="✓"
                  label="保留"
                  shortcut="Enter"
                  title="保留并下一条 (Enter)"
                />
                <ReviewBtn
                  onClick={onDelete}
                  color="red"
                  icon="✕"
                  label="删除"
                  shortcut="Delete"
                  title="删除并下一条 (Delete)"
                />
                <ReviewBtn
                  onClick={onReconnect}
                  color="orange"
                  icon="↔"
                  label="重连"
                  shortcut="R"
                  title="重连端点 (R)"
                />
                <ReviewBtn
                  onClick={onSkip}
                  color="neutral"
                  icon="⏭"
                  label="跳过"
                  shortcut="S"
                  title="跳过到下一条 (S)"
                />
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function ReviewBtn({
  onClick, color, icon, label, shortcut, title,
}: {
  onClick: () => void;
  color: 'green' | 'red' | 'orange' | 'neutral';
  icon: string;
  label: string;
  shortcut: string;
  title: string;
}) {
  const palette: Record<string, { bg: string; hoverBg: string; text: string; border: string; hoverBorder: string; shadow: string }> = {
    green: {
      bg: 'rgba(5,150,105,0.12)',
      hoverBg: 'rgba(5,150,105,0.22)',
      text: 'rgb(5,150,105)',
      border: 'rgba(5,150,105,0.3)',
      hoverBorder: 'rgba(5,150,105,0.5)',
      shadow: '0 2px 8px rgba(5,150,105,0.2)',
    },
    red: {
      bg: 'rgba(220,38,38,0.1)',
      hoverBg: 'rgba(220,38,38,0.2)',
      text: 'rgb(220,38,38)',
      border: 'rgba(220,38,38,0.3)',
      hoverBorder: 'rgba(220,38,38,0.5)',
      shadow: '0 2px 8px rgba(220,38,38,0.2)',
    },
    orange: {
      bg: 'rgba(234,140,12,0.1)',
      hoverBg: 'rgba(234,140,12,0.2)',
      text: 'rgb(234,140,12)',
      border: 'rgba(234,140,12,0.3)',
      hoverBorder: 'rgba(234,140,12,0.5)',
      shadow: '0 2px 8px rgba(234,140,12,0.2)',
    },
    neutral: {
      bg: 'rgba(100,116,139,0.1)',
      hoverBg: 'rgba(100,116,139,0.18)',
      text: 'rgb(71,85,105)',
      border: 'rgba(100,116,139,0.25)',
      hoverBorder: 'rgba(100,116,139,0.45)',
      shadow: '0 2px 6px rgba(100,116,139,0.15)',
    },
  };
  const c = palette[color];

  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className="group flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[12px] font-medium border transition-all duration-150 hover:-translate-y-0.5 active:translate-y-0"
      style={{
        backgroundColor: c.bg,
        color: c.text,
        borderColor: c.border,
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLButtonElement).style.backgroundColor = c.hoverBg;
        (e.currentTarget as HTMLButtonElement).style.borderColor = c.hoverBorder;
        (e.currentTarget as HTMLButtonElement).style.boxShadow = c.shadow;
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLButtonElement).style.backgroundColor = c.bg;
        (e.currentTarget as HTMLButtonElement).style.borderColor = c.border;
        (e.currentTarget as HTMLButtonElement).style.boxShadow = 'none';
      }}
    >
      <span className="text-sm leading-none">{icon}</span>
      <span className="whitespace-nowrap">{label}</span>
      <kbd className="ml-0.5 rounded border px-1 py-0 text-[9.5px] opacity-70"
        style={{ borderColor: c.border, backgroundColor: 'rgba(255,255,255,0.5)' }}>
        {shortcut}
      </kbd>
    </button>
  );
}
