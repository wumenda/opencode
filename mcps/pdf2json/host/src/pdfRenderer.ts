/**
 * 使用 pdf.js 在浏览器中渲染 PDF 指定页为 base64 PNG。
 *
 * 供 hostProtocol.ts 的 read_image 处理器调用，将 data/装置级/PFD.pdf 的
 * 各页渲染为真实底图，替代 buildPlaceholderImage 的占位 SVG。
 */
import * as pdfjsLib from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
// Vite ?url 后缀：返回 PDF 文件的 URL（dev 下为 /@fs/...，build 后为 hashed asset）
import pdfFileUrl from '../../data/装置级/PFD.pdf?url';
import processPackagePdfUrl from '../../data/装置级/1万吨异戊烯工艺包文字.pdf?url';

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl;

/** 已知 PDF 路径关键字 -> 打包内对应 PDF 资源 URL（read_pdf 按路径取档）。 */
const KNOWN_PDF_URLS: Record<string, string> = {
  '工艺包': processPackagePdfUrl,
};

export interface RenderedPage {
  mime_type: string;
  data_base64: string;
  width: number;
  height: number;
}

// 缓存已渲染的页面，避免重复渲染
const pageCache = new Map<number, RenderedPage>();
let pdfDocPromise: Promise<pdfjsLib.PDFDocumentProxy> | null = null;

async function loadPdf(): Promise<pdfjsLib.PDFDocumentProxy> {
  if (!pdfDocPromise) {
    pdfDocPromise = (async () => {
      // 先在主线程 fetch 整个 PDF 为 ArrayBuffer，再传给 pdf.js，
      // 避免 worker 通过 URL 发起 range request 被 Vite dev server 中断
      const response = await fetch(pdfFileUrl);
      if (!response.ok) throw new Error(`Failed to fetch PDF: ${response.status}`);
      const data = await response.arrayBuffer();
      return pdfjsLib.getDocument({ data }).promise;
    })();
  }
  return pdfDocPromise;
}

/** 根据 pdf_path 解析对应的打包内 PDF 资源 URL（未匹配则取 PFD.pdf）。 */
export function resolvePdfUrl(pdfPath?: string | null): string {
  if (!pdfPath) return pdfFileUrl;
  for (const key in KNOWN_PDF_URLS) {
    if (pdfPath.includes(key)) return KNOWN_PDF_URLS[key];
  }
  return pdfFileUrl;
}

/** 将 PDF 文件读为 base64（供 UI 直接嵌入加载整份 PDF）。 */
export async function readPdfBase64(pdfPath?: string | null): Promise<{
  mime_type: string;
  data_base64: string;
}> {
  const url = resolvePdfUrl(pdfPath);
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Failed to fetch PDF: ${response.status}`);
  const buf = await response.arrayBuffer();
  const bytes = new Uint8Array(buf);
  let binary = '';
  bytes.forEach((b) => (binary += String.fromCharCode(b)));
  return { mime_type: 'application/pdf', data_base64: btoa(binary) };
}

/** 渲染 PDF 指定页（0-based）为 base64 JPEG，结果会被缓存。 */
export async function renderPdfPage(pageIndex: number): Promise<RenderedPage> {
  const cached = pageCache.get(pageIndex);
  if (cached) return cached;

  const pdf = await loadPdf();
  const page = await pdf.getPage(pageIndex + 1); // pdf.js 页码从 1 开始

  // 使用 1x 缩放（约 72 DPI），避免图片过大导致 postMessage 传输失败
  const viewport = page.getViewport({ scale: 1 });

  const canvas = document.createElement('canvas');
  canvas.width = Math.floor(viewport.width);
  canvas.height = Math.floor(viewport.height);
  const context = canvas.getContext('2d');
  if (!context) throw new Error('无法获取 canvas 2d context');

  await page.render({ canvas, viewport }).promise;

  // 使用 JPEG 格式（quality 0.85），比 PNG 小得多，避免 postMessage 数据过大
  const dataUrl = canvas.toDataURL('image/jpeg', 0.85);
  const data_base64 = dataUrl.split(',')[1];

  const result: RenderedPage = {
    mime_type: 'image/jpeg',
    data_base64,
    width: canvas.width,
    height: canvas.height,
  };
  pageCache.set(pageIndex, result);
  return result;
}

/** 获取 PDF 总页数。 */
export async function getPdfPageCount(): Promise<number> {
  const pdf = await loadPdf();
  return pdf.numPages;
}
