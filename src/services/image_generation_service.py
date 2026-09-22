"""Image generation service supporting FLUX, Gemini Imagen, and local procedural rendering."""

import io
import json
from pathlib import Path
from typing import Literal

import httpx
from PIL import Image, ImageDraw

from src.core.config import settings


class ImageGenerationService:
    """Generates authentic or conceptual AI visual assets for abstract or futuristic shots."""

    def __init__(
        self,
        provider: Literal["flux", "gemini", "local", "fallback"] | None = None,
        flux_api_key: str | None = None,
        flux_endpoint: str | None = None,
        gemini_api_key: str | None = None,
        output_dir: Path | None = None,
    ) -> None:
        self.provider = provider or settings.image_generation_provider
        self.flux_api_key = flux_api_key or settings.flux_api_key
        self.flux_endpoint = flux_endpoint or settings.flux_endpoint
        self.gemini_api_key = gemini_api_key or settings.gemini_api_key
        self.output_dir = output_dir or settings.media_cache_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_image(
        self,
        prompt: str,
        output_path: Path,
        aspect_ratio: str = "9:16",
    ) -> tuple[bool, Path]:
        """Generate an image using the configured provider with graceful fallback chain."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 1. Try FLUX API endpoint if configured
        if self.flux_api_key or self.flux_endpoint:
            ok, path = self._generate_flux(prompt, output_path, aspect_ratio)
            if ok:
                return True, path

        # 2. Try Gemini Imagen 3 if Gemini key is present
        if self.gemini_api_key and self.gemini_api_key != "your_gemini_api_key_here":
            ok, path = self._generate_gemini(prompt, output_path, aspect_ratio)
            if ok:
                return True, path

        # 3. Deterministic procedural visual generator fallback
        return self._generate_procedural_card(prompt, output_path, aspect_ratio)

    def _generate_flux(
        self,
        prompt: str,
        output_path: Path,
        aspect_ratio: str,
    ) -> tuple[bool, Path]:
        """Send prompt to FLUX API or OpenAI-compatible image endpoint."""
        endpoint = self.flux_endpoint or "https://api.together.xyz/v1/images/generations"
        headers = {
            "Authorization": f"Bearer {self.flux_api_key}",
            "Content-Type": "application/json",
        }
        width, height = (768, 1344) if aspect_ratio == "9:16" else (1344, 768)
        payload = {
            "model": "black-forest-labs/FLUX.1-schnell",
            "prompt": f"hyperrealistic tech journalism B-roll, high fidelity, 8k: {prompt}",
            "width": width,
            "height": height,
            "steps": 4,
            "response_format": "b64_json",
        }

        try:
            with httpx.Client(timeout=25.0) as client:
                resp = client.post(endpoint, json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("data", [])
                    if items:
                        import base64

                        b64_str = items[0].get("b64_json")
                        if b64_str:
                            output_path.write_bytes(base64.b64decode(b64_str))
                            return True, output_path
                        url = items[0].get("url")
                        if url:
                            img_resp = client.get(url)
                            if img_resp.status_code == 200:
                                output_path.write_bytes(img_resp.content)
                                return True, output_path
        except Exception:
            pass

        return False, output_path

    def _generate_gemini(
        self,
        prompt: str,
        output_path: Path,
        aspect_ratio: str,
    ) -> tuple[bool, Path]:
        """Invoke Gemini Imagen model for visual generation."""
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.gemini_api_key)
            g_aspect = "9:16" if aspect_ratio == "9:16" else "16:9"
            result = client.models.generate_images(
                model="imagen-3.0-generate-002",
                prompt=f"Cinematic tech journalism visual: {prompt}",
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio=g_aspect,
                    output_mime_type="image/jpeg",
                ),
            )
            for generated in result.generated_images:
                output_path.write_bytes(generated.image.image_bytes)
                return True, output_path
        except Exception:
            pass

        return False, output_path

    def _generate_procedural_card(
        self,
        prompt: str,
        output_path: Path,
        aspect_ratio: str,
    ) -> tuple[bool, Path]:
        """Synthesize high-contrast futuristic visual artwork as reliable offline fallback."""
        width, height = (1080, 1920) if aspect_ratio == "9:16" else (1920, 1080)
        img = Image.new("RGB", (width, height), color=(8, 12, 22))
        draw = ImageDraw.Draw(img)

        # Draw tech matrix grid lines
        grid_step = 60
        for x in range(0, width, grid_step):
            draw.line([(x, 0), (x, height)], fill=(18, 28, 48), width=1)
        for y in range(0, height, grid_step):
            draw.line([(0, y), (width, y)], fill=(18, 28, 48), width=1)

        # Draw luminous cyber tech concentric circles
        center_x, center_y = width // 2, height // 2
        for r in range(120, min(width, height) // 2, 80):
            draw.ellipse(
                [center_x - r, center_y - r, center_x + r, center_y + r],
                outline=(34, 211, 238),
                width=2,
            )

        # Save generated visual
        output_path = output_path.with_suffix(".png")
        img.save(str(output_path), "PNG")
        return True, output_path
