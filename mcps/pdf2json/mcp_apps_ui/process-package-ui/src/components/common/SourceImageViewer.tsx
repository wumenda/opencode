/**
 * 左侧源图预览区：缩略图条（多页）+ 主图 + 可选 bbox 叠加层。
 *
 * - 单图模式：imagePaths 长度 ≤ 1，仅显示主图
 * - 多图模式：左侧缩略图条 + 主图，点击缩略图切换
 * - bboxOverlay：归一化坐标 [x1, y1, x2, y2]（0-1），叠加在主图上
 */
import { useState } from 'react';
import { useSourceImages } from '@/patterns/image';

export interface BboxOverlay {
  /** 归一化坐标 0-1。 */
  bbox: [number, number, number, number];
  label?: string;
  color?: string;
}

export function SourceImageViewer({
  imagePaths,
  bboxes = [],
  className = '',
}: {
  imagePaths: string[];
  bboxes?: BboxOverlay[];
  className?: string;
}) {
  const [activeIdx, setActiveIdx] = useState(0);
  const { urls, loading, error } = useSourceImages(imagePaths);
  const activeUrl = urls[activeIdx] ?? null;

  return (
    <div className={`flex h-full overflow-hidden ${className}`}>
      {/* 多页缩略图条 */}
      {imagePaths.length > 1 && (
        <div className="flex w-20 shrink-0 flex-col gap-1 overflow-y-auto border-r border-border bg-bg-2/40 p-1">
          {imagePaths.map((_, i) => (
            <button
              key={i}
              type="button"
              onClick={() => setActiveIdx(i)}
              className={`relative aspect-[3/4] w-full overflow-hidden rounded border transition ${
                i === activeIdx ? 'border-accent' : 'border-border hover:border-accent/50'
              } bg-bg`}
            >
              {urls[i] ? (
                <img src={urls[i]!} alt={`第 ${i + 1} 页`} className="h-full w-full object-cover" />
              ) : (
                <div className="flex h-full items-center justify-center text-[10px] text-text-3">{i + 1}</div>
              )}
            </button>
          ))}
        </div>
      )}

      {/* 主图区 */}
      <div className="relative flex-1 overflow-auto bg-bg">
        {loading && (
          <div className="flex h-full items-center justify-center text-xs text-text-3">加载源图中…</div>
        )}
        {error && !loading && (
          <div className="m-3 rounded border border-red/30 bg-red/5 p-2 text-[11px] text-red">
            源图加载失败：{error}
          </div>
        )}
        {!loading && !error && activeUrl && (
          <div className="relative inline-block">
            <img src={activeUrl} alt="源图" className="block max-h-full max-w-full" />
            {/* bbox 叠加层（归一化坐标 -> 百分比定位） */}
            {bboxes.length > 0 && (
              <svg className="absolute left-0 top-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
                {bboxes.map((b, i) => {
                  const [x1, y1, x2, y2] = b.bbox;
                  return (
                    <g key={i}>
                      <rect
                        x={x1 * 100}
                        y={y1 * 100}
                        width={(x2 - x1) * 100}
                        height={(y2 - y1) * 100}
                        fill="none"
                        stroke={b.color ?? '#3168ff'}
                        strokeWidth="0.4"
                        vectorEffect="non-scaling-stroke"
                      />
                      {b.label && (
                        <text
                          x={x1 * 100}
                          y={y1 * 100 - 0.5}
                          fontSize="2"
                          fill={b.color ?? '#3168ff'}
                        >
                          {b.label}
                        </text>
                      )}
                    </g>
                  );
                })}
              </svg>
            )}
          </div>
        )}
        {!loading && !error && !activeUrl && (
          <div className="flex h-full items-center justify-center text-xs text-text-3">
            无源图
          </div>
        )}
      </div>
    </div>
  );
}
