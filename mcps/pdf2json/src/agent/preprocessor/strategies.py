from .enums import ExpertType, PreprocessMethod

EXPERT_STRATEGIES: dict[ExpertType, list[PreprocessMethod]] = {
    ExpertType.EQUIPMENT: [
    ],
    ExpertType.BOUNDARY_NODE: [

    ],
    ExpertType.DRAWING_INFO: [

    ],
    ExpertType.TOPOLOGY: [
        # PreprocessMethod.GRAYSCALE,
        # PreprocessMethod.CLAHE,
        # PreprocessMethod.SHARPEN,
    ],
    ExpertType.PLANT_UNIT: [
        PreprocessMethod.GRAYSCALE,
        PreprocessMethod.CLAHE,
        PreprocessMethod.SHARPEN,
        PreprocessMethod.THRESHOLD,
    ],
    ExpertType.PLANT_UNIT_TOPOLOGY: [
        PreprocessMethod.RESIZE,
    ],
    ExpertType.PLANT_UNIT_TOPOLOGY_ONE_BY_ONE: [
        PreprocessMethod.RESIZE,
    ],
    ExpertType.PLANT_UNIT_DRAWING_TYPE: [
        PreprocessMethod.RESIZE,
    ],
    ExpertType.REACTOR_ASSEMBLY: [
        PreprocessMethod.RESIZE,
    ],
    ExpertType.COLUMN_ASSEMBLY: [
        PreprocessMethod.RESIZE,
    ],
    ExpertType.EQUIPMENT_TYPE: [
        PreprocessMethod.RESIZE,
    ],
    ExpertType.PROCESS_DESCRIPTION_TOPOLOGY: [
    ],
    ExpertType.PFD_TOPOLOGY: [
    ],
    ExpertType.PROCESS_PACKAGE: [
    ],
    ExpertType.INTENT_RECOGNITION: [
    ],
    ExpertType.PFD_REFLUX: [
    ],
}

STRATEGY_DESCRIPTIONS = {
    ExpertType.EQUIPMENT: "Grayscale → CLAHE → Sharpen → Adaptive threshold",
    ExpertType.BOUNDARY_NODE: "Grayscale → CLAHE → Sharpen → Resize",
    ExpertType.DRAWING_INFO: "Color CLAHE → Bilateral denoise → Color sharpen",
    ExpertType.TOPOLOGY: "Grayscale → CLAHE → Sharpen",
    ExpertType.PLANT_UNIT: "Grayscale → CLAHE → Sharpen → Adaptive threshold",
    ExpertType.PLANT_UNIT_TOPOLOGY: "Resize",
    ExpertType.PLANT_UNIT_TOPOLOGY_ONE_BY_ONE: "Resize",
    ExpertType.PLANT_UNIT_DRAWING_TYPE: "Resize",
    ExpertType.REACTOR_ASSEMBLY: "Resize",
    ExpertType.COLUMN_ASSEMBLY: "Resize",
    ExpertType.EQUIPMENT_TYPE: "Resize",
    ExpertType.PROCESS_DESCRIPTION_TOPOLOGY: "No preprocessing",
    ExpertType.PFD_TOPOLOGY: "Grayscale -> CLAHE -> Sharpen",
    ExpertType.PROCESS_PACKAGE: "No preprocessing",
    ExpertType.INTENT_RECOGNITION: "No preprocessing",
    ExpertType.PFD_REFLUX: "No preprocessing",
}
