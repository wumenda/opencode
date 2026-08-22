import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple

_logger = logging.getLogger(__name__)


class ParseResult:

    def __init__(
        self,
        data: Optional[dict[str, Any]],
        success: bool,
        recovery_level: int = 0,
        warnings: list[str] = None,
    ):
        self.data = data
        self.success = success
        self.recovery_level = recovery_level
        self.warnings = warnings or []


def clean_json_text(text: str) -> str:
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return text.strip()


def _save_failed_json_text(
    text: str,
    stage: str = "unknown",
    warnings: list[str] | None = None,
    expert_type: str | None = None,
) -> None:
    try:
        log_dir = Path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        file_path = log_dir / f"failed_json_{stage}_{timestamp}.txt"
        file_path.write_text(text, encoding="utf-8")
        _logger.info(f"Saved failed JSON text to {file_path}")
    except Exception as e:
        _logger.warning(f"Failed to save failed JSON text: {e}")


def _quote_unquoted_tilde_ranges(text: str) -> str:
    return re.sub(
        r"(:\s*)(-?\d+(?:\.\d+)?\s*~\s*-?\d+(?:\.\d+)?)(\s*[,}\]])",
        lambda match: f'{match.group(1)}"{match.group(2).replace(" ", "")}"{match.group(3)}',
        text,
    )


def _evaluate_fraction_expressions(text: str) -> str:
    def _replace_fraction(match: re.Match) -> str:
        numerator = float(match.group(2))
        denominator = float(match.group(3))
        if denominator == 0:
            return match.group(0)
        result = numerator / denominator
        if result == int(result):
            replacement = str(int(result))
        else:
            replacement = f"{result:.10g}"
        return f"{match.group(1)}{replacement}"

    return re.sub(
        r"([:\[,]\s*)(-?\d+(?:\.\d+)?)\s*/\s*(-?\d+(?:\.\d+)?)(?![/\w])",
        _replace_fraction,
        text,
    )


def _fix_unclosed_strings(text: str) -> str:
    result = []
    in_string = False
    escape = False

    for i, char in enumerate(text):
        if escape:
            result.append(char)
            escape = False
        elif char == "\\":
            result.append(char)
            escape = True
        elif char == '"':
            if not in_string:
                in_string = True
            else:
                in_string = False
            result.append(char)
        else:
            result.append(char)

    if in_string:
        result.append('"')

    return "".join(result)


def _extract_json_objects(text: str) -> list[str]:
    objects = []
    brace_count = 0
    start_idx = -1

    for i, char in enumerate(text):
        if char == "{":
            if brace_count == 0:
                start_idx = i
            brace_count += 1
        elif char == "}":
            brace_count -= 1
            if brace_count == 0 and start_idx != -1:
                objects.append(text[start_idx : i + 1])
                start_idx = -1

    return objects


def _repair_truncated_json(json_str: str) -> Tuple[str, bool]:
    open_stack: list[str] = []
    in_string = False
    escape = False

    for char in json_str:
        if escape:
            escape = False
        elif char == "\\" and in_string:
            escape = True
        elif char == '"' and not escape:
            in_string = not in_string
        elif not in_string:
            if char == "{":
                open_stack.append("}")
            elif char == "[":
                open_stack.append("]")
            elif char in ("}", "]"):
                if open_stack and open_stack[-1] == char:
                    open_stack.pop()

    if not open_stack:
        return json_str, False

    repaired = json_str + "".join(reversed(open_stack))
    return repaired, True


def _parse_individual_objects(text: str) -> Optional[dict[str, Any]]:
    objects = _extract_json_objects(text)

    if not objects:
        return None

    result = {}
    for obj_str in objects:
        try:
            obj = json.loads(obj_str)
            for key, value in obj.items():
                if key in result:
                    if isinstance(result[key], list):
                        result[key].append(value)
                    else:
                        result[key] = [result[key], value]
                else:
                    result[key] = value
        except json.JSONDecodeError:
            continue

    return result if result else None


