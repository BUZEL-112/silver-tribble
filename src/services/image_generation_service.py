"""Image generation service supporting FLUX, Gemini Imagen, and local procedural rendering."""

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
        self._gemini_imagen_unsupported = False

    def generate_image(
        self,
        prompt: str,
        output_path: Path,
        aspect_ratio: str = "9:16",
    ) -> tuple[bool, Path]:
        """Generate an image using the configured provider with graceful fallback chain."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if self.provider in ["local", "fallback"]:
            return self._generate_procedural_card(prompt, output_path, aspect_ratio)

        # 1. Try FLUX API endpoint if configured
        if self.flux_api_key or self.flux_endpoint:
            ok, path = self._generate_flux(prompt, output_path, aspect_ratio)
            if ok:
                return True, path

        # 2. Try Gemini Imagen 3 if Gemini key is present
        if (
            not self._gemini_imagen_unsupported
            and self.gemini_api_key
            and self.gemini_api_key != "your_gemini_api_key_here"
        ):
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
            self._gemini_imagen_unsupported = True

        return False, output_path

    def _generate_procedural_card(
        self,
        prompt: str,
        output_path: Path,
        aspect_ratio: str,
    ) -> tuple[bool, Path]:
        """Synthesize high-contrast futuristic visual artwork as reliable offline fallback."""
        if aspect_ratio == "16:9":
            width, height = 1920, 1080
        elif aspect_ratio == "1:1":
            width, height = 1080, 1080
        else:
            width, height = 1080, 1920

        img = Image.new("RGB", (width, height), color=(8, 12, 22))
        draw = ImageDraw.Draw(img)

        # 1. Subtle dark gradient background
        for y in range(0, height, 4):
            ratio = y / height
            r = int(8 + 8 * (1 - ratio))
            g = int(12 + 10 * (1 - ratio))
            b = int(22 + 20 * (1 - ratio))
            draw.rectangle([0, y, width, y + 4], fill=(r, g, b))

        # 2. Tech grid matrix background
        grid_step = 60
        for x in range(0, width, grid_step):
            draw.line([(x, 0), (x, height)], fill=(16, 24, 40), width=1)
        for y in range(0, height, grid_step):
            draw.line([(0, y), (width, y)], fill=(16, 24, 40), width=1)

        # Determine theme and topic classification
        lower_prompt = prompt.lower()
        if any(
            w in lower_prompt
            for w in ["benchmark", "record", "score", "performance", "sota", "metric"]
        ):
            category = "PERFORMANCE BENCHMARKS"
            accent = (16, 185, 129)  # Emerald
            mode = "benchmark"
        elif any(
            w in lower_prompt
            for w in ["code", "developer", "debug", "refactor", "software", "terminal", "engine"]
        ):
            category = "AUTONOMOUS CODE ENGINE"
            accent = (14, 165, 233)  # Sky blue
            mode = "code"
        elif any(
            w in lower_prompt
            for w in ["edge", "legacy", "risk", "warning", "skeptic", "error", "fail"]
        ):
            category = "PRODUCTION EDGE CASES"
            accent = (245, 158, 11)  # Amber
            mode = "warning"
        elif any(
            w in lower_prompt
            for w in ["server", "datacenter", "cluster", "gpu", "chip", "hardware", "hardware"]
        ):
            category = "HARDWARE INFRASTRUCTURE"
            accent = (139, 92, 246)  # Purple
            mode = "hardware"
        else:
            category = "FRONTIER AI INTELLIGENCE"
            accent = (59, 130, 246)  # Blue
            mode = "general"

        margin_x = int(width * 0.07)
        margin_y = int(height * 0.08)

        # 3. Outer cyber telemetry frame with corner brackets
        bracket_len = min(int(width * 0.06), 48)
        # Corners
        draw.line([(margin_x, margin_y), (margin_x + bracket_len, margin_y)], fill=accent, width=3)
        draw.line([(margin_x, margin_y), (margin_x, margin_y + bracket_len)], fill=accent, width=3)
        draw.line(
            [(width - margin_x, margin_y), (width - margin_x - bracket_len, margin_y)],
            fill=accent,
            width=3,
        )
        draw.line(
            [(width - margin_x, margin_y), (width - margin_x, margin_y + bracket_len)],
            fill=accent,
            width=3,
        )
        draw.line(
            [(margin_x, height - margin_y), (margin_x + bracket_len, height - margin_y)],
            fill=accent,
            width=3,
        )
        draw.line(
            [(margin_x, height - margin_y), (margin_x, height - margin_y - bracket_len)],
            fill=accent,
            width=3,
        )
        draw.line(
            [
                (width - margin_x, height - margin_y),
                (width - margin_x - bracket_len, height - margin_y),
            ],
            fill=accent,
            width=3,
        )
        draw.line(
            [
                (width - margin_x, height - margin_y),
                (width - margin_x, height - margin_y - bracket_len),
            ],
            fill=accent,
            width=3,
        )

        # 4. Top category header badge
        badge_w = min(int(width * 0.55), 440)
        badge_h = 36
        badge_x = (width - badge_w) // 2
        badge_y = margin_y + int(height * 0.04)
        draw.rounded_rectangle(
            [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
            radius=18,
            fill=(18, 28, 46),
            outline=accent,
            width=2,
        )
        draw.text((width // 2, badge_y + badge_h // 2), category, fill=accent, anchor="mm")

        # 5. Central Graphic Demonstration Box
        box_top = badge_y + badge_h + int(height * 0.05)
        box_bottom = height - margin_y - int(height * 0.12)
        box_left = margin_x + int(width * 0.03)
        box_right = width - margin_x - int(width * 0.03)
        box_w = box_right - box_left
        box_h = box_bottom - box_top

        draw.rectangle(
            [box_left, box_top, box_right, box_bottom],
            fill=(12, 18, 30),
            outline=(30, 42, 64),
            width=2,
        )

        # Depiction specific visualization
        if mode == "code":
            # Code window title bar
            draw.rectangle([box_left, box_top, box_right, box_top + 36], fill=(18, 26, 42))
            draw.ellipse(
                [box_left + 16, box_top + 12, box_left + 28, box_top + 24], fill=(239, 68, 68)
            )
            draw.ellipse(
                [box_left + 36, box_top + 12, box_left + 48, box_top + 24], fill=(245, 158, 11)
            )
            draw.ellipse(
                [box_left + 56, box_top + 12, box_left + 68, box_top + 24], fill=(16, 185, 129)
            )
            draw.text(
                (box_left + 90, box_top + 18),
                "autonomous_agent_executor.py",
                fill=(148, 163, 184),
                anchor="lm",
            )

            # Code editor lines
            code_lines = [
                ("1", "class AutonomousCodeAgent:", (224, 231, 255)),
                ("2", "    def __init__(self, workspace_context):", (148, 163, 184)),
                ("3", "        self.context = workspace_context.load()", (96, 165, 250)),
                ("4", "        self.validator = RealtimeSelfCorrection()", (52, 211, 153)),
                ("5", " ", (255, 255, 255)),
                ("6", "    def execute_and_refactor(self, issue_spec):", (224, 231, 255)),
                ("7", "        plan = self.reasoning_engine.synthesize()", (167, 139, 250)),
                ("8", "        diff = self.code_generator.generate_patch(plan)", (56, 189, 248)),
                ("9", "        verified = self.validator.verify_tests()", (52, 211, 153)),
                ("10", "       if verified: return self.deploy(diff)", (250, 204, 21)),
            ]
            line_y = box_top + 56
            line_spacing = max(26, min(48, box_h // 14))
            for num, text_content, line_color in code_lines:
                if line_y + line_spacing > box_bottom - 20:
                    break
                draw.text((box_left + 20, line_y), num, fill=(71, 85, 105), anchor="lm")
                draw.text((box_left + 60, line_y), text_content, fill=line_color, anchor="lm")
                line_y += line_spacing

        elif mode == "benchmark":
            # High-tech benchmark scoreboard
            draw.text(
                (box_left + 24, box_top + 32),
                "SWE-BENCH ZERO-SHOT ACCURACY",
                fill=(255, 255, 255),
                anchor="lm",
            )
            metrics = [
                ("Autonomous Code Engine", 92.4, (16, 185, 129)),
                ("Frontier Model Baseline", 74.8, (59, 130, 246)),
                ("Standard Assistant", 48.2, (100, 116, 139)),
                ("Legacy System", 28.5, (71, 85, 105)),
            ]
            b_y = box_top + 80
            b_spacing = max(40, min(70, (box_h - 100) // len(metrics)))
            max_bar_w = box_w - 240
            for name, score, bar_col in metrics:
                draw.text((box_left + 24, b_y), name, fill=(203, 213, 225), anchor="lm")
                bar_len = int((score / 100.0) * max_bar_w)
                draw.rounded_rectangle(
                    [box_left + 24, b_y + 14, box_left + 24 + max_bar_w, b_y + 30],
                    radius=8,
                    fill=(24, 34, 52),
                )
                draw.rounded_rectangle(
                    [box_left + 24, b_y + 14, box_left + 24 + bar_len, b_y + 30],
                    radius=8,
                    fill=bar_col,
                )
                draw.text(
                    (box_left + 40 + max_bar_w, b_y + 22),
                    f"{score:.1f}%",
                    fill=bar_col,
                    anchor="lm",
                )
                b_y += b_spacing

        elif mode == "warning":
            # Production edge cases & verification matrix
            draw.rectangle([box_left, box_top, box_right, box_top + 40], fill=(45, 26, 14))
            draw.text(
                (box_left + 24, box_top + 20),
                "RUNTIME VERIFICATION ALERT",
                fill=(245, 158, 11),
                anchor="lm",
            )
            warnings = [
                ("[RISK]", "Legacy Monolith Multi-Tenant Edge Cases", (239, 68, 68)),
                ("[AUDIT]", "Detached Database Connection Handling", (245, 158, 11)),
                ("[TEST]", "Concurrency Lock Under Asynchronous Load", (59, 130, 246)),
                ("[STATUS]", "Fail-Fast Guardrails Actively Enforced", (16, 185, 129)),
            ]
            w_y = box_top + 80
            w_spacing = max(40, min(65, (box_h - 100) // len(warnings)))
            for tag, text_w, tag_col in warnings:
                draw.text((box_left + 24, w_y), tag, fill=tag_col, anchor="lm")
                draw.text((box_left + 100, w_y), text_w, fill=(226, 232, 240), anchor="lm")
                w_y += w_spacing

        else:
            # Neural Matrix / Cluster Telemetry
            draw.text(
                (box_left + 24, box_top + 32),
                "NEURAL REASONING ARCHITECTURE",
                fill=(255, 255, 255),
                anchor="lm",
            )
            nodes = [
                ("Transformer Attention Core", "ACTIVE", (16, 185, 129)),
                ("Realtime Feedback Loop", "RUNNING", (59, 130, 246)),
                ("Semantic Vector Memory", "SYNCED", (168, 85, 247)),
                ("Self-Healing Test Pipeline", "100%", (14, 165, 233)),
            ]
            n_y = box_top + 80
            n_spacing = max(40, min(65, (box_h - 100) // len(nodes)))
            for n_title, n_stat, n_col in nodes:
                draw.text((box_left + 24, n_y), n_title, fill=(203, 213, 225), anchor="lm")
                draw.rounded_rectangle(
                    [box_right - 140, n_y - 12, box_right - 24, n_y + 12],
                    radius=6,
                    fill=(24, 34, 52),
                    outline=n_col,
                )
                draw.text((box_right - 82, n_y), n_stat, fill=n_col, anchor="mm")
                n_y += n_spacing

        # 6. Bottom telemetry summary bar
        bot_bar_y = height - margin_y - int(height * 0.05)
        draw.line(
            [(margin_x + 20, bot_bar_y), (width - margin_x - 20, bot_bar_y)],
            fill=(30, 42, 64),
            width=1,
        )
        draw.text(
            (width // 2, bot_bar_y + 18),
            f"AI INTELLIGENCE REPORT | {aspect_ratio} FORMAT",
            fill=(100, 116, 139),
            anchor="mm",
        )

        output_path = output_path.with_suffix(".png")
        img.save(str(output_path), "PNG")
        return True, output_path
