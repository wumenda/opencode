from enum import Enum


class ExpertType(Enum):
    EQUIPMENT = "equipment"
    BOUNDARY_NODE = "boundary_node"
    DRAWING_INFO = "drawing_info"
    TOPOLOGY = "topology"
    PLANT_UNIT = "plant_unit"
    PLANT_UNIT_TOPOLOGY = "plant_unit_topology"
    PLANT_UNIT_TOPOLOGY_ONE_BY_ONE = "plant_unit_topology_one_by_one"
    PLANT_UNIT_DRAWING_TYPE = "plant_unit_drawing_type"
    REACTOR_ASSEMBLY = "reactor_assembly"
    COLUMN_ASSEMBLY = "column_assembly"
    EQUIPMENT_TYPE = "equipment_type"
    PROCESS_DESCRIPTION_TOPOLOGY = "process_description_topology"
    PFD_TOPOLOGY = "pfd_topology"
    PROCESS_PACKAGE = "process_package"
    INTENT_RECOGNITION = "intent_recognition"
    PFD_REFLUX = "pfd_reflux"


class PreprocessMethod(Enum):
    GRAYSCALE = "grayscale"
    CLAHE = "clahe"
    CLAHE_COLOR = "clahe_color"
    DENOISE = "denoise"
    DENOISE_COLOR = "denoise_color"
    THRESHOLD = "threshold"
    GLOBAL_THRESHOLD = "global_threshold"
    INVERT = "invert"
    DILATE = "dilate"
    ERODE = "erode"
    SHARPEN = "sharpen"
    SHARPEN_COLOR = "sharpen_color"
    EDGE_ENHANCE = "edge_enhance"
    BLUR = "blur"
    MEDIAN_DENOISE = "median_denoise"
    MORPH_CLOSE = "morph_close"
    SKELETONIZE = "skeletonize"
    CC_FILTER_TEXT = "cc_filter_text"
    RESIZE = "resize"
    ARROW_ENHANCE = "arrow_enhance"


METHOD_DESCRIPTIONS = {
    PreprocessMethod.GRAYSCALE: "转为灰度图",
    PreprocessMethod.CLAHE: "CLAHE 对比度增强（灰度）",
    PreprocessMethod.CLAHE_COLOR: "CLAHE 对比度增强（彩色，逐通道）",
    PreprocessMethod.DENOISE: "高斯去噪（灰度）",
    PreprocessMethod.DENOISE_COLOR: "双边滤波去噪（保色）",
    PreprocessMethod.THRESHOLD: "自适应阈值二值化",
    PreprocessMethod.GLOBAL_THRESHOLD: "全局阈值二值化",
    PreprocessMethod.INVERT: "像素值反转 (255 - x)",
    PreprocessMethod.DILATE: "膨胀（用于加粗线条）",
    PreprocessMethod.ERODE: "腐蚀（用于细化黑色线条）",
    PreprocessMethod.SHARPEN: "图像锐化以增强边缘（灰度）",
    PreprocessMethod.SHARPEN_COLOR: "图像锐化以增强边缘（彩色）",
    PreprocessMethod.EDGE_ENHANCE: "基于拉普拉斯算子的边缘增强",
    PreprocessMethod.BLUR: "高斯模糊（降噪与平滑）",
    PreprocessMethod.MEDIAN_DENOISE: "中值滤波去噪（去除椒盐噪声）",
    PreprocessMethod.MORPH_CLOSE: "形态学闭运算（用于桥接断裂的线条）",
    PreprocessMethod.SKELETONIZE: "基于形态学细化的骨架提取（Guo-Hall 算法）",
    PreprocessMethod.CC_FILTER_TEXT: "连通域过滤（去除小尺寸文字区域）",
    PreprocessMethod.RESIZE: "按专家配置的最大边长缩放图像（LANCZOS 插值）",
    PreprocessMethod.ARROW_ENHANCE: "箭头专用增强管线：灰度 → 锐化 → 全局阈值 → 反相 → 形态学闭运算 → 反相 → 腐蚀",
}
