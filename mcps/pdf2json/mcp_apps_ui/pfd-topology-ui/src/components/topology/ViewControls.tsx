/**
 * 视图控制浮动栏：背景透明度、管道线增强、网格线、MiniMap显隐等。
 * 仅在非只读模式渲染。
 */
interface ViewControlsProps {
  bgOpacity: number;
  bgEnhance: boolean;
  onOpacityChange: (v: number) => void;
  onEnhanceToggle: () => void;
  /** 网格线显示切换（可选，仅在TopologyEditor内有用到） */
  showGrid?: boolean;
  onGridToggle?: () => void;
  /** MiniMap 显隐 */
  minimapVisible?: boolean;
  onMinimapToggle?: () => void;
  /** 重置视图到初始状态（fitView） */
  onResetView?: () => void;
}

export function ViewControls({
  bgOpacity,
  bgEnhance,
  onOpacityChange,
  onEnhanceToggle,
  showGrid,
  onGridToggle,
  minimapVisible,
  onMinimapToggle,
  onResetView,
}: ViewControlsProps) {
  const opacityPct = Math.round(bgOpacity * 100);
  return (
    <div className="glass-panel anim-slide-up-fade absolute left-3 top-14 z-10 flex flex-col gap-2 rounded-lg p-2 w-56">
      <div className="flex items-center justify-between px-1">
        <span className="text-[11px] font-semibold text-text tracking-wide">视图控制</span>
        {onResetView && (
          <button
            type="button"
            onClick={onResetView}
            title="重置视图（适配全部）"
            className="text-[10px] px-2 py-0.5 rounded border border-border text-text3 hover:bg-accent hover:text-white hover:border-accent transition"
          >
            重置
          </button>
        )}
      </div>

      {/* 背景透明度 */}
      <div className="flex flex-col gap-1 px-1">
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-text3 font-medium">背景透明度</span>
          <span className="text-[10px] font-mono text-accent font-semibold">{opacityPct}%</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[9px] text-text3">30%</span>
          <input
            type="range"
            min={0.3}
            max={1}
            step={0.05}
            value={bgOpacity}
            onChange={(e) => onOpacityChange(parseFloat(e.target.value))}
            className="nice-range flex-1"
            title={`背景透明度 ${opacityPct}%`}
          />
          <span className="text-[9px] text-text3">100%</span>
        </div>
      </div>

      {/* 快速透明度按钮组 */}
      <div className="flex gap-1 px-1">
        {[0.4, 0.6, 0.8, 1.0].map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => onOpacityChange(v)}
            className={`flex-1 text-[10px] py-0.5 rounded transition ${
              Math.abs(bgOpacity - v) < 0.025
                ? 'bg-accent text-white font-medium'
                : 'bg-bg3 text-text2 hover:bg-bg-3/70'
            }`}
          >
            {Math.round(v * 100)}%
          </button>
        ))}
      </div>

      {/* 开关组 */}
      <div className="flex flex-col gap-1 pt-1 border-t border-border px-1">
        <ToggleRow
          label="增强管道线"
          desc="对比原图管道"
          active={bgEnhance}
          onClick={onEnhanceToggle}
          color="accent"
        />
        {typeof showGrid === 'boolean' && onGridToggle && (
          <ToggleRow
            label="显示网格线"
            desc="对齐辅助"
            active={showGrid}
            onClick={onGridToggle}
            color="green"
          />
        )}
        {typeof minimapVisible === 'boolean' && onMinimapToggle && (
          <ToggleRow
            label="显示小地图"
            desc="全局导航"
            active={minimapVisible}
            onClick={onMinimapToggle}
            color="purple"
          />
        )}
      </div>
    </div>
  );
}

/** 独立开关行 */
function ToggleRow({
  label,
  desc,
  active,
  onClick,
  color = 'accent',
}: {
  label: string;
  desc?: string;
  active: boolean;
  onClick: () => void;
  color?: 'accent' | 'green' | 'orange' | 'purple' | 'cyan';
}) {
  const colorMap: Record<string, string> = {
    accent: 'bg-accent',
    green: 'bg-green',
    orange: 'bg-orange',
    purple: 'bg-purple',
    cyan: 'bg-cyan',
  };
  const activeBg = colorMap[color] ?? colorMap.accent;
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full flex items-center justify-between py-1.5 px-1.5 rounded hover:bg-bg3/70 transition"
    >
      <div className="flex flex-col items-start">
        <span className="text-[11px] text-text2 font-medium">{label}</span>
        {desc && <span className="text-[9px] text-text3">{desc}</span>}
      </div>
      <div
        className={`relative w-8 h-4.5 rounded-full transition-all ${
          active ? activeBg : 'bg-border2'
        }`}
        style={{ height: '18px' }}
      >
        <div
          className={`absolute top-0.5 w-3.5 h-3.5 rounded-full bg-white shadow transition-transform ${
            active ? 'translate-x-[18px]' : 'translate-x-0.5'
          }`}
          style={{ width: '14px', height: '14px' }}
        />
      </div>
    </button>
  );
}
