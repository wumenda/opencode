/**
 * 塔体示意图（SVG）：竖向塔体轮廓 + 内件段分段 + 接管符号。
 *
 * 内件段按 elevation_bottom + height 绘制为塔体上的分段色块
 * （塔板=青色，填料=紫色）。
 * 接管按均匀分布放置在塔体周围，带 nominal_size 标注。
 */

interface InternalSection {
  from_no?: number | string;
  to_no?: number | string;
  height?: { value?: number | null; unit?: string } | null;
  elevation_bottom?: { value?: number | null; unit?: string } | null;
  type?: string; // tray | packed | ...
}

interface Nozzle {
  nozzle_id?: string;
  nominal_size?: string;
  nozzle_role?: string;
  service_description?: string;
}

export function TowerSchematic({
  sections = [],
  nozzles = [],
  onNozzleClick,
}: {
  sections: InternalSection[];
  nozzles: Nozzle[];
  onNozzleClick?: (index: number) => void;
}) {
  const W = 280;
  const H = 400;
  const towerX = 120;
  const towerW = 50;
  const towerTopY = 30;
  const towerBotY = 370;

  // 计算内件段 y 范围（按 elevation_bottom 归一化到塔体高度）
  const elevations = sections.map((s) => s.elevation_bottom?.value ?? 0);
  const maxElev = Math.max(...elevations, 1);
  const sectionColor = (t?: string) =>
    t === 'packed' ? '#7c3aed' : '#0891b2'; // 填料紫，塔板青

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-96 w-full">
      {/* 塔体轮廓 */}
      <rect x={towerX} y={towerTopY} width={towerW} height={towerBotY - towerTopY} fill="#f7fbff" stroke="#07175f" strokeWidth="1.5" rx="6" />
      <text x={towerX + towerW / 2} y={towerTopY - 8} fontSize="10" fill="#07175f" textAnchor="middle" fontWeight="bold">塔体</text>

      {/* 内件段分段色块 */}
      {sections.map((s, i) => {
        const elev = s.elevation_bottom?.value ?? 0;
        const h = s.height?.value ?? 20;
        const y1 = towerBotY - (elev / maxElev) * (towerBotY - towerTopY);
        const y2 = towerBotY - ((elev + h) / maxElev) * (towerBotY - towerTopY);
        return (
          <g key={i}>
            <rect x={towerX + 2} y={Math.min(y1, y2)} width={towerW - 4} height={Math.abs(y2 - y1)} fill={sectionColor(s.type)} fillOpacity="0.3" stroke={sectionColor(s.type)} strokeWidth="0.8" />
            <text x={towerX + towerW + 6} y={(y1 + y2) / 2 + 3} fontSize="8" fill="#5d6d9c">
              {s.from_no ?? '?'}~{s.to_no ?? '?'}
            </text>
          </g>
        );
      })}

      {/* 接管符号：均匀分布在塔体周围 */}
      {nozzles.map((n, i) => {
        const angle = (i / Math.max(nozzles.length, 1)) * Math.PI * 2;
        const r = 35;
        const cx = towerX + towerW / 2 + Math.cos(angle) * r;
        const cy = (towerTopY + towerBotY) / 2 + Math.sin(angle) * r * 0.5;
        return (
          <g key={i} onClick={() => onNozzleClick?.(i)} className="cursor-pointer transition-opacity hover:opacity-70">
            <line x1={towerX + towerW / 2} y1={(towerTopY + towerBotY) / 2} x2={cx} y2={cy} stroke="#5d6d9c" strokeWidth="1" />
            <circle cx={cx} cy={cy} r="5" fill="#fff" stroke="#3168ff" strokeWidth="1.2" />
            <text x={cx} y={cy + 14} fontSize="7" fill="#5d6d9c" textAnchor="middle">
              {n.nominal_size || n.nozzle_id || n.nozzle_role || `N${i + 1}`}
            </text>
          </g>
        );
      })}

      {/* 图例 */}
      <g>
        <rect x={10} y={H - 30} width={10} height={8} fill="#0891b2" fillOpacity="0.3" stroke="#0891b2" />
        <text x={24} y={H - 22} fontSize="8" fill="#5d6d9c">塔板</text>
        <rect x={60} y={H - 30} width={10} height={8} fill="#7c3aed" fillOpacity="0.3" stroke="#7c3aed" />
        <text x={74} y={H - 22} fontSize="8" fill="#5d6d9c">填料</text>
      </g>
    </svg>
  );
}