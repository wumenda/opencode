"""
Base class for all experts in v1 architecture
"""

import threading
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from PIL import Image

from src.core import VisionAPIClient, Settings, LoggerMixin
from src.core.infra.exceptions import (
    APIError,
    CancelledByClientError,
    ParseError,
    ImageProcessingError,
    PFDAnalysisError,
)
from src.core.io.json_utils import parse_json_with_recovery, ParseResult
from src.agent.preprocessor import ExpertImagePreprocessor, ExpertType
from src.agent.models import ExpertOutput

EXPERT_TYPE_MAPPING = {
    "equipment": ExpertType.EQUIPMENT,
    "boundary_node": ExpertType.BOUNDARY_NODE,
    "drawing_info": ExpertType.DRAWING_INFO,
    "topology": ExpertType.TOPOLOGY,
    "pfd_topology": ExpertType.PFD_TOPOLOGY,
    "plant_unit": ExpertType.PLANT_UNIT,
    "plant_unit_topology": ExpertType.PLANT_UNIT_TOPOLOGY,
    "plant_unit_topology_one_by_one": ExpertType.PLANT_UNIT_TOPOLOGY_ONE_BY_ONE,
    "plant_unit_drawing_type": ExpertType.PLANT_UNIT_DRAWING_TYPE,
    "reactor_assembly": ExpertType.REACTOR_ASSEMBLY,
    "column_assembly": ExpertType.COLUMN_ASSEMBLY,
    "equipment_type": ExpertType.EQUIPMENT_TYPE,
    "process_description_topology": ExpertType.PROCESS_DESCRIPTION_TOPOLOGY,
    "process_package": ExpertType.PROCESS_PACKAGE,
    "intent_recognition": ExpertType.INTENT_RECOGNITION,
    "pfd_reflux": ExpertType.PFD_REFLUX,
}


