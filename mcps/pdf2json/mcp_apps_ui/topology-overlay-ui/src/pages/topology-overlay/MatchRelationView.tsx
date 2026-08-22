/**
 * 匹配关系视图：双栏 + SVG 连线。
 *
 * 左栏=工艺说明设备；右栏=图纸设备；中间连线表示匹配关系。
 * 颜色：matched=绿实线，unmatched_pd=橙（无连线，指向"跨图"标签），extra_image=灰（无连线）。
 */
import { useMemo } from 'react';

export interface MatchedPair {
  pd_equipment_id: string;
  pd_tag: string;
  image_node_id: string;
  image_tag: string;
}
export interface UnmatchedPd {
  pd_equipment_id: string;
  pd_tag: string;
  reason: string;
}
export interface ExtraImage {
  image_node_id: string;
  image_tag: string;
}

export interface MatchDetails {
  matched: MatchedPair[];
  unmatched_pd: UnmatchedPd[];
  extra_image: ExtraImage[];
}

export function MatchRelationView({
  matchDetails,
  onLocate,
}: {
  matchDetails: MatchDetails;
  onLocate?: (nodeId: string, side: 'pd' | 'image') => void;
}) {
  const pdItems = useMemo(() => {
    const matched = matchDetails.matched.map((m) => ({
      id: m.pd_equipment_id,
      tag: m.pd_tag,
      pairId: m.image_node_id,
      status: 'matched' as const,
    }));
    const unmatched = matchDetails.unmatched_pd.map((u) => ({
      id: u.pd_equipment_id,
      tag: u.pd_tag,
      pairId: null,
      status: 'unmatched' as const,
    }));
    return [...matched, ...unmatched];
  }, [matchDetails]);

  const imgItems = useMemo(() => {
    const matched = matchDetails.matched.map((m) => ({
      id: m.image_node_id,
      tag: m.image_tag,
      pairId: m.pd_equipment_id,
      status: 'matched' as const,
    }));
    const extra = matchDetails.extra_image.map((e) => ({
      id: e.image_node_id,
      tag: e.image_tag,
      pairId: null,
      status: 'extra' as const,
    }));
    return [...matched, ...extra];
  }, [matchDetails]);

  // 连线 y 坐标：按 matched 索引等分（简化版，实际行高一致时近似对齐）
  const lineY = (index: number, total: number) =>
    total > 0 ? `${((index + 0.5) * 100) / total}%` : '50%';

  return (
    <div className="flex h-full">
      {/* 左栏：工艺说明设备 */}
      <div className="w-40 shrink-0 overflow-y-auto border-r border-border bg-bg-2/40 p-2">
        <div className="mb-2 text-[10px] font-bold text-text-3">工艺说明设备</div>
        {pdItems.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => onLocate?.(item.id, 'pd')}
            className={`mb-1 w-full rounded border px-2 py-1 text-left text-[11px] ${
              item.status === 'matched' ? 'border-green/30 bg-green/5 text-text' : 'border-orange/30 bg-orange/5 text-orange'
            } hover:bg-bg-3/40`}
          >
            <span className="font-mono font-bold">{item.tag || item.id}</span>
          </button>
        ))}
      </div>

      {/* 中间连线 SVG */}
      <div className="relative flex-1">
        <svg className="absolute inset-0 h-full w-full" preserveAspectRatio="none">
          {matchDetails.matched.map((_, i) => (
            <line
              key={i}
              x1="0"
              y1={lineY(i, pdItems.length)}
              x2="100%"
              y2={lineY(i, imgItems.length)}
              stroke="#18a581"
              strokeWidth="1.2"
            />
          ))}
        </svg>
      </div>

      {/* 右栏：图纸设备 */}
      <div className="w-40 shrink-0 overflow-y-auto border-l border-border bg-bg-2/40 p-2">
        <div className="mb-2 text-[10px] font-bold text-text-3">图纸设备</div>
        {imgItems.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => onLocate?.(item.id, 'image')}
            className={`mb-1 w-full rounded border px-2 py-1 text-left text-[11px] ${
              item.status === 'matched' ? 'border-green/30 bg-green/5 text-text' : 'border-border bg-bg/60 text-text-3'
            } hover:bg-bg-3/40`}
          >
            <span className="font-mono font-bold">{item.tag || item.id}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
