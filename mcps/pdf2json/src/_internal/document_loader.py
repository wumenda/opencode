from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from src.core import get_logger

logger = get_logger(__name__)

# 设备位号正则：前缀(1-3字母) + 可选连字符 + 数字(2-5位) + 可选后缀(字母，可带/A形式)
# 示例：P-81001, E-201A, V305B, P-81004A/B, C-102
TAG_EXTRACTION_RE = re.compile(r"[A-Za-z]{1,3}-?\d{2,5}(?:[A-Za-z](?:/[A-Za-z])*)?")
# 严格位号正则（用于校验提取到的 tag 是否符合格式）
TAG_STRICT_RE = re.compile(r"^[A-Za-z]{1,3}-?\d{2,5}(?:[A-Za-z](?:/[A-Za-z])*)?$")
# 解析位号结构：前缀 + 数字 + 后缀
_TAG_PARSE_RE = re.compile(r"^([A-Za-z]+)-?(\d+)([A-Za-z](?:/[A-Za-z])*)?$")


@dataclass(frozen=True)
class EquipmentTableEntry:
    """工艺设备表中的一条记录。"""

    tag: str  # 设备位号，如 "P-81001"
    name: str = ""  # 设备名称（如有）
    raw_text: str = ""  # 原始文本行


def normalize_tag(tag: str) -> str:
    """归一化 tag 为基础形式：大写 + 去连字符 + 去前导零 + 去后缀。

    示例：
        P-81001  -> P81001
        p-81001a -> P81001
        E201B    -> E201
        V-305A/B -> V305

    这样 "P-81001" 与 "P81001A" 的基础形式不同（P81001 vs P81001），
    但通过 base_form 匹配可判断它们指向同一设备系列。
    """
    if not tag:
        return ""
    m = _TAG_PARSE_RE.match(tag.strip())
    if not m:
        # 无法解析结构，退化为大写 + 去连字符 + 去空白
        return tag.strip().upper().replace("-", "").replace(" ", "")
    prefix = m.group(1).upper()
    num = m.group(2).lstrip("0") or "0"
    return f"{prefix}{num}"


def normalize_tag_full(tag: str) -> str:
    """归一化 tag 为完整形式：大写 + 去连字符 + 去空白，保留后缀。

    示例：
        P-81001  -> P81001
        p-81001a -> P81001A
        E201B    -> E201B
        V-305A/B -> V305A/B
    """
    if not tag:
        return ""
    return tag.strip().upper().replace("-", "").replace(" ", "")


def _extract_name_after_tag(line: str, tag: str) -> str:
    """从行文本中提取位号之后的设备名称（简单启发式）。"""
    idx = line.find(tag)
    if idx < 0:
        return ""
    rest = line[idx + len(tag):].strip()
    # 去掉前导分隔符
    rest = rest.lstrip(" \t:-—、，,")
    # 取第一个连续中文/英文片段作为名称
    m = re.match(r"[\u4e00-\u9fffA-Za-z0-9（）()/]+", rest)
    return m.group(0) if m else ""


def load_process_description(source: Union[str, bytes]) -> str:
    """Load process description from PDF file path or bytes.

    Args:
        source: PDF file path (str) or PDF bytes.

    Returns:
        Extracted text content, or empty string if loading failed
    """
    try:
        import fitz

        if isinstance(source, bytes):
            doc = fitz.open(stream=source, filetype="pdf")
        else:
            path = Path(source)
            if not path.exists():
                logger.warning(f"Process description PDF not found: {source}")
                return ""
            doc = fitz.open(str(path))

        with doc:
            text_parts = []
            for page in doc:
                text = page.get_text()
                text_parts.append(text.strip())

        full_text = "\n\n".join(text_parts)
        logger.info(f"Loaded process description ({len(full_text)} characters)")
        return full_text

    except ImportError:
        logger.warning("PyMuPDF (fitz) not installed, cannot load process description PDF")
        return ""
    except Exception as e:
        logger.warning(f"Failed to load process description: {e}")
        return ""


def load_equipment_table_from_pdf(
    source: Union[str, bytes],
) -> list[EquipmentTableEntry]:
    """从工艺设备表 PDF 中提取设备位号记录。

    使用 PyMuPDF (fitz) 提取文本，按行扫描符合位号格式的 token。

    Args:
        source: 工艺设备表 PDF 文件路径或 PDF bytes

    Returns:
        设备表记录列表；若加载失败返回空列表
    """
    entries: list[EquipmentTableEntry] = []

    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.warning("PyMuPDF (fitz) not installed, cannot load equipment table PDF")
        return entries

    try:
        if isinstance(source, bytes):
            doc = fitz.open(stream=source, filetype="pdf")
        else:
            path = Path(source)
            if not path.exists():
                logger.warning(f"Equipment table PDF not found: {source}")
                return entries
            doc = fitz.open(str(path))

        seen_tags: set[str] = set()
        with doc:
            for page in doc:
                text = page.get_text()
                if not text:
                    continue
                for line in text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    # 在该行中查找所有符合位号格式的 token
                    matches = TAG_EXTRACTION_RE.findall(line)
                    for match in matches:
                        if not TAG_STRICT_RE.match(match):
                            continue
                        full = normalize_tag_full(match)
                        if full in seen_tags:
                            continue
                        seen_tags.add(full)
                        # 尝试提取设备名称：位号之后的中文/英文描述
                        name = _extract_name_after_tag(line, match)
                        entries.append(EquipmentTableEntry(
                            tag=match.strip(),
                            name=name,
                            raw_text=line,
                        ))
    except Exception as e:
        logger.warning(f"Failed to extract equipment table: {e}")
        return entries

    logger.info(f"Loaded {len(entries)} equipment entries")
    return entries


def load_equipment_table(source: Union[str, bytes]) -> Optional[list]:
    """Load equipment table entries from PDF file path or bytes.

    Args:
        source: PDF file path (str) or PDF bytes.

    Returns:
        List of EquipmentTableEntry or None if loading failed
    """
    try:
        if isinstance(source, bytes):
            entries = load_equipment_table_from_pdf(source)
        else:
            path = Path(source)
            if not path.exists():
                logger.warning(f"Equipment table PDF not found: {source}")
                return None
            entries = load_equipment_table_from_pdf(source)

        if entries:
            logger.info(f"Loaded {len(entries)} equipment entries")
        else:
            logger.warning(
                "Equipment table PDF loaded but 0 entries extracted. "
                "Check that the PDF contains a table with columns matching "
                "'位号/设备位号/tag' and tags matching pattern like 'P-81001'"
            )
        return entries
    except Exception as e:
        logger.warning(f"Failed to load equipment table: {e}")
        return None