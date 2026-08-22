"""
PFD Topology Extractor - Core Module

This module provides core abstractions, configuration, and utilities
used throughout the PFD topology extraction system.
"""

from src.core.infra.config import Settings, load_project_env
from src.core.infra.logging import get_logger, setup_logging, LoggerMixin
from src.core.models import (
    NodeType,
    KeypointType,
    BoundaryType,
    PortDirection,
    PortCategory,
    EquipmentType,
    StreamPhase,
    STREAM_PHASE_ZH_MAP,
    Port,
    StreamCondition,
    PFDNode,
    PFDEquipmentNode,
    KeypointNode,
    BoundaryNode,
    StreamEdge,
    PFDDrawing,
    DrawingRef,
    CrossPageLink,
    PageGraphBundle,
    GlobalPFDGraph,
    MultiPageExtractionResult,
    DrawingDeserializer,
    NODE_TYPE_MAP,
)
from src.core.infra.exceptions import (
    PFDAnalysisError,
    AnalysisError,
    ConfigurationError,
    ImageProcessingError,
    APIError,
    ParseError,
    ValidationError,
    PFDFileNotFoundError,
    DirectoryNotFoundError,
)
from src.core.client import VisionAPIClient
from src.core.io.image_io import (
    encode_image,
    resize_image_if_needed,
)
from src.core.io.json_utils import (
    clean_json_text,
    parse_json_safely,
)
from src.core.utils import (
    save_json,
    load_json,
)
from src.core.io.image_utils import ImagePreprocessor
from src.core.infra.yaml_config import (
    load_yaml_config,
    deep_merge,
    resolve_env_vars,
)

__all__ = [
    "Settings",
    "load_project_env",
    "load_yaml_config",
    "deep_merge",
    "resolve_env_vars",
    "get_logger",
    "setup_logging",
    "LoggerMixin",
    "NodeType",
    "KeypointType",
    "BoundaryType",
    "PortDirection",
    "PortCategory",
    "EquipmentType",
    "StreamPhase",
    "STREAM_PHASE_ZH_MAP",
    "Port",
    "StreamCondition",
    "PFDNode",
    "PFDEquipmentNode",
    "KeypointNode",
    "BoundaryNode",
    "StreamEdge",
    "PFDDrawing",
    "DrawingRef",
    "CrossPageLink",
    "PageGraphBundle",
    "GlobalPFDGraph",
    "MultiPageExtractionResult",
    "DrawingDeserializer",
    "NODE_TYPE_MAP",
    "PFDAnalysisError",
    "AnalysisError",
    "ConfigurationError",
    "ImageProcessingError",
    "APIError",
    "ParseError",
    "ValidationError",
    "PFDFileNotFoundError",
    "DirectoryNotFoundError",
    "VisionAPIClient",
    "encode_image",
    "resize_image_if_needed",
    "clean_json_text",
    "parse_json_safely",
    "save_json",
    "load_json",
    "ImagePreprocessor",
]