class BaseExpert(ABC, LoggerMixin):
    """
    Abstract base class for all PFD analysis experts
    """

    expert_type: str = "base"

    def __init__(
        self,
        settings: Settings,
        enable_preprocessing: Optional[bool] = None,
        client: Optional[VisionAPIClient] = None,
        preprocessor: Optional[ExpertImagePreprocessor] = None,
        prompt_version: Optional[str] = None,
    ) -> None:
        self.settings = settings
        self.client = client or VisionAPIClient(self.settings)
        self.max_image_size: int = self.settings.get_expert_image_size(self.expert_type)

        self.provider_config, self.expert_config = self.settings.get_expert_provider_config(
            self.expert_type
        )
        if enable_preprocessing is None:
            enable_preprocessing = self.expert_config.enable_preprocessing
        self.enable_preprocessing = enable_preprocessing

        self.preprocessor = preprocessor or (
            ExpertImagePreprocessor()
            if self.enable_preprocessing
            else None
        )

        self._prompt_version = prompt_version or self.settings.get_expert_prompt_version(
            self.expert_type
        )

        self._cancel_event: Optional[threading.Event] = None

        self._validate_settings()
        self._log_initialization()

    def _validate_settings(self) -> None:
        if not self.provider_config.api_key:
            raise ValueError(f"API key is required for expert '{self.expert_type}'")

    def _log_initialization(self) -> None:
        self.logger.info("%s initialized", self.__class__.__name__)
        self.logger.debug(
            "Provider: %s, Model: %s, Max image size: %s",
            self.provider_config.name,
            self.expert_config.model,
            self.max_image_size,
        )
        if self.enable_preprocessing:
            expert_enum = EXPERT_TYPE_MAPPING.get(self.expert_type)
            if expert_enum:
                strategy = ExpertImagePreprocessor.get_strategy(expert_enum)
                strategy_desc = ExpertImagePreprocessor.get_strategy_description(expert_enum)
                self.logger.debug(
                    f"Preprocessing enabled: {[m.value for m in strategy]} - {strategy_desc}"
                )

    @abstractmethod
    def _extract(
        self, image_path: str, context: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]: ...

    @abstractmethod
    def _parse(
        self, raw_response: str, context: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]: ...

    def _build_prompt(self, context: Optional[dict[str, Any]] = None) -> str:
        return ""

    def _call_vlm(
        self,
        image: Union[str, Image.Image],
        context: Optional[dict[str, Any]] = None,
        reference_image_paths: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        prompt = self._build_prompt(context)

        # 取消检查点：LLM 调用前
        if self._cancel_event and self._cancel_event.is_set():
            raise CancelledByClientError(
                f"客户端取消（{self.expert_type} VLM 调用前）"
            )

        if isinstance(image, Image.Image):
            raw_response, image_metadata, reasoning_content = self.client.call_api_with_image(
                image=image,
                prompt=prompt,
                provider_config=self.provider_config,
                expert_config=self.expert_config,
                max_dimension=self.max_image_size,
            )
        else:
            raw_response, image_metadata, reasoning_content = (
                self.client.call_api_with_expert_config(
                    image,
                    prompt,
                    self.provider_config,
                    self.expert_config,
                    max_dimension=self.max_image_size,
                    reference_image_paths=reference_image_paths,
                )
            )

        # 取消检查点：LLM 调用后
        if self._cancel_event and self._cancel_event.is_set():
            raise CancelledByClientError(
                f"客户端取消（{self.expert_type} VLM 调用后）"
            )

        return {
            "raw_response": raw_response,
            "image_metadata": image_metadata,
            "reasoning_content": reasoning_content,
        }

    def _parse_json_with_recovery(self, raw_response: str) -> ParseResult:
        return parse_json_with_recovery(raw_response, expert_type=self.expert_type)

    def analyze(
        self,
        image_path: str,
        context: Optional[dict[str, Any]] = None,
        loaded_image: Optional[Image.Image] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> ExpertOutput:
        self._cancel_event = cancel_event
        image_path_obj = Path(image_path)
        if not image_path or (not image_path_obj.exists() and loaded_image is None):
            raise PFDAnalysisError(f"Image file not found: {image_path}")

        self.logger.info(f"Starting analysis: {image_path}")

        image_input: Union[str, Image.Image] = loaded_image or image_path
        temp_file_path = None

        try:
            self._current_image_size = self._resolve_image_size(image_input)

            if not self.settings.get_expert_inject_image_size(self.expert_type):
                self._current_image_size = None

            if self.enable_preprocessing and self.preprocessor:
                processed = self._preprocess_image(image_input)
                if isinstance(processed, Image.Image):
                    image_input = processed
                elif isinstance(processed, str) and processed != image_path:
                    self.logger.info(f"Using preprocessed image: {processed}")
                    temp_file_path = processed
                    image_input = processed

                if isinstance(image_input, Image.Image):
                    self._current_image_size = (
                        image_input.size
                        if self.settings.get_expert_inject_image_size(self.expert_type)
                        else None
                    )

            if isinstance(image_input, Image.Image):
                extracted = self._extract_from_memory(image_input, context)
            else:
                extracted = self._extract(str(image_input), context)

            raw_response = extracted.get("raw_response", "")
            image_metadata = extracted.get("image_metadata")
            reasoning_content = extracted.get("reasoning_content")

            if reasoning_content and self.settings.save_thinking:
                self._save_thinking_content(reasoning_content, image_path)

            parsed = self._parse(raw_response, context)

            return ExpertOutput(
                expert_type=self.expert_type,
                success=True,
                data=parsed,
                image_metadata=image_metadata,
                reasoning_content=reasoning_content,
                warnings=parsed.get("warnings", []),
            )

        except APIError as e:
            self.logger.error(f"API call failed for {self.expert_type}: {e}")
            raise
        except ParseError as e:
            self.logger.error(f"Parse failed for {self.expert_type}: {e}")
            raise
        except ImageProcessingError as e:
            self.logger.error(f"Image processing failed for {self.expert_type}: {e}")
            raise
        except PFDAnalysisError as e:
            self.logger.error(f"Analysis error in {self.expert_type}: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in {self.expert_type}: {e}")
            raise PFDAnalysisError(f"Unexpected error in {self.expert_type}: {e}") from e
        finally:
            self._cancel_event = None
            self._current_image_size = None
            if temp_file_path and Path(temp_file_path).exists():
                if self.settings.keep_temp_files:
                    self.logger.info(f"Keeping temporary file for debugging: {temp_file_path}")
                else:
                    try:
                        Path(temp_file_path).unlink()
                        self.logger.debug(f"Cleaned up temporary file: {temp_file_path}")
                    except Exception as e:
                        self.logger.warning(f"Failed to clean up temporary file: {e}")

    def _resolve_image_size(
        self, image_input: Union[str, Image.Image]
    ) -> Optional[tuple[int, int]]:
        try:
            if isinstance(image_input, Image.Image):
                return image_input.size
            if not image_input:
                return None
            with Image.open(image_input) as img:
                return img.size
        except Exception as e:
            self.logger.warning(f"Failed to resolve image size: {e}")
            return None

    def _extract_from_memory(
        self, image: Image.Image, context: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        return self._call_vlm(image=image, context=context)

    def _save_thinking_content(self, reasoning_content: str, image_path: str) -> None:
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            image_name = Path(image_path).stem
            filename = f"{timestamp}_{self.expert_type}_{image_name}.md"
            output_path = self.settings.thinking_output_dir / filename

            output_path.parent.mkdir(parents=True, exist_ok=True)

            content = f"# Thinking Process - {self.expert_type}\n\n"
            content += f"**Image**: {image_path}\n"
            content += f"**Timestamp**: {datetime.now().isoformat()}\n\n"
            content += "---\n\n"
            content += reasoning_content

            output_path.write_text(content, encoding="utf-8")
            self.logger.info(f"Saved thinking content to: {output_path}")
        except Exception as e:
            self.logger.warning(f"Failed to save thinking content: {e}")

    def _preprocess_image(self, image_input: Union[str, Image.Image]) -> Union[str, Image.Image]:
        expert_enum = EXPERT_TYPE_MAPPING.get(self.expert_type)
        if not expert_enum:
            self.logger.warning(f"Unknown expert type: {self.expert_type}, skipping preprocessing")
            return image_input

        strategy = ExpertImagePreprocessor.get_strategy(expert_enum)
        if not strategy:
            self.logger.debug(f"No preprocessing strategy for {self.expert_type}")
            return image_input

        try:
            processed = self.preprocessor.preprocess(
                image_input, expert_enum
            )
            self.logger.debug(f"Image preprocessed for {self.expert_type}")
            return processed
        except Exception as e:
            self.logger.warning(f"Preprocessing failed, using original image: {e}")
            return image_input
