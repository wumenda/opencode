/**
 * 读取 PDF 指定页为 data URL（通过扩展后的 read_image，支持 page_index）。
 *
 * 用于 process_package 章节原图预览：传入 pdf_path + page_index，
 * 调 read_image 渲染该页为 PNG 返回 base64。
 */
import { useEffect, useState } from 'react';
import { mcpApp } from '@/core/mcpApp';

export interface PdfPageImageState {
  url: string | null;
  loading: boolean;
  error: string | null;
}

export function usePdfPageImage(
  pdfPath?: string | null,
  pageIndex?: number | null,
): PdfPageImageState {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!pdfPath || pageIndex == null) {
      setUrl(null);
      setLoading(false);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    mcpApp
      .callTool('read_image', { path: pdfPath, page_index: pageIndex })
      .then((result) => {
        const sc = result.structuredContent as
          | { mime_type?: string; data_base64?: string }
          | undefined;
        if (!cancelled) {
          if (sc?.data_base64 && sc?.mime_type) {
            setUrl(`data:${sc.mime_type};base64,${sc.data_base64}`);
            setError(null);
          } else {
            setUrl(null);
            setError('read_image 返回格式异常');
          }
          setLoading(false);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setUrl(null);
          setError(e instanceof Error ? e.message : String(e));
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [pdfPath, pageIndex]);

  return { url, loading, error };
}
