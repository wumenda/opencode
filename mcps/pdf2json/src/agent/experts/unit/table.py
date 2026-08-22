"""
Table Expert - Table extraction expert for structured data extraction
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from src.agent.experts.core.base import BaseExpert
from src.agent.prompts import get_prompt_builder, PromptContext
from src.core import parse_json_safely

if TYPE_CHECKING:
    from src.agent.preprocessor import ExpertImagePreprocessor
    from src.core import Settings, VisionAPIClient


class TableExpert(BaseExpert):
    """Expert for extracting structured table data from images."""

    expert_type = "table"

    def __init__(
        self,
        settings: Optional["Settings"] = None,
        process_description: str = "",
        table_type: str = "general",
        client: Optional["VisionAPIClient"] = None,
        preprocessor: Optional["ExpertImagePreprocessor"] = None,
    ) -> None:
        super().__init__(settings, client=client, preprocessor=preprocessor)
        self.process_description = process_description
        self.table_type = table_type
        self._prompt_builder = get_prompt_builder("table", self._prompt_version)

    def _build_prompt(self, context: Optional[dict[str, Any]] = None) -> str:
        prompt_context = PromptContext(
            process_description=self.process_description or "未提供工艺流程说明",
            extra={"table_type": self.table_type},
            image_size=getattr(self, "_current_image_size", None),
        )
        return self._prompt_builder.build(prompt_context)

    def _extract(self, image_path: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Extract table data from image."""

        self.logger.info(f"Extracting table data from: {image_path}")
        prompt = self._build_prompt(context)
        raw_response, image_metadata, _ = self.client.call_api_with_expert_config(
            image_path,
            prompt,
            self.provider_config,
            self.expert_config,
            max_dimension=self.max_image_size,
        )

        return {
            "raw_response": raw_response,
            "image_path": image_path,
            "image_metadata": image_metadata,
        }

    def _parse(self, raw_response: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Parse raw table response into structured data."""

        self.logger.info("Parsing table response")

        markdown_content = self._extract_markdown(raw_response)

        if markdown_content:
            return self._parse_markdown_table(markdown_content)

        result_json = parse_json_safely(raw_response, expert_type=self.expert_type)
        if result_json is not None:
            return self._parse_json_table(result_json)

        return {
            "table": [],
            "raw_content": raw_response,
            "warnings": ["Unable to parse table format"],
        }

    def _extract_markdown(self, content: str) -> Optional[str]:
        """Extract markdown table from response content."""

        lines = content.strip().split("\n")
        table_lines = []
        in_table = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("|") and stripped.endswith("|"):
                in_table = True
                table_lines.append(stripped)
            elif in_table and not stripped:
                break
            elif in_table and not stripped.startswith("|"):
                break

        if table_lines:
            return "\n".join(table_lines)
        return None

    def _parse_markdown_table(self, markdown: str) -> dict[str, Any]:
        """Parse markdown table into structured data."""

        lines = markdown.strip().split("\n")
        rows: list[list[str]] = []

        for line in lines:
            line = line.strip()
            if not line.startswith("|") or not line.endswith("|"):
                continue

            cells = [cell.strip() for cell in line[1:-1].split("|")]

            is_separator = all(
                set(cell.replace("-", "").replace(":", "")) == set() or cell == "" for cell in cells
            ) and any("-" in cell for cell in cells)

            if is_separator:
                continue

            rows.append(cells)

        if not rows:
            return {
                "table": [],
                "raw_content": markdown,
                "warnings": ["No valid table rows found"],
            }

        col_counts = [len(row) for row in rows]
        max_cols = max(col_counts)

        normalized_rows = []
        for row in rows:
            if len(row) < max_cols:
                row = row + [""] * (max_cols - len(row))
            normalized_rows.append(row)

        header = normalized_rows[0] if normalized_rows else []
        data_rows = normalized_rows[1:] if len(normalized_rows) > 1 else []

        return {
            "table": [
                {
                    "header": header,
                    "rows": data_rows,
                    "col_count": max_cols,
                    "row_count": len(data_rows),
                }
            ],
            "raw_content": markdown,
        }

    def _parse_json_table(self, json_data: dict[str, Any]) -> dict[str, Any]:
        """Parse JSON table format."""

        tables = []

        if "table" in json_data:
            for table in json_data["table"]:
                if isinstance(table, dict):
                    tables.append(
                        {
                            "header": table.get("header", []),
                            "rows": table.get("rows", []),
                            "col_count": table.get("col_count", 0),
                            "row_count": table.get("row_count", 0),
                        }
                    )
        elif "header" in json_data or "rows" in json_data:
            tables.append(
                {
                    "header": json_data.get("header", []),
                    "rows": json_data.get("rows", []),
                    "col_count": json_data.get("col_count", 0),
                    "row_count": json_data.get("row_count", 0),
                }
            )

        return {
            "table": tables,
            "raw_content": str(json_data),
        }
