"""
Image Processor — Core processing engine for Better Images.
Handles upscaling, background removal, SVG and ICO conversion.
All processing is done locally using open-source AI models.

Key improvements for macOS:
- Tile-based processing for Real-ESRGAN (prevents OOM and speeds up)
- Auto-resize large images before upscaling
- MPS (Apple Metal GPU) detection for acceleration
"""

import os
import time
import logging
from pathlib import Path

import numpy as np
from PIL import Image
from rembg import remove

logger = logging.getLogger(__name__)

# Max input dimension before auto-resize (upscaling a 2000px image x4 = 8000px)
MAX_INPUT_DIM = 1500
# Tile size for Real-ESRGAN (smaller = less memory, slightly slower)
TILE_SIZE = 256


class ImageProcessor:
    """Handles all image processing operations locally."""

    def __init__(self, models_dir: str = "models"):
        self.models_dir = Path(models_dir)
        self.models_dir.mkdir(exist_ok=True)
        self._upsampler_x2 = None
        self._upsampler_x4 = None
        self._device = self._detect_device()
        logger.info(f"ImageProcessor initialized — device: {self._device}")

    def _detect_device(self) -> str:
        """Detect best available device for PyTorch."""
        try:
            import torch
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                logger.info("🚀 Apple MPS (Metal GPU) detected — using GPU acceleration")
                return "mps"
            elif torch.cuda.is_available():
                logger.info("🚀 CUDA GPU detected — using GPU acceleration")
                return "cuda"
        except ImportError:
            pass
        logger.info("💻 Using CPU for processing")
        return "cpu"

    def _get_upsampler(self, scale: int):
        """Lazy-load Real-ESRGAN upsampler model with tiling."""
        if scale == 2 and self._upsampler_x2:
            return self._upsampler_x2
        if scale == 4 and self._upsampler_x4:
            return self._upsampler_x4

        try:
            from basicsr.archs.rrdbnet_arch import RRDBNet
            from realesrgan import RealESRGANer

            if scale == 2:
                model = RRDBNet(
                    num_in_ch=3, num_out_ch=3, num_feat=64,
                    num_block=23, num_grow_ch=32, scale=2
                )
                model_name = "RealESRGAN_x2plus"
                model_url = f"https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/{model_name}.pth"
            else:
                model = RRDBNet(
                    num_in_ch=3, num_out_ch=3, num_feat=64,
                    num_block=23, num_grow_ch=32, scale=4
                )
                model_name = "RealESRGAN_x4plus"
                model_url = f"https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/{model_name}.pth"

            model_path = self.models_dir / f"{model_name}.pth"

            # Auto-download model if not present (expected on fresh GitHub clones)
            if not model_path.exists():
                logger.info(f"⬇️  Downloading {model_name} model (~67MB)...")
                import urllib.request
                self.models_dir.mkdir(parents=True, exist_ok=True)
                urllib.request.urlretrieve(model_url, str(model_path))
                logger.info(f"✅ Model downloaded to {model_path}")

            # Use tiling to prevent OOM and speed up processing
            # MPS doesn't work well with half precision
            use_half = self._device == "cuda"

            upsampler = RealESRGANer(
                scale=scale,
                model_path=str(model_path),
                model=model,
                tile=TILE_SIZE,
                tile_pad=10,
                pre_pad=0,
                half=use_half,
                device=self._device,
            )

            if scale == 2:
                self._upsampler_x2 = upsampler
            else:
                self._upsampler_x4 = upsampler

            return upsampler

        except Exception as e:
            logger.error(f"Failed to load Real-ESRGAN model: {e}")
            raise

    def _resize_if_needed(self, image_path: str, max_dim: int = MAX_INPUT_DIM) -> str:
        """Resize image if any dimension exceeds max_dim. Returns new path or original."""
        img = Image.open(image_path)
        w, h = img.size

        if w <= max_dim and h <= max_dim:
            return image_path

        # Calculate new size maintaining aspect ratio
        ratio = min(max_dim / w, max_dim / h)
        new_w = int(w * ratio)
        new_h = int(h * ratio)

        logger.info(f"📐 Resizing {w}×{h} → {new_w}×{new_h} before upscaling")

        img_resized = img.resize((new_w, new_h), Image.LANCZOS)
        resized_path = self._make_output_path(image_path, "_resized")
        img_resized.save(resized_path, quality=95)
        return resized_path

    def upscale(self, image_path: str, scale: int = 2, progress_cb=None) -> str:
        """
        Upscale image using Real-ESRGAN.
        Properly handles alpha channels to prevent black border artifacts.
        """
        if scale not in (2, 4):
            raise ValueError("Scale must be 2 or 4")

        def update(msg):
            logger.info(msg)
            if progress_cb:
                progress_cb(msg)

        # Auto-resize large images
        update(f"📐 Checking image size...")
        work_path = self._resize_if_needed(image_path)

        update(f"🧠 Loading Real-ESRGAN model ({scale}x)...")
        start = time.time()

        import cv2
        img = cv2.imread(work_path, cv2.IMREAD_UNCHANGED)
        if img is None:
            raise ValueError(f"Cannot read image: {work_path}")

        h, w = img.shape[:2]
        has_alpha = img.shape[2] == 4 if len(img.shape) == 3 else False

        update(f"⚡ Upscaling {w}×{h} → {w*scale}×{h*scale} ({self._device.upper()})...")

        upsampler = self._get_upsampler(scale)

        if has_alpha:
            # --- Handle alpha channel to prevent black borders ---
            alpha = img[:, :, 3]     # Extract alpha
            bgr = img[:, :, :3]      # Extract RGB

            # Fill transparent areas with average foreground color
            # This prevents black bleeding into semi-transparent edges
            mask = alpha > 0
            if mask.any():
                avg_color = bgr[mask].mean(axis=0).astype(np.uint8)
            else:
                avg_color = np.array([255, 255, 255], dtype=np.uint8)

            # Create composite: blend original onto solid avg_color background
            alpha_f = alpha.astype(np.float32) / 255.0
            alpha_3ch = np.stack([alpha_f] * 3, axis=-1)
            bg = np.full_like(bgr, avg_color)
            composite = (bgr.astype(np.float32) * alpha_3ch + bg.astype(np.float32) * (1 - alpha_3ch))
            composite = composite.clip(0, 255).astype(np.uint8)

            # Upscale the RGB composite (no alpha, no black)
            output_rgb, _ = upsampler.enhance(composite, outscale=scale)

            # Upscale alpha channel separately using high-quality resize
            new_h, new_w = output_rgb.shape[:2]
            alpha_upscaled = cv2.resize(
                alpha, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4
            )

            # Recombine BGRA
            output = cv2.merge([
                output_rgb[:, :, 0],
                output_rgb[:, :, 1],
                output_rgb[:, :, 2],
                alpha_upscaled,
            ])

            output_path = self._make_output_path(image_path, f"_x{scale}", ext=".png")
        else:
            # No alpha — standard upscale
            output, _ = upsampler.enhance(img, outscale=scale)
            output_path = self._make_output_path(image_path, f"_x{scale}")

        cv2.imwrite(output_path, output)

        elapsed = time.time() - start
        update(f"✅ Upscaled in {elapsed:.1f}s → {output_path}")
        return output_path

    def remove_background(self, image_path: str, progress_cb=None) -> str:
        """
        Remove background using rembg (U2-Net).
        Returns path to PNG with transparent background.
        """
        def update(msg):
            logger.info(msg)
            if progress_cb:
                progress_cb(msg)

        update("🎭 Removing background with AI...")
        start = time.time()

        with open(image_path, "rb") as f:
            input_data = f.read()

        output_data = remove(input_data)

        output_path = self._make_output_path(image_path, "_nobg", ext=".png")
        with open(output_path, "wb") as f:
            f.write(output_data)

        elapsed = time.time() - start
        update(f"✅ Background removed in {elapsed:.1f}s")
        return output_path

    def to_svg(self, image_path: str, progress_cb=None) -> str:
        """Convert bitmap to SVG using vtracer."""
        import vtracer

        def update(msg):
            logger.info(msg)
            if progress_cb:
                progress_cb(msg)

        update("🖋️ Converting to SVG...")
        start = time.time()

        output_path = self._make_output_path(image_path, "", ext=".svg")

        vtracer.convert_image_to_svg_py(
            image_path,
            output_path,
            colormode="color",
            hierarchical="stacked",
            mode="spline",
            filter_speckle=2,        # minimal filtering, keeps most detail
            color_precision=8,       # max color accuracy
            layer_difference=5,      # many layers but not extreme
            corner_threshold=45,     # balanced corners
            length_threshold=3.0,    # balanced segment length
            max_iterations=15,       # good fit without being extreme
            splice_threshold=35,     # balanced curves
            path_precision=5,        # good precision, reasonable file size
        )

        elapsed = time.time() - start
        update(f"✅ SVG created in {elapsed:.1f}s")
        return output_path

    def to_ico(self, image_path: str, sizes: list[int] | None = None, progress_cb=None) -> str:
        """
        Convert image to ICO format with multiple sizes.
        Default sizes: 16, 32, 48, 64, 128, 256.
        """
        if sizes is None:
            sizes = [16, 32, 48, 64, 128, 256]

        def update(msg):
            logger.info(msg)
            if progress_cb:
                progress_cb(msg)

        update(f"🎨 Creating ICO with sizes {sizes}...")

        img = Image.open(image_path)
        if img.mode != "RGBA":
            img = img.convert("RGBA")

        ico_sizes = [(s, s) for s in sizes]
        output_path = self._make_output_path(image_path, "", ext=".ico")
        img.save(output_path, format="ICO", sizes=ico_sizes)

        update(f"✅ ICO saved with {len(sizes)} sizes")
        return output_path

    def process_pipeline(
        self,
        image_path: str,
        upscale_factor: int | None = None,
        remove_bg: bool = False,
        output_format: str = "png",
        progress_cb=None,
    ) -> dict:
        """
        Run the full processing pipeline.
        Returns dict with paths to all generated files.
        """
        results = {"original": image_path, "steps": []}
        current_path = image_path

        # Step 1: Upscale
        if upscale_factor:
            current_path = self.upscale(current_path, upscale_factor, progress_cb)
            results["upscaled"] = current_path
            results["steps"].append("upscaled")

        # Step 2: Remove background
        if remove_bg:
            current_path = self.remove_background(current_path, progress_cb)
            results["no_background"] = current_path
            results["steps"].append("background_removed")

        # Step 3: Convert format
        if output_format == "svg":
            final_path = self.to_svg(current_path, progress_cb)
            results["svg"] = final_path
            results["steps"].append("converted_svg")
        elif output_format == "ico":
            final_path = self.to_ico(current_path, progress_cb=progress_cb)
            results["ico"] = final_path
            results["steps"].append("converted_ico")
        else:
            final_path = current_path

        results["final"] = final_path
        return results

    def _make_output_path(self, input_path: str, suffix: str, ext: str | None = None) -> str:
        """Generate output path based on input path."""
        p = Path(input_path)
        output_dir = p.parent
        if ext is None:
            ext = p.suffix
        output_name = f"{p.stem}{suffix}{ext}"
        return str(output_dir / output_name)
