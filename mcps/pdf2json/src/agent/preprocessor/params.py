from typing import Optional

import numpy as np


class PreprocessParams:

    def __init__(
        self,
        clahe_clip_limit: float = 2.0,
        clahe_tile_size: tuple[int, int] = (8, 8),
        denoise_kernel: tuple[int, int] = (3, 3),
        denoise_sigma: float = 0.0,
        threshold_block_size: int = 21,
        threshold_c: int = 2,
        global_threshold_value: int = 205,
        dilate_kernel: tuple[int, int] = (2, 2),
        dilate_iterations: int = 1,
        erode_kernel: tuple[int, int] = (2, 2),
        erode_iterations: int = 1,
        sharpen_kernel: Optional[np.ndarray] = None,
        blur_kernel: tuple[int, int] = (5, 5),
        blur_sigma: float = 2.0,
        median_kernel: int = 3,
        morph_close_kernel: tuple[int, int] = (2, 2),
        morph_close_iterations: int = 1,
        cc_min_area: int = 50,
        cc_max_area: Optional[int] = None,
        cc_aspect_ratio_threshold: float = 5.0,
        arrow_global_threshold_value: int = 200,
        arrow_close_kernel: tuple[int, int] = (3, 3),
        arrow_erode_kernel: tuple[int, int] = (2, 2),
        arrow_erode_iterations: int = 1,
    ):
        self.clahe_clip_limit = clahe_clip_limit
        self.clahe_tile_size = clahe_tile_size
        self.denoise_kernel = denoise_kernel
        self.denoise_sigma = denoise_sigma
        self.threshold_block_size = threshold_block_size
        self.threshold_c = threshold_c
        self.global_threshold_value = global_threshold_value
        self.dilate_kernel = dilate_kernel
        self.dilate_iterations = dilate_iterations
        self.erode_kernel = erode_kernel
        self.erode_iterations = erode_iterations
        self.sharpen_kernel = (
            sharpen_kernel
            if sharpen_kernel is not None
            else np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
        )
        self.blur_kernel = blur_kernel
        self.blur_sigma = blur_sigma
        self.median_kernel = median_kernel
        self.morph_close_kernel = morph_close_kernel
        self.morph_close_iterations = morph_close_iterations
        self.cc_min_area = cc_min_area
        self.cc_max_area = cc_max_area
        self.cc_aspect_ratio_threshold = cc_aspect_ratio_threshold
        self.arrow_global_threshold_value = arrow_global_threshold_value
        self.arrow_close_kernel = arrow_close_kernel
        self.arrow_erode_kernel = arrow_erode_kernel
        self.arrow_erode_iterations = arrow_erode_iterations


PARAMS_4096 = PreprocessParams(
    clahe_clip_limit=2.0,
    clahe_tile_size=(6, 6),
    denoise_kernel=(3, 3),
    denoise_sigma=0.5,
    threshold_block_size=11,
    threshold_c=1,
    global_threshold_value=200,
    dilate_kernel=(2, 2),
    dilate_iterations=1,
    erode_kernel=(2, 2),
    erode_iterations=1,
    morph_close_kernel=(2, 2),
    morph_close_iterations=1,
    blur_kernel=(3, 3),
    blur_sigma=1.0,
    arrow_global_threshold_value=200,
    arrow_close_kernel=(3, 3),
    arrow_erode_kernel=(2, 2),
    arrow_erode_iterations=1,
)

DEFAULT_PARAMS = PARAMS_4096
