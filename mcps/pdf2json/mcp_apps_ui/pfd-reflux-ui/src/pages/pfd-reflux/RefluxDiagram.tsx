/**
 * 塔回流关系示意图（SVG）。
 *
 * 布局：塔体竖向矩形居中；塔顶冷凝器在右上（若 has_top_condenser）；塔釜再沸器在左下（若 has_bottom_reboiler）；
 * 回流箭头从冷凝器/再沸器指向塔体。无回流时显示简化塔体。
 */
export interface RefluxDiagramProps {
  hasTopCondenser?: boolean | null;
  hasBottomReboiler?: boolean | null;
  topCondenserTag?: string;
  bottomReboilerTag?: string;
  refluxType?: string; // none | top | bottom | top_and_bottom
}

export function RefluxDiagram({
  hasTopCondenser,
  hasBottomReboiler,
  topCondenserTag,
  bottomReboilerTag,
  refluxType = 'none',
}: RefluxDiagramProps) {
  const showTop = hasTopCondenser === true || refluxType === 'top' || refluxType === 'top_and_bottom';
  const showBottom = hasBottomReboiler === true || refluxType === 'bottom' || refluxType === 'top_and_bottom';
  const W = 200;
  const H = 240;
  const towerX = 80;
  const towerW = 40;
  const towerY = 30;
  const towerH = 180;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-48 w-full">
      {/* 塔体 */}
      <rect x={towerX} y={towerY} width={towerW} height={towerH} fill="#edf5ff" stroke="#3168ff" strokeWidth="1.5" rx="4" />
      {/* 塔板示意线 */}
      {[0.25, 0.4, 0.55, 0.7, 0.85].map((p, i) => (
        <line key={i} x1={towerX + 4} y1={towerY + towerH * p} x2={towerX + towerW - 4} y2={towerY + towerH * p} stroke="#8a9abf" strokeWidth="0.8" strokeDasharray="2 2" />
      ))}
      <text x={towerX + towerW / 2} y={towerY - 6} fontSize="9" fill="#07175f" textAnchor="middle" fontWeight="bold">塔</text>

      {/* 塔顶冷凝器 */}
      {showTop && (
        <g>
          <circle cx={150} cy={50} r="16" fill="#e8f5ee" stroke="#18a581" strokeWidth="1.5" />
          <text x={150} y={54} fontSize="8" fill="#18a581" textAnchor="middle">C</text>
          {/* 回流箭头：冷凝器 -> 塔顶 */}
          <path d={`M 134 50 Q 110 50 ${towerX + towerW} 40`} fill="none" stroke="#18a581" strokeWidth="1.2" markerEnd="url(#arrow-green)" />
          {topCondenserTag && (
            <text x={150} y={78} fontSize="8" fill="#5d6d9c" textAnchor="middle">{topCondenserTag}</text>
          )}
        </g>
      )}

      {/* 塔釜再沸器 */}
      {showBottom && (
        <g>
          <circle cx={50} cy={190} r="16" fill="#fff4e6" stroke="#e8920c" strokeWidth="1.5" />
          <text x={50} y={194} fontSize="8" fill="#e8920c" textAnchor="middle">R</text>
          {/* 回流箭头：再沸器 -> 塔釜 */}
          <path d={`M 66 190 Q 80 190 ${towerX} 200`} fill="none" stroke="#e8920c" strokeWidth="1.2" markerEnd="url(#arrow-orange)" />
          {bottomReboilerTag && (
            <text x={50} y={218} fontSize="8" fill="#5d6d9c" textAnchor="middle">{bottomReboilerTag}</text>
          )}
        </g>
      )}

      {!showTop && !showBottom && (
        <text x={100} y={130} fontSize="9" fill="#8a9abf" textAnchor="middle">无回流</text>
      )}

      <defs>
        <marker id="arrow-green" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
          <path d="M0,0 L6,3 L0,6 Z" fill="#18a581" />
        </marker>
        <marker id="arrow-orange" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
          <path d="M0,0 L6,3 L0,6 Z" fill="#e8920c" />
        </marker>
      </defs>
    </svg>
  );
}