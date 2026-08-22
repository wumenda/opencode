import base64
from pathlib import Path
from typing import Any

from PIL import Image

from src.core.infra.exceptions import ImageProcessingError


def scale_to_long_edge(img: Image.Image, target_long_edge: int = 2048) -> Image.Image:
    w, h = img.size
    long_edge = max(w, h)
    if long_edge <= target_long_edge:
        return img
    ratio = target_long_edge / long_edge
    new_w = int(w * ratio)
    new_h = int(h * ratio)
    return img.resize((new_w, new_h), Image.LANCZOS)


def encode_image(image_path: Path) -> str:
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")
    except Exception as e:
        raise ImageProcessingError(f"Failed to encode image: {e}") from e


def resize_image_if_needed(
    image_path: Path,
    max_pixels: int = 178956970,
    max_dimension: int = 4096,
) -> tuple[str, bool, int, int, int, int]:
    resized_path = None
    try:
        img = Image.open(image_path)
        original_width, original_height = img.size
        original_pixels = original_width * original_height
        was_resized = False

        if original_pixels > max_pixels or max(original_width, original_height) > max_dimension:
            ratio = min(
                (max_pixels / original_pixels) ** 0.5,
                max_dimension / max(original_width, original_height),
            )
            new_width = int(original_width * ratio)
            new_height = int(original_height * ratio)
            img = img.resize((new_width, new_height), Image.LANCZOS)
            was_resized = True
        else:
            new_width, new_height = original_width, original_height

        if was_resized:
            resized_path = image_path.parent / f"{image_path.stem}_resized{image_path.suffix}"
            img.save(resized_path, quality=95)
            img.close()
            base64_image = encode_image(resized_path)
            return base64_image, True, original_width, original_height, new_width, new_height
        else:
            img.close()
            base64_image = encode_image(image_path)
            return base64_image, False, original_width, original_height, new_width, new_height

    except Exception as e:
        raise ImageProcessingError(f"Failed to resize image: {e}") from e
    finally:
        if resized_path and resized_path.exists():
            try:
                resized_path.unlink()
            except OSError:
                pass


def get_image_metadata(image_path: Path, **kwargs) -> dict[str, Any]:
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            return {
                "file_path": str(image_path),
                "original_width": width,
                "original_height": height,
                "format": img.format or "PNG",
                "color_mode": img.mode,
            }
    except Exception as e:
        raise ImageProcessingError(f"Failed to get image metadata: {e}") from e
