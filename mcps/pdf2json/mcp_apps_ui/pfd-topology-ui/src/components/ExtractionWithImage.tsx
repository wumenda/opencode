/**
 * 提取阶段布局：左侧源图（提取开始即显示）+ 右侧 ExtractionProgress。
 *
 * 替代 6 个页面 `!raw && <ExtractionProgress />` 的纯占位，
 * 让用户在提取中即可核对图纸是否选对。
 *
 * 注：useToolImage 返回 data URL，直接用 <img> 渲染，避免 SourceImageViewer
 * 内部再次调用 read_image 造成重复请求。
 */
import { useToolImage } from '@/patterns/image';
import { ExtractionProgress } from './ExtractionProgress';

interface ExtractionWithImageProps {}

export function ExtractionWithImage({}: ExtractionWithImageProps) {
  const { imageUrl, loading, error } = useToolImage();

  return (
    <div className="grid h-full grid-cols-[1fr_360px] overflow-hidden">
      {/* 左：源图（提取中即可加载，progress.uiEvent.image_paths 最早可用） */}
      <div className="border-r border-border bg-bg">
        {loading && (
          <div className="flex h-full items-center justify-center text-sm text-text-3">
            加载源图中…
          </div>
        )}
        {error && !loading && (
          <div className="m-4 rounded border border-red/30 bg-red/5 p-3 text-xs text-red">
            源图加载失败：{error}
          </div>
        )}
        {!loading && !error && imageUrl && (
          <div className="h-full overflow-auto bg-bg p-3">
            <img src={imageUrl} alt="源图" className="max-h-full max-w-full" />
          </div>
        )}
        {!loading && !error && !imageUrl && (
          <div className="flex h-full items-center justify-center text-sm text-text-3">
            等待源图路径…
          </div>
        )}
      </div>
      {/* 右：事件时间线 */}
      <ExtractionProgress />
    </div>
  );
}
