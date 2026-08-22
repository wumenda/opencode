"""
PDF to Image Conversion Module

This module provides utilities for converting PDF files to images.
"""

from pathlib import Path
from typing import List, Optional, Union
import os

from PIL import Image
import numpy as np

Image.MAX_IMAGE_PIXELS = 500_000_000


class PDFToImageConverter:
    """PDF to image converter."""

    PREPROCESS_METHODS = {
        "grayscale": "Convert to grayscale",
        "clahe": "CLAHE contrast enhancement",
        "denoise": "Gaussian denoise",
        "threshold": "Adaptive threshold binarization",
        "dilate": "Slight dilation",
    }

    def __init__(
        self,
        dpi: int = 300,
        image_format: str = "png",
        quality: int = 95,
        preprocess_methods: list[str] | None = None,
        target_long_edge: int | None = None,
        vector_enhance: bool = False,
    ) -> None:
        """
        Initialize the converter.

        Args:
            dpi: Image resolution, default 300.
            image_format: Output format, supports 'png' or 'jpg'/'jpeg'.
            quality: JPG quality (1-100), only for JPG.
            preprocess_methods: List of preprocessing methods to apply.
                Available methods: grayscale, clahe, denoise, threshold, dilate.
                If None, preprocessing is disabled.
            target_long_edge: Target long edge size for resizing before preprocessing.
                If None, no resizing is performed. Default None.
                Example: 4096 means resize image so the long edge is 4096 pixels.
            vector_enhance: Enable vector line art enhancement mode.
                Disables anti-aliasing and uses grayscale colorspace to make
                thin vector lines (e.g., PFD pipelines) more visible.
                Default False.
        """
        self.dpi = dpi
        self.image_format = image_format.lower()
        self.quality = max(1, min(100, quality))
        self.preprocess_methods = preprocess_methods or []
        self.target_long_edge = target_long_edge
        self.vector_enhance = vector_enhance

        if self.image_format not in ["png", "jpg", "jpeg"]:
            raise ValueError(
                f"Unsupported image format: {image_format}, " f"only png/jpg/jpeg are supported"
            )

        for method in self.preprocess_methods:
            if method not in self.PREPROCESS_METHODS:
                raise ValueError(
                    f"Unknown preprocess method: {method}. "
                    f"Available methods: {list(self.PREPROCESS_METHODS.keys())}"
                )

    @property
    def enable_preprocess(self) -> bool:
        """Check if preprocessing is enabled."""
        return len(self.preprocess_methods) > 0

    def convert(
        self,
        pdf_path: Union[str, Path],
        output_dir: Union[str, Path],
        prefix: Optional[str] = None,
        start_page: int = 0,
        end_page: Optional[int] = None,
    ) -> List[str]:
        """
        Convert PDF to images.

        Args:
            pdf_path: PDF file path.
            output_dir: Output directory.
            prefix: Output filename prefix, defaults to PDF filename.
            start_page: Start page number (from 0).
            end_page: End page number (exclusive), None means last page.

        Returns:
            List of generated image file paths.

        Raises:
            FileNotFoundError: If PDF file does not exist.
            ValueError: If page range is invalid.
        """
        pdf_path = Path(pdf_path)
        output_dir = Path(output_dir)

        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        output_dir.mkdir(parents=True, exist_ok=True)

        if prefix is None:
            prefix = pdf_path.stem

        page_count = self.get_page_count(pdf_path)
        if start_page < 0 or start_page >= page_count:
            raise ValueError(
                f"Start page out of range: {start_page}, total pages: {page_count}"
            )
        if end_page is None:
            end_page = page_count
        elif end_page > page_count:
            end_page = page_count
        if start_page >= end_page:
            raise ValueError(
                f"Start page {start_page} cannot be greater than or "
                f"equal to end page {end_page}"
            )

        images = self._read_pdf(pdf_path, start_page, end_page)

        if self.enable_preprocess:
            print("\nPerforming image preprocessing...")
            processed_images = []
            for idx, image in enumerate(images):
                processed_image = self.preprocess_image(image)
                processed_images.append(processed_image)
                print(f"  Processed page {start_page + idx + 1}")
            images = processed_images
            print("Preprocessing completed\n")

        output_paths = []

        for idx, image in enumerate(images):
            page_num = start_page + idx + 1  # 绝对页码命名保持不变

            if self.image_format in ["jpg", "jpeg"]:
                ext = ".jpg"
            else:
                ext = ".png"

            output_path = output_dir / f"{prefix}_page_{page_num:03d}{ext}"

            self._save_image(image, output_path)
            output_paths.append(str(output_path))
            print(f"Saved: {output_path}")

        return output_paths

    def convert_single_page(
        self,
        pdf_path: Union[str, Path],
        page_num: int,
        output_path: Union[str, Path],
    ) -> str:
        """
        Convert a specific page of PDF to image.

        Args:
            pdf_path: PDF file path.
            page_num: Page number (from 0).
            output_path: Output image path.

        Returns:
            Generated image file path.
        """
        pdf_path = Path(pdf_path)
        output_path = Path(output_path)

        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        total = self.get_page_count(pdf_path)
        if page_num < 0 or page_num >= total:
            raise ValueError(f"Page out of range: {page_num}, total pages: {total}")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        images = self._read_pdf(pdf_path, page_num, page_num + 1)
        self._save_image(images[0], output_path)
        print(f"Saved: {output_path}")

        return str(output_path)

    def get_page_count(self, pdf_path: Union[str, Path]) -> int:
        """
        Get PDF page count.

        Args:
            pdf_path: PDF file path.

        Returns:
            Page count.
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        import pypdfium2 as pdfium

        with pdfium.PdfDocument(str(pdf_path)) as pdf:
            return len(pdf)

    def _read_pdf(
        self, pdf_path: Path, start_page: int = 0, end_page: Optional[int] = None
    ) -> List:
        """读取 PDF 指定页范围并渲染（end_page 不含；None 表示到最后一页）。"""
        return self._read_pdf_with_pypdfium2(pdf_path, start_page, end_page)

    def _read_pdf_with_pypdfium2(
        self, pdf_path: Path, start_page: int = 0, end_page: Optional[int] = None
    ) -> List:
        """Read PDF using pypdfium2.

        pypdfium2 bundles PDFium, so no external system dependency (e.g.
        poppler) is required. Anti-aliasing flags are set per render call,
        avoiding the global state restore needed by fitz.
        """
        import pypdfium2 as pdfium

        scale = self.dpi / 72.0
        images: List = []

        with pdfium.PdfDocument(str(pdf_path)) as pdf:
            total = len(pdf)
            end = total if end_page is None else min(end_page, total)
            if start_page < 0 or start_page >= total:
                raise ValueError(
                    f"Start page out of range: {start_page}, total pages: {total}"
                )
            if start_page >= end:
                raise ValueError(
                    f"Start page {start_page} cannot be greater than or "
                    f"equal to end page {end}"
                )
            for page_num in range(start_page, end):
                page = pdf[page_num]

                if self.vector_enhance:
                    # Disable anti-aliasing to sharpen thin vector lines
                    # (e.g. PFD pipelines); equivalent to fitz set_aa_level(0).
                    bitmap = page.render(
                        scale=scale,
                        no_smoothtext=True,
                        no_smoothimage=True,
                        no_smoothpath=True,
                    )
                else:
                    bitmap = page.render(scale=scale)

                pil_image = bitmap.to_pil()

                if self.vector_enhance:
                    pil_image = pil_image.convert("L")

                images.append(pil_image)

        return images

    def preprocess_image(self, image: Image.Image) -> Image.Image:
        """
        Image preprocessing with configurable methods.

        Args:
            image: Original image.

        Returns:
            Processed image.
        """
        if not self.preprocess_methods:
            return image

        try:
            import cv2  # noqa: F401
        except ImportError:
            raise ImportError(
                "Image preprocessing requires opencv-python: " "pip install opencv-python"
            )

        if self.target_long_edge is not None:
            image = self._resize_to_target_long_edge(image)

        img_array = np.array(image)
        current = img_array

        for method in self.preprocess_methods:
            current = self._apply_preprocess_method(current, method)

        if len(current.shape) == 2:
            processed_image = Image.fromarray(current)
        else:
            processed_image = Image.fromarray(current)

        return processed_image

    def _resize_to_target_long_edge(self, image: Image.Image) -> Image.Image:
        """
        Resize image so that the long edge equals target_long_edge.

        Args:
            image: Original image.

        Returns:
            Resized image.
        """
        width, height = image.size
        long_edge = max(width, height)

        if long_edge == self.target_long_edge:
            return image

        scale = self.target_long_edge / long_edge
        new_width = int(width * scale)
        new_height = int(height * scale)

        resized = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        print(f"  Resized from {width}x{height} to {new_width}x{new_height} (scale: {scale:.4f})")

        return resized

    def _apply_preprocess_method(self, img: np.ndarray, method: str) -> np.ndarray:
        """
        Apply a single preprocessing method.

        Args:
            img: Input image array.
            method: Preprocessing method name.

        Returns:
            Processed image array.
        """
        import cv2

        if method == "grayscale":
            if len(img.shape) == 3:
                return cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            return img

        elif method == "clahe":
            if len(img.shape) == 3:
                img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
            return clahe.apply(img)

        elif method == "denoise":
            return cv2.GaussianBlur(img, (3, 3), 0)

        elif method == "threshold":
            if len(img.shape) == 3:
                img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            return cv2.adaptiveThreshold(
                img,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                21,
                3,
            )

        elif method == "dilate":
            kernel = np.ones((2, 2), np.uint8)
            return cv2.dilate(img, kernel, iterations=1)

        return img

    def _save_image(self, image: Image.Image, output_path: Path) -> None:
        """Save image."""
        if self.image_format in ["jpg", "jpeg"]:
            if image.mode == "RGBA":
                image = image.convert("RGB")
            image.save(
                str(output_path),
                "JPEG",
                quality=self.quality,
                dpi=(self.dpi, self.dpi),
            )
        else:
            image.save(str(output_path), "PNG", dpi=(self.dpi, self.dpi))

        self._print_image_info(image, output_path)

    def _print_image_info(self, image: Image.Image, output_path: Path) -> None:
        """Print image metadata."""
        file_size = os.path.getsize(output_path)
        file_size_kb = file_size / 1024
        file_size_mb = file_size_kb / 1024

        if file_size_mb >= 1:
            size_str = f"{file_size_mb:.2f} MB"
        else:
            size_str = f"{file_size_kb:.2f} KB"

        width, height = image.size
        mode = image.mode
        format_name = "JPEG" if self.image_format in ["jpg", "jpeg"] else "PNG"

        bits_per_pixel = {
            "1": 1,
            "L": 8,
            "P": 8,
            "RGB": 24,
            "RGBA": 32,
            "CMYK": 32,
            "YCbCr": 24,
            "LAB": 24,
            "HSV": 24,
            "I": 32,
            "F": 32,
        }.get(mode, 8)

        print(f"\n{'─' * 60}")
        print("Image metadata:")
        print(f"{'─' * 60}")
        print(f"  File path: {output_path}")
        print(f"  File size: {size_str}")
        print(f"  Image size: {width} x {height} pixels")
        print(f"  Image format: {format_name}")
        print(f"  Resolution:   {self.dpi} DPI")
        print(f"  Color mode: {mode}")
        print(f"  Bit depth:   {bits_per_pixel} bits/pixel")
        print(f"  Total pixels: {width * height:,} pixels")
        print(f"{'─' * 60}")

    def resize_image(
        self,
        image: Image.Image,
        scale: float,
    ) -> Image.Image:
        """
        Resize image.

        Args:
            image: Original image.
            scale: Scale factor (0-1).

        Returns:
            Resized image.
        """
        if scale <= 0 or scale > 1:
            raise ValueError(f"Scale must be in range (0, 1], current: {scale}")

        width, height = image.size
        new_width = int(width * scale)
        new_height = int(height * scale)

        resized = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

        return resized

    def _postprocess_after_resize(self, image: Image.Image) -> Image.Image:
        """
        缩放后的轻量预处理，用于增强缩小后图像的可见性。

        Args:
            image: 缩放后的图像。

        Returns:
            处理后的图像。
        """
        try:
            import cv2
        except ImportError:
            return image

        img_array = np.array(image)

        if len(img_array.shape) == 2:
            gray = img_array
        else:
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)

        clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        denoised = cv2.GaussianBlur(enhanced, (3, 3), 0)

        return Image.fromarray(denoised)

    def convert_multi_scale(
        self,
        pdf_path: Union[str, Path],
        output_dir: Union[str, Path],
        scales: Optional[List[float]] = None,
        prefix: Optional[str] = None,
        start_page: int = 0,
        end_page: Optional[int] = None,
        post_resize_preprocess: bool = False,
    ) -> dict:
        """
        Convert PDF to images of multiple sizes.

        Args:
            pdf_path: PDF file path.
            output_dir: Output directory.
            scales: List of scale factors, default [0.5, 0.25, 0.1].
            prefix: Output filename prefix, defaults to PDF filename.
            start_page: Start page number (from 0).
            end_page: End page number (exclusive), None means last page.
            post_resize_preprocess: Whether to apply light preprocessing after resize.
                Useful for enhancing visibility of small scaled images.

        Returns:
            Dictionary with scale as key and list of image paths as value.

        Raises:
            FileNotFoundError: If PDF file does not exist.
            ValueError: If page range is invalid.
        """
        if scales is None:
            scales = [0.5, 0.25, 0.1]
        pdf_path = Path(pdf_path)
        output_dir = Path(output_dir)

        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        output_dir.mkdir(parents=True, exist_ok=True)

        if prefix is None:
            prefix = pdf_path.stem

        images = self._read_pdf(pdf_path)

        if self.enable_preprocess:
            print("\nPerforming image preprocessing...")
            processed_images = []
            for idx, image in enumerate(images):
                processed_image = self.preprocess_image(image)
                processed_images.append(processed_image)
                print(f"  Processed page {idx + 1}")
            images = processed_images
            print("Preprocessing completed\n")

        if start_page < 0 or start_page >= len(images):
            raise ValueError(
                f"Start page out of range: {start_page}, " f"total pages: {len(images)}"
            )

        if end_page is None:
            end_page = len(images)
        elif end_page > len(images):
            end_page = len(images)

        if start_page >= end_page:
            raise ValueError(
                f"Start page {start_page} cannot be greater than or "
                f"equal to end page {end_page}"
            )

        result = {}

        for scale in scales:
            scale_dir = output_dir / f"scale_{scale}"
            scale_dir.mkdir(parents=True, exist_ok=True)

            scale_paths = []

            for idx in range(start_page, end_page):
                image = images[idx]
                page_num = idx + 1

                resized_image = self.resize_image(image, scale)

                if post_resize_preprocess:
                    resized_image = self._postprocess_after_resize(resized_image)

                if self.image_format in ["jpg", "jpeg"]:
                    ext = ".jpg"
                else:
                    ext = ".png"

                output_path = scale_dir / f"{prefix}_page_{page_num:03d}{ext}"

                self._save_image(resized_image, output_path)
                scale_paths.append(str(output_path))

            result[scale] = scale_paths
            print(f"\nScale {scale} completed, {len(scale_paths)} images")

        return result


def pdf_to_images(
    pdf_path: Union[str, Path],
    output_dir: Union[str, Path],
    dpi: int = 300,
    image_format: str = "png",
    quality: int = 95,
    prefix: Optional[str] = None,
    start_page: int = 0,
    end_page: Optional[int] = None,
) -> List[str]:
    """
    Convenience function: Convert PDF to images.

    Args:
        pdf_path: PDF file path.
        output_dir: Output directory.
        dpi: Image resolution, default 300.
        image_format: Output format, supports 'png' or 'jpg'/'jpeg'.
        quality: JPG quality (1-100), only for JPG.
        prefix: Output filename prefix, defaults to PDF filename.
        start_page: Start page number (from 0), default 0.
        end_page: End page number (exclusive), None means last page.

    Returns:
        List of generated image file paths.

    Examples:
        >>> pdf_to_images("document.pdf", "output_images", dpi=300)
        >>> pdf_to_images("report.pdf", "images", image_format='jpg', quality=90)
    """
    converter = PDFToImageConverter(dpi=dpi, image_format=image_format, quality=quality)
    return converter.convert(pdf_path, output_dir, prefix=prefix, start_page=start_page, end_page=end_page)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PDF to Image Tool")
    parser.add_argument(
        "--input",
        "-i",
        default="data/装置级/PFD.pdf",
        type=str,
        help="Input PDF file path",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="output_images",
        type=str,
        help="Output directory",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="Image resolution DPI (default: 300)",
    )
    parser.add_argument(
        "--format",
        "-f",
        type=str,
        default="png",
        choices=["png", "jpg", "jpeg"],
        help="Output image format (default: png)",
    )
    parser.add_argument(
        "--quality",
        "-q",
        type=int,
        default=95,
        help="JPG quality 1-100 (default: 95)",
    )
    parser.add_argument(
        "--prefix",
        "-p",
        type=str,
        help="Output filename prefix (default: PDF filename)",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=0,
        help="Start page, from 0 (default: 0)",
    )
    parser.add_argument(
        "--end",
        type=int,
        help="End page (exclusive) (default: last page)",
    )
    parser.add_argument(
        "--multi-scale",
        action="store_true",
        help="Enable multi-scale output (0.5, 0.25, 0.1)",
    )
    parser.add_argument(
        "--scales",
        type=float,
        nargs="+",
        default=[0.5, 0.25, 0.1],
        help="Custom scale factors (e.g., --scales 0.5 0.25 0.1)",
    )
    parser.add_argument(
        "--preprocess",
        action="store_true",
        help="Enable image preprocessing (grayscale, CLAHE, Gaussian denoise, adaptive threshold, dilate)",
    )
    parser.add_argument(
        "--target-long-edge",
        type=int,
        default=None,
        help="Target long edge size for resizing before preprocessing (e.g., 4096). Only applies when --preprocess is enabled.",
    )
    parser.add_argument(
        "--post-resize-preprocess",
        action="store_true",
        help="Enable light preprocessing after resize (CLAHE + denoise), useful for small scaled images",
    )
    parser.add_argument(
        "--vector-enhance",
        "-V",
        action="store_true",
        help="Enable vector line art enhancement mode. Disables anti-aliasing and uses "
        "grayscale colorspace to make thin vector lines more visible.",
    )

    args = parser.parse_args()

    print(f"\n{'=' * 60}")
    print("PDF to Image")
    print(f"{'=' * 60}")
    print(f"Input file: {args.input}")
    print(f"Output directory: {args.output}")
    print(f"Resolution: {args.dpi} DPI")
    print(f"Image format: {args.format}")
    if args.format in ["jpg", "jpeg"]:
        print(f"Image quality: {args.quality}")
    if args.multi_scale:
        print(f"Multi-scale output: {args.scales}")
    if args.preprocess:
        print("Image preprocessing: Enabled")
        if args.target_long_edge:
            print(f"Target long edge: {args.target_long_edge} pixels")
    if args.post_resize_preprocess:
        print("Post-resize preprocessing: Enabled")
    if args.vector_enhance:
        print("Vector enhance: Enabled (no AA, grayscale)")
    print(f"{'=' * 60}\n")

    preprocess_methods = None
    if args.preprocess:
        preprocess_methods = ["grayscale", "clahe", "denoise", "threshold", "dilate"]

    converter = PDFToImageConverter(
        dpi=args.dpi,
        image_format=args.format,
        quality=args.quality,
        preprocess_methods=preprocess_methods,
        target_long_edge=args.target_long_edge,
        vector_enhance=args.vector_enhance,
    )

    if args.multi_scale:
        result = converter.convert_multi_scale(
            pdf_path=args.input,
            output_dir=args.output,
            scales=args.scales,
            prefix=args.prefix,
            start_page=args.start,
            end_page=args.end,
            post_resize_preprocess=args.post_resize_preprocess,
        )

        total_images = sum(len(paths) for paths in result.values())
        print(f"\n{'=' * 60}")
        print(f"Conversion completed! Generated {total_images} images")
        for scale, paths in result.items():
            print(f"  Scale {scale}: {len(paths)} images")
        print(f"{'=' * 60}\n")
    else:
        output_paths = converter.convert(
            pdf_path=args.input,
            output_dir=args.output,
            prefix=args.prefix,
            start_page=args.start,
            end_page=args.end,
        )

        print(f"\n{'=' * 60}")
        print(f"Conversion completed! Generated {len(output_paths)} images")
        print(f"{'=' * 60}\n")