def parse_json_safely(text: str, expert_type: str | None = None) -> Optional[dict[str, Any]]:
    result = parse_json_with_recovery(text, expert_type=expert_type)
    return result.data if result.success else None


def parse_json_with_recovery(text: str, expert_type: str | None = None) -> ParseResult:
    if not text or not isinstance(text, str):
        return ParseResult(data=None, success=False, warnings=["Empty or non-string input"])

    warnings = []

    cleaned = clean_json_text(text)

    json_start = cleaned.find("{")
    json_end = cleaned.rfind("}") + 1

    if json_start == -1:
        warnings.append("No JSON opening brace found")
        _save_failed_json_text(text, "stage1_no_json", warnings=warnings, expert_type=expert_type)

        individual_result = _parse_individual_objects(text)
        if individual_result:
            return ParseResult(
                data=individual_result,
                success=True,
                recovery_level=5,
                warnings=warnings + ["Recovered by extracting individual objects"],
            )
        return ParseResult(data=None, success=False, warnings=warnings)

    json_str_full = cleaned[json_start:]

    if json_end > json_start:
        json_str = cleaned[json_start:json_end]
    else:
        json_str = json_str_full

    try:
        parsed = json.loads(json_str)
        return ParseResult(data=parsed, success=True, recovery_level=0)
    except json.JSONDecodeError as e:
        warnings.append(f"Level 0 parsing failed: {str(e)}")

    try:
        repaired = _fix_unclosed_strings(json_str_full)
        repaired, _ = _repair_truncated_json(repaired)
        parsed = json.loads(repaired)
        return ParseResult(
            data=parsed,
            success=True,
            recovery_level=1,
            warnings=warnings
            + ["Recovered by fixing truncated JSON (unclosed strings + missing brackets)"],
        )
    except json.JSONDecodeError as e:
        warnings.append(f"Level 1 truncation recovery failed: {str(e)}")

    try:
        repaired = _quote_unquoted_tilde_ranges(json_str)
        repaired = re.sub(r",\s*}", "}", repaired)
        repaired = re.sub(r",\s*]", "]", repaired)
        parsed = json.loads(repaired)
        return ParseResult(
            data=parsed,
            success=True,
            recovery_level=2,
            warnings=warnings + ["Recovered by fixing trailing commas and tilde ranges"],
        )
    except json.JSONDecodeError as e:
        warnings.append(f"Level 2 recovery failed: {str(e)}")

    try:
        repaired = _evaluate_fraction_expressions(repaired)
        parsed = json.loads(repaired)
        return ParseResult(
            data=parsed,
            success=True,
            recovery_level=3,
            warnings=warnings + ["Recovered by evaluating fraction expressions"],
        )
    except json.JSONDecodeError as e:
        warnings.append(f"Level 3 recovery failed: {str(e)}")

    try:
        repaired = re.sub(r"(?<!\\)(?<!\")\"(?!\")", "'", repaired)
        repaired = re.sub(r"'([^']+)':", r'"\1":', repaired)
        parsed = json.loads(repaired)
        return ParseResult(
            data=parsed,
            success=True,
            recovery_level=4,
            warnings=warnings + ["Recovered by fixing quote issues"],
        )
    except json.JSONDecodeError as e:
        warnings.append(f"Level 4 recovery failed: {str(e)}")

    try:
        individual_result = _parse_individual_objects(text)
        if individual_result:
            return ParseResult(
                data=individual_result,
                success=True,
                recovery_level=5,
                warnings=warnings + ["Recovered by extracting individual objects"],
            )
    except Exception as e:
        warnings.append(f"Level 5 recovery failed: {str(e)}")

    _save_failed_json_text(text, "stage_final", warnings=warnings, expert_type=expert_type)
    return ParseResult(data=None, success=False, warnings=warnings)
