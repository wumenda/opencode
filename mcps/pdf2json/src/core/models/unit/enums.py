"""Enumeration types for PFD graph model."""

from enum import Enum


class NodeType(str, Enum):
    EQUIPMENT = "equipment"
    INSTRUMENT = "instrument"
    KEYPOINT = "keypoint"
    BOUNDARY = "boundary"


class KeypointType(str, Enum):
    SPLIT = "split"
    MERGE = "merge"
    ELBOW = "elbow"
    CROSSING_H = "crossing_h"
    CROSSING_V = "crossing_v"
    UNKNOWN = "unknown"
    INVALID = "invalid"


class BoundaryType(str, Enum):
    BOUNDARY_IN = "boundary_in"
    BOUNDARY_OUT = "boundary_out"
    CROSS_DRAWING_IN = "cross_drawing_in"
    CROSS_DRAWING_OUT = "cross_drawing_out"


class PortDirection(str, Enum):
    INPUT = "input"
    OUTPUT = "output"
    UNKNOWN = "unknown"


class PortCategory(str, Enum):
    PROCESS = "process"
    UTILITY = "utility"


class PortOrientation(str, Enum):
    """端口在设备外轮廓上的方位（上下左右）。"""

    TOP = "top"
    BOTTOM = "bottom"
    LEFT = "left"
    RIGHT = "right"
    UNKNOWN = "unknown"


class EquipmentType(str, Enum):
    PUMP = "pump"
    COMPRESSOR = "compressor"
    HEAT_EXCHANGER = "heat_exchanger"
    REACTOR = "reactor"
    DISTILLATION_COLUMN = "distillation_column"
    VESSEL = "vessel"
    TANK = "tank"
    FURNACE = "furnace"
    COOLER = "cooler"
    HEATER = "heater"
    MIXER = "mixer"
    SEPARATOR = "separator"
    OTHER = "other"


EQUIPMENT_TYPE_ZH_MAP: dict[str, str] = {
    "泵": "pump",
    "压缩机": "compressor",
    "换热器": "heat_exchanger",
    "反应器": "reactor",
    "精馏塔": "distillation_column",
    "容器": "vessel",
    "储罐": "tank",
    "加热炉": "furnace",
    "冷却器": "cooler",
    "加热器": "heater",
    "混合器": "mixer",
    "分离器": "separator",
    "其他": "other",
}


class InstrumentType(str, Enum):
    TI = "TI"
    PI = "PI"
    FI = "FI"
    LI = "LI"
    AI = "AI"
    TIC = "TIC"
    PIC = "PIC"
    FIC = "FIC"
    LIC = "LIC"
    AIC = "AIC"
    TT = "TT"
    PT = "PT"
    FT = "FT"
    LT = "LT"
    AT = "AT"
    TV = "TV"
    PV = "PV"
    FV = "FV"
    LV = "LV"
    AV = "AV"
    OTHER = "other"


class StreamPhase(str, Enum):
    LIQUID = "liquid"
    LIQUID_GAS = "liquid_gas"
    LIQUID_VAPOR = "liquid_vapor"
    LIQUID_GAS_VAPOR = "liquid_gas_vapor"
    VAPOR = "vapor"
    TWO_PHASE = "two_phase"
    GAS = "gas"
    SOLID = "solid"
    UNKNOWN = "unknown"


STREAM_PHASE_ZH_MAP: dict[str, str] = {
    "液相": "liquid",
    "液相气体": "liquid_gas",
    "液相蒸汽": "liquid_vapor",
    "液相汽体": "liquid_gas_vapor",
    "蒸汽": "vapor",
    "两相": "two_phase",
    "气体": "gas",
    "固体": "solid",
    "未知": "unknown",
}

KEYPOINT_TYPE_MAP: dict[str, KeypointType] = {
    "split": KeypointType.SPLIT,
    "merge": KeypointType.MERGE,
    "elbow": KeypointType.ELBOW,
    "crossing_h": KeypointType.CROSSING_H,
    "crossing_v": KeypointType.CROSSING_V,
    "unknown": KeypointType.UNKNOWN,
    "invalid": KeypointType.INVALID,
}
