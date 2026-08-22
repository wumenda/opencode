from pathlib import Path
from typing import Any, Optional, Union

import numpy as np
from PIL import Image

from src.core.infra.config import Settings

from .enums import ExpertType, METHOD_DESCRIPTIONS, PreprocessMethod
from .params import DEFAULT_PARAMS, PreprocessParams
from .strategies import EXPERT_STRATEGIES, STRATEGY_DESCRIPTIONS

Image.MAX_IMAGE_PIXELS = 500_000_000
STANDARD_SIZE = 10240


class ExpertImagePreprocessor:

    def __init__(
        self,
        custom_strategies: Optional[dict[ExpertType, list[PreprocessMethod]]] = None,
        params: Optional[PreprocessParams] = None,
        expert_image_sizes: Optional[dict[str, int]] = None,
    ):
        self.strategies = custom_strategies or EXPERT_STRATEGIES
        self.params = params or DEFAULT_PARAMS
        self._expert_image_sizes = expert_image_sizes
        self._validate_strategies()

    def _validate_strategies(self) -> None:
        for expert_type, methods in self.strategies.items():
            for method in methods:
                if not isinstance(method, PreprocessMethod):
                    raise ValueError(
                        f"Invalid method {method} for expert {expert_type}. "
                        f"Must be a PreprocessMethod enum."
                    )

    def _get_expert_max_size(self, expert_type: ExpertType) -> int:
        if self._expert_image_sizes is not None:
            return self._expert_image_sizes.get(expert_type.value, 2048)
        settings = Settings.from_env()
        return settings.get_expert_image_size(expert_type.value)

    def preprocess(
        self,
        image: Union[str, Path, Image.Image, np.ndarray],
        expert_type: ExpertType,
    ) -> Image.Image:
        img = self._load_image(image)

        methods = self.strategies.get(expert_type, [])

        if methods:
            img_array = np.array(img)
            for method in methods:
                img_array = self._apply_method(img_array, method, expert_type=expert_type)
            img = Image.fromarray(img_array)

        img = self._resize_image(img, expert_type)

        return img

    def preprocess_and_save(
        self,
        image: Union[str, Path, Image.Image, np.ndarray],
        output_path: Union[str, Path],
        expert_type: ExpertType,
    ) -> Path:
        processed = self.preprocess(image, expert_type)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        processed.save(output_path)
        return output_path

    def preprocess_for_all_experts(
        self,
        image: Union[str, Path, Image.Image, np.ndarray],
        output_dir: Union[str, Path],
        base_name: str = "processed",
    ) -> dict[ExpertType, Path]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        results = {}
        for expert_type in ExpertType:
            output_path = output_dir / f"{base_name}_{expert_type.value}.png"
            self.preprocess_and_save(image, output_path, expert_type)
            results[expert_type] = output_path

        return results

    def _resize_to_standard(self, img: Image.Image) -> Image.Image:
        width, height = img.size
        if max(width, height) <= STANDARD_SIZE:
            return img

        if width >= height:
            new_width = STANDARD_SIZE
            new_height = int(height * (STANDARD_SIZE / width))
        else:
            new_height = STANDARD_SIZE
            new_width = int(width * (STANDARD_SIZE / height))

        return img.resize((new_width, new_height), Image.Resampling.LANCZOS)

    def _resize_image(self, img: Image.Image, expert_type: ExpertType) -> Image.Image:
        if self._expert_image_sizes is not None:
            max_size = self._expert_image_sizes.get(expert_type.value, 2048)
        else:
            try:
                settings = Settings.from_env()
                max_size = settings.get_expert_image_size(expert_type.value)
            except (ValueError, KeyError):
                max_size = 2048

        width, height = img.size
        if max(width, height) <= max_size:
            return img

        if width >= height:
            new_width = max_size
            new_height = int(height * (max_size / width))
        else:
            new_height = max_size
            new_width = int(width * (max_size / height))

        return img.resize((new_width, new_height), Image.Resampling.LANCZOS)

    def _load_image(self, image: Union[str, Path, Image.Image, np.ndarray]) -> Image.Image:
        if isinstance(image, (str, Path)):
            return Image.open(image).convert("RGB")
        elif isinstance(image, np.ndarray):
            if image.ndim == 2:
                return Image.fromarray(image)
            elif image.ndim == 3:
                if image.shape[2] == 4:
                    return Image.fromarray(image, mode="RGBA").convert("RGB")
                return Image.fromarray(image)
            raise ValueError(f"Invalid image array shape: {image.shape}")
        elif isinstance(image, Image.Image):
            if image.mode != "RGB":
                return image.convert("RGB")
            return image
        else:
            raise TypeError(f"Unsupported image type: {type(image)}")

    # 分发表：PreprocessMethod -> 处理方法名。
    # 除 RESIZE 需要额外 expert_type 参数外，其余方法签名均为 (img)。
    _METHOD_DISPATCH: dict[PreprocessMethod, str] = {
        PreprocessMethod.GRAYSCALE: "_to_grayscale",
        PreprocessMethod.CLAHE: "_apply_clahe",
        PreprocessMethod.CLAHE_COLOR: "_apply_clahe_color",
        PreprocessMethod.DENOISE: "_apply_denoise",
        PreprocessMethod.DENOISE_COLOR: "_apply_denoise_color",
        PreprocessMethod.THRESHOLD: "_apply_threshold",
        PreprocessMethod.GLOBAL_THRESHOLD: "_apply_global_threshold",
        PreprocessMethod.INVERT: "_apply_invert",
        PreprocessMethod.DILATE: "_apply_dilate",
        PreprocessMethod.ERODE: "_apply_erode",
        PreprocessMethod.SHARPEN: "_apply_sharpen",
        PreprocessMethod.SHARPEN_COLOR: "_apply_sharpen_color",
        PreprocessMethod.EDGE_ENHANCE: "_apply_edge_enhance",
        PreprocessMethod.BLUR: "_apply_blur",
        PreprocessMethod.MEDIAN_DENOISE: "_apply_median_denoise",
        PreprocessMethod.MORPH_CLOSE: "_apply_morph_close",
        PreprocessMethod.SKELETONIZE: "_apply_skeletonize",
        PreprocessMethod.CC_FILTER_TEXT: "_apply_cc_filter_text",
        PreprocessMethod.RESIZE: "_apply_resize",
        PreprocessMethod.ARROW_ENHANCE: "_apply_arrow_enhance",
    }

    def _apply_method(
        self,
        img: np.ndarray,
        method: PreprocessMethod,
        expert_type: Optional[ExpertType] = None,
    ) -> np.ndarray:
        method_name = self._METHOD_DISPATCH.get(method)
        if method_name is None:
            return img
        handler = getattr(self, method_name)
        # RESIZE 是唯一需要 expert_type 参数的方法
        if method == PreprocessMethod.RESIZE:
            return handler(img, expert_type)
        return handler(img)

    def _to_grayscale(self, img: np.ndarray) -> np.ndarray:
        import cv2

        if len(img.shape) == 3:
            return cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        return img

    def _apply_clahe(self, img: np.ndarray) -> np.ndarray:
        import cv2

        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

        clahe = cv2.createCLAHE(
            clipLimit=self.params.clahe_clip_limit, tileGridSize=self.params.clahe_tile_size
        )
        return clahe.apply(img)

    def _apply_denoise(self, img: np.ndarray) -> np.ndarray:
        import cv2

        return cv2.GaussianBlur(img, self.params.denoise_kernel, self.params.denoise_sigma)

    def _apply_threshold(self, img: np.ndarray) -> np.ndarray:
        import cv2

        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

        return cv2.adaptiveThreshold(
            img,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            self.params.threshold_block_size,
            self.params.threshold_c,
        )

    def _apply_global_threshold(self, img: np.ndarray) -> np.ndarray:
        import cv2

        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

        _, binary = cv2.threshold(img, self.params.global_threshold_value, 255, cv2.THRESH_BINARY)
        return binary

    def _apply_invert(self, img: np.ndarray) -> np.ndarray:
        return 255 - img

    def _apply_dilate(self, img: np.ndarray) -> np.ndarray:
        import cv2

        kernel = np.ones(self.params.dilate_kernel, np.uint8)
        return cv2.dilate(img, kernel, iterations=self.params.dilate_iterations)

    def _apply_erode(self, img: np.ndarray) -> np.ndarray:
        import cv2

        kernel = np.ones(self.params.erode_kernel, np.uint8)
        return cv2.erode(img, kernel, iterations=self.params.erode_iterations)

    def _apply_sharpen(self, img: np.ndarray) -> np.ndarray:
        import cv2

        return cv2.filter2D(img, -1, self.params.sharpen_kernel)

    def _apply_edge_enhance(self, img: np.ndarray) -> np.ndarray:
        import cv2

        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        else:
            gray = img

        laplacian = cv2.Laplacian(gray, cv2.CV_8U, ksize=3)
        return np.clip(laplacian, 0, 255).astype(np.uint8)

    def _apply_blur(self, img: np.ndarray) -> np.ndarray:
        import cv2

        return cv2.GaussianBlur(img, self.params.blur_kernel, self.params.blur_sigma)

    def _apply_clahe_color(self, img: np.ndarray) -> np.ndarray:
        import cv2

        if len(img.shape) != 3:
            return img

        lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)

        clahe = cv2.createCLAHE(
            clipLimit=self.params.clahe_clip_limit, tileGridSize=self.params.clahe_tile_size
        )
        l_equalized = clahe.apply(l_channel)

        lab_equalized = cv2.merge((l_equalized, a_channel, b_channel))
        return cv2.cvtColor(lab_equalized, cv2.COLOR_LAB2RGB)

    def _apply_denoise_color(self, img: np.ndarray) -> np.ndarray:
        import cv2

        if len(img.shape) != 3:
            return self._apply_denoise(img)

        return cv2.bilateralFilter(img, d=9, sigmaColor=75, sigmaSpace=75)

    def _apply_sharpen_color(self, img: np.ndarray) -> np.ndarray:
        import cv2

        if len(img.shape) == 3:
            return cv2.filter2D(img, -1, self.params.sharpen_kernel)
        else:
            return self._apply_sharpen(img)

    def _apply_median_denoise(self, img: np.ndarray) -> np.ndarray:
        import cv2

        ksize = self.params.median_kernel
        if ksize % 2 == 0:
            ksize += 1
        return cv2.medianBlur(img, ksize)

    def _apply_morph_close(self, img: np.ndarray) -> np.ndarray:
        import cv2

        kernel = np.ones(self.params.morph_close_kernel, np.uint8)
        return cv2.morphologyEx(
            img,
            cv2.MORPH_CLOSE,
            kernel,
            iterations=self.params.morph_close_iterations,
        )

    def _apply_skeletonize(self, img: np.ndarray) -> np.ndarray:
        import cv2

        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

        _, binary = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)
        skeleton = np.zeros_like(binary, dtype=np.uint8)

        eroded = binary.copy()
        while True:
            opened = cv2.morphologyEx(eroded, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            temp = cv2.subtract(eroded, opened)
            skeleton = cv2.bitwise_or(skeleton, temp)
            eroded = cv2.erode(eroded, np.ones((3, 3), np.uint8))
            if cv2.countNonZero(eroded) == 0:
                break

        return skeleton

    def _apply_cc_filter_text(self, img: np.ndarray) -> np.ndarray:
        import cv2

        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

        _, binary = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY_INV)
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)

        result = np.zeros_like(binary, dtype=np.uint8)
        for i in range(1, num_labels):
            area = stats[i, cv2.CC_STAT_AREA]
            if area < self.params.cc_min_area:
                continue
            if self.params.cc_max_area is not None and area > self.params.cc_max_area:
                continue
            w = stats[i, cv2.CC_STAT_WIDTH]
            h = stats[i, cv2.CC_STAT_HEIGHT]
            if w > 0 and h > 0:
                aspect = max(w, h) / min(w, h)
                if aspect > self.params.cc_aspect_ratio_threshold:
                    continue
            # 通过过滤器的连通域（管线/设备）-> 保留
            component_mask = (labels == i).astype(np.uint8) * 255
            result = cv2.bitwise_or(result, component_mask)

        return result

    def _apply_resize(
        self, img: np.ndarray, expert_type: Optional[ExpertType] = None
    ) -> np.ndarray:
        import cv2

        if expert_type is None:
            return img

        max_size = self._get_expert_max_size(expert_type)
        h, w = img.shape[:2]
        if max(h, w) <= max_size:
            return img

        if w >= h:
            new_w = max_size
            new_h = int(h * (max_size / w))
        else:
            new_h = max_size
            new_w = int(w * (max_size / h))

        interpolation = cv2.INTER_AREA if max(w, h) > max_size else cv2.INTER_LINEAR
        return cv2.resize(img, (new_w, new_h), interpolation=interpolation)

    def _apply_arrow_enhance(self, img: np.ndarray) -> np.ndarray:
        import cv2

        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

        sharpened = cv2.filter2D(img, -1, self.params.sharpen_kernel)
        _, binary = cv2.threshold(
            sharpened,
            self.params.arrow_global_threshold_value,
            255,
            cv2.THRESH_BINARY,
        )

        inverted = 255 - binary
        close_kernel = np.ones(self.params.arrow_close_kernel, np.uint8)
        connected = cv2.morphologyEx(inverted, cv2.MORPH_CLOSE, close_kernel)

        erode_kernel = np.ones(self.params.arrow_erode_kernel, np.uint8)
        strengthened = cv2.erode(
            255 - connected,
            erode_kernel,
            iterations=self.params.arrow_erode_iterations,
        )
        return strengthened

    @classmethod
    def get_strategy(cls, expert_type: ExpertType) -> list[PreprocessMethod]:
        return EXPERT_STRATEGIES.get(expert_type, [])

    @classmethod
    def get_strategy_description(cls, expert_type: ExpertType) -> str:
        return STRATEGY_DESCRIPTIONS.get(expert_type, "No preprocessing")

    @classmethod
    def list_methods(cls) -> dict[str, str]:
        return {m.value: METHOD_DESCRIPTIONS[m] for m in PreprocessMethod}

    @classmethod
    def list_strategies(cls) -> dict[str, dict[str, Any]]:
        result = {}
        for expert_type in ExpertType:
            methods = EXPERT_STRATEGIES.get(expert_type, [])
            result[expert_type.value] = {
                "methods": [m.value for m in methods],
                "description": STRATEGY_DESCRIPTIONS.get(expert_type, ""),
            }
        return result

    @classmethod
    def list_param_presets(cls) -> dict[str, dict[str, Any]]:
        return {
            "PARAMS_4096": {
                "description": "Parameters optimized for 4096 max dimension images (default)",
                "params": {
                    "clahe_clip_limit": 2.0,
                    "clahe_tile_size": (6, 6),
                    "denoise_kernel": (3, 3),
                    "denoise_sigma": 0.5,
                    "threshold_block_size": 11,
                    "threshold_c": 1,
                    "global_threshold_value": 200,
                    "dilate_kernel": (2, 2),
                    "dilate_iterations": 1,
                    "erode_kernel": (2, 2),
                    "erode_iterations": 1,
                    "morph_close_kernel": (2, 2),
                    "morph_close_iterations": 1,
                    "blur_kernel": (3, 3),
                    "blur_sigma": 1.0,
                    "median_kernel": 3,
                    "cc_min_area": 50,
                    "cc_max_area": None,
                    "cc_aspect_ratio_threshold": 5.0,
                },
            },
        }
