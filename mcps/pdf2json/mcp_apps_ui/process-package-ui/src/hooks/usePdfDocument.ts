/**
 * 加载整份 PDF 文档为 data URL（通过 host 的 read_pdf 工具）。
 *
 * 用于 process_package 在 PDF 接收后直接在 UI 渲染 PDF 内容：
 * 调 read_pdf 返回 application/pdf 的 base64，UI 端用 <iframe> 嵌入渲染。
 */
import { useEffect, useState } from 'react';
import { mcpApp } from '@/core/mcpApp';

export interface PdfDocumentState {
  url: string | null;
  loading: boolean;
  error: string | null;
}

export function usePdfDocument(pdfPath?: string | null): PdfDocumentState {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!pdfPath) {
      setUrl(null);
      setLoading(false);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    mcpApp
      .callTool('read_pdf', { path: pdfPath })
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
            setError('read_pdf 返回格式异常');
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
  }, [pdfPath]);

  return { url, loading, error };
}