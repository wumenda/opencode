"""PDF section extractor for process package documents.

A process package PDF may contain 100+ pages. This module extracts text
page-by-page from a native (text-based) PDF, detects section headings, and
returns the full content of sections whose titles contain the given keywords.

The key difference from naive page-level keyword matching: when a keyword
matches a section heading (e.g. "工序说明"), **all pages** in that section
are returned — even pages that do not themselves contain the keyword.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from src.core import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Heading detection
# ---------------------------------------------------------------------------

# Level 1: 第X章 / 第X节 / 第X部分 / 附录A
_HEADING_L1 = re.compile(
    r"^(第[一二三四五六七八九十百千]+[章部分节]|附录[A-Za-z]?)\s*(.*)"
)
# Level 3: X.Y.Z title  (check before L2)
_HEADING_L3 = re.compile(r"^(\d+)\.(\d+)\.(\d+)\s+(.+)")
# Level 2: X.Y title  (not X.Y.Z)
_HEADING_L2 = re.compile(r"^(\d+)\.(\d+)(?!\.\d)\s+(.+)")
# TOC lines: heading text followed by dots and a page number, e.g.
#   "第二章  工序说明 ....................... 5"
_TOC_LINE = re.compile(r"\.{3,}\s*\d+\s*$")


def _detect_heading(line: str) -> Optional[tuple[int, str]]:
    """Return ``(heading_level, full_line)`` if *line* looks like a heading.

    Level 1 is the highest (chapters).  Lower levels are more specific
    subsections.  Table-of-contents lines (with dot leaders + page numbers)
    are rejected.
    """
    stripped = line.strip()
    if not stripped or len(stripped) > 80:
        # Headings are rarely longer than 80 chars; skip body paragraphs.
        return None

    # Reject TOC entries like "第二章  工序说明 ........ 5"
    if _TOC_LINE.search(stripped):
        return None

    m = _HEADING_L1.match(stripped)
    if m:
        return 1, stripped

    m = _HEADING_L3.match(stripped)
    if m:
        return 3, stripped

    m = _HEADING_L2.match(stripped)
    if m:
        return 2, stripped

    return None


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class PdfPageContent(BaseModel):
    """Single page text content extracted from a PDF."""

    model_config = ConfigDict(frozen=False)

    page_number: int  # 1-based
    text: str


class PdfSection(BaseModel):
    """A section spanning one or more pages, delimited by headings."""

    model_config = ConfigDict(frozen=False)

    title: str = ""
    level: int = 0  # heading level (1=highest); 0 = untitled (before first heading)
    start_page: int  # 1-based, inclusive
    end_page: int  # 1-based, inclusive
    pages: list[PdfPageContent] = Field(default_factory=list)

    @property
    def combined_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text.strip())


class PdfSectionResult(BaseModel):
    """Result of filtering a PDF by keywords."""

    model_config = ConfigDict(frozen=False)

    pdf_path: str
    total_pages: int = 0
    keywords: list[str] = Field(default_factory=list)
    matched_sections: list[PdfSection] = Field(default_factory=list)
    matched_pages: list[PdfPageContent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def combined_text(self) -> str:
        """Concatenated text of all matched pages (deduplicated), separated by blank lines."""
        seen: set[int] = set()
        texts: list[str] = []
        for section in self.matched_sections:
            for page in section.pages:
                if page.page_number not in seen:
                    seen.add(page.page_number)
                    if page.text.strip():
                        texts.append(page.text)
        # Also include standalone matched pages (body-text hits outside sections)
        for page in self.matched_pages:
            if page.page_number not in seen:
                seen.add(page.page_number)
                if page.text.strip():
                    texts.append(page.text)
        return "\n\n".join(texts)


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


class PdfSectionExtractor:
    """从文本型 PDF 中按章节抽取文本。

    定位策略（两级回退）::

        1. 优先读 PDF 书签目录 (doc.get_toc())  —— 最准、零成本
        2. 无书签时回退到正则标题检测           —— 识别 第X章 / X.Y / X.Y.Z

    通过 :meth:`extract_chapter` 按章节序号或标题关键词定位整个章节，
    返回该章节全部页面的文本。
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_all_pages(self, source: Union[str, bytes]) -> list[PdfPageContent]:
        """Extract text from every page of a native PDF.

        Args:
            source: Path to the PDF file or PDF bytes.

        Returns:
            List of :class:`PdfPageContent`, one per page (1-based numbering).
            Returns an empty list if the file is missing or PyMuPDF is not
            installed.
        """
        try:
            import fitz
        except ImportError:
            logger.warning(
                "PyMuPDF (fitz) not installed, cannot extract PDF text"
            )
            return []

        if isinstance(source, bytes):
            doc_factory = lambda: fitz.open(stream=source, filetype="pdf")
        else:
            pdf_path_obj = Path(source)
            if not pdf_path_obj.exists():
                logger.warning(f"PDF file not found: {source}")
                return []
            doc_factory = lambda: fitz.open(str(pdf_path_obj))

        pages: list[PdfPageContent] = []
        try:
            with doc_factory() as doc:
                for index, page in enumerate(doc, start=1):
                    text = page.get_text().strip()
                    pages.append(PdfPageContent(page_number=index, text=text))
            logger.info(f"Extracted text from {len(pages)} pages")
        except Exception as e:
            logger.error(f"Failed to extract PDF text: {e}")
            return []

        return pages

    def extract_chapter(
        self,
        source: Union[str, bytes],
        chapter_index: Optional[int] = None,
        chapter_title: Optional[str] = None,
    ) -> PdfSectionResult:
        """按章节序号或标题关键词抽取整个章节（单章抽取）。

        定位策略（两级回退）::

            1. 优先读 PDF 书签目录 (doc.get_toc())  -- 最准、零成本
            2. 无书签时回退到正则标题检测           -- 复用现有 _detect_all_headings

        Args:
            source: PDF 文件路径或 PDF bytes。
            chapter_index: 顶层章节序号（1-based），如 3 表示第 3 个顶层
                章节（对应"第X章"）。与 chapter_title 至少指定其一；同时
                指定时 index 优先。
            chapter_title: 章节标题关键词（子串匹配，大小写不敏感），
                匹配任意级别标题；多个命中时取第一个。

        Returns:
            :class:`PdfSectionResult`。``matched_sections`` 含匹配到的章节
            （通常为 1 个），``warnings`` 记录降级/未命中原因。
        """
        pdf_path = source if isinstance(source, str) else "<bytes>"
        warnings: list[str] = []
        if chapter_index is None and not chapter_title:
            raise ValueError(
                "extract_chapter 需要指定 chapter_index 或 chapter_title"
            )

        pages = self.extract_all_pages(source)
        if not pages:
            warnings.append(f"No text extracted from PDF: {pdf_path}")
            return PdfSectionResult(
                pdf_path=pdf_path,
                total_pages=0,
                keywords=[],
                matched_sections=[],
                matched_pages=[],
                warnings=warnings,
            )

        total_pages = len(pages)

        # 优先用 PDF 书签目录
        toc_headings = self._read_pdf_toc(source)
        if toc_headings:
            source = "PDF bookmark (TOC)"
            headings = toc_headings
        else:
            # 回退到正则标题检测
            source = "regex heading detection"
            headings = self._detect_all_headings(pages)
            if not headings:
                warnings.append(
                    "No PDF bookmarks and no headings detected; cannot "
                    "locate chapter."
                )
                return PdfSectionResult(
                    pdf_path=pdf_path,
                    total_pages=total_pages,
                    keywords=[],
                    matched_sections=[],
                    matched_pages=[],
                    warnings=warnings,
                )

        sections = self._group_into_sections(pages, headings)
        # 只保留有标题且有内容的章节（跳过 level 0 preamble）
        titled = [s for s in sections if s.level > 0 and s.pages]

        matched: Optional[PdfSection] = None
        if chapter_index is not None:
            # 顶层章节序号：按 level==1 计数
            top_level = [s for s in titled if s.level == 1]
            if not top_level:
                # 书签可能全非 1 级，退化用 titled 列表
                top_level = titled
            if 1 <= chapter_index <= len(top_level):
                matched = top_level[chapter_index - 1]
            else:
                warnings.append(
                    f"chapter_index={chapter_index} 超出范围，"
                    f"共 {len(top_level)} 个顶层章节"
                )
        elif chapter_title:
            kw = chapter_title.strip().lower()
            candidates = [s for s in titled if kw in s.title.lower()]
            if candidates:
                matched = candidates[0]
                if len(candidates) > 1:
                    warnings.append(
                        f"chapter_title 命中 {len(candidates)} 个章节: "
                        f"{[s.title for s in candidates]}，取第一个"
                    )
            else:
                warnings.append(
                    f"chapter_title='{chapter_title}' 未匹配到任何章节"
                )

        matched_sections: list[PdfSection] = []
        if matched:
            matched_sections.append(matched)
            logger.info(
                f"[{source}] matched chapter: {matched.title} "
                f"(第{matched.start_page}-{matched.end_page}页, "
                f"{len(matched.pages)}页)"
            )

        return PdfSectionResult(
            pdf_path=pdf_path,
            total_pages=total_pages,
            keywords=[chapter_title] if chapter_title else [],
            matched_sections=matched_sections,
            matched_pages=[],
            warnings=warnings,
        )

    def _read_pdf_toc(self, source: Union[str, bytes]) -> list[tuple[int, int, str]]:
        """读取 PDF 书签目录。

        Returns:
            ``[(page_number, level, title), ...]`` 按 PDF 中出现顺序。
            page_number 为 1-based。返回空列表表示无书签或读取失败。
        """
        try:
            import fitz
        except ImportError:
            logger.warning("PyMuPDF (fitz) not installed, cannot read TOC")
            return []
        try:
            if isinstance(source, bytes):
                with fitz.open(stream=source, filetype="pdf") as doc:
                    toc = doc.get_toc()  # [[level, title, page], ...]
            else:
                with fitz.open(str(source)) as doc:
                    toc = doc.get_toc()  # [[level, title, page], ...]
            return [(entry[2], entry[0], entry[1]) for entry in toc]
        except Exception as e:
            logger.warning(f"Failed to read PDF TOC: {e}")
            return []

    # ------------------------------------------------------------------
    # Internal: heading detection & section grouping
    # ------------------------------------------------------------------

    def _detect_all_headings(
        self, pages: list[PdfPageContent]
    ) -> list[tuple[int, int, str]]:
        """Scan every page for heading lines.

        Returns:
            List of ``(page_number, level, heading_text)`` tuples, in page
            order.  Duplicate headings on the same page (e.g. a page header
            that repeats the chapter title) are deduplicated — only the first
            occurrence is kept.
        """
        headings: list[tuple[int, int, str]] = []
        for page in pages:
            seen_on_page: set[str] = set()
            for line in page.text.split("\n"):
                result = _detect_heading(line)
                if result is not None:
                    level, text = result
                    # Normalise whitespace for dedup so "第二章  工序说明"
                    # and "第二章 工序说明" are treated as the same heading.
                    normalised = " ".join(text.split())
                    if normalised in seen_on_page:
                        continue
                    seen_on_page.add(normalised)
                    headings.append((page.page_number, level, text))
        return headings

    def _group_into_sections(
        self,
        pages: list[PdfPageContent],
        headings: list[tuple[int, int, str]],
    ) -> list[PdfSection]:
        """Group pages into sections based on heading positions.

        A section starts at the page where a heading appears and ends at the
        page just before the next heading of the same or higher level.
        """
        if not headings:
            return []

        page_map = {p.page_number: p for p in pages}
        sections: list[PdfSection] = []

        # Prepend a synthetic "preamble" section for pages before the first
        # heading (level 0).
        first_heading_page = headings[0][0]
        if first_heading_page > 1:
            preamble_pages = [
                page_map[i] for i in range(1, first_heading_page) if i in page_map
            ]
            if preamble_pages:
                sections.append(
                    PdfSection(
                        title="",
                        level=0,
                        start_page=1,
                        end_page=first_heading_page - 1,
                        pages=preamble_pages,
                    )
                )

        for idx, (heading_page, level, heading_text) in enumerate(headings):
            # Find the end page: the page before the next heading at
            # the same or higher level.
            end_page = pages[-1].page_number  # default: last page
            for j in range(idx + 1, len(headings)):
                next_page, next_level, _ = headings[j]
                if next_level <= level:
                    # 同页出现同级标题时，end_page 至少为 heading_page（包含当前页）
                    end_page = max(next_page - 1, heading_page)
                    break

            # Collect pages in range [heading_page, end_page]
            section_pages = [
                page_map[i]
                for i in range(heading_page, end_page + 1)
                if i in page_map
            ]
            sections.append(
                PdfSection(
                    title=heading_text,
                    level=level,
                    start_page=heading_page,
                    end_page=end_page,
                    pages=section_pages,
                )
            )

        return sections
