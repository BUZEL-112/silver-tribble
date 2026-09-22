"""Generates high-tech 9:16 portrait visual brand cards for AI companies and models."""

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


class BrandCardService:
    """Renders cyber-aesthetic visual brand cards for tech entities and models."""

    BRAND_CONFIGS: dict[str, dict[str, Any]] = {
        "anthropic": {
            "name": "ANTHROPIC",
            "accent": (217, 119, 6),  # Warm amber / coral
            "tag": "FRONTIER AI RESEARCH",
            "sub": "Claude Models & Constitutional AI",
        },
        "openai": {
            "name": "OPENAI",
            "accent": (16, 163, 127),  # OpenAI emerald
            "tag": "FRONTIER AI LAB",
            "sub": "GPT & Reasoning Architecture",
        },
        "deepseek": {
            "name": "DEEPSEEK",
            "accent": (2, 132, 199),  # Sky blue
            "tag": "OPEN REASONING AI",
            "sub": "DeepSeek-R1 & Open Architecture",
        },
        "nvidia": {
            "name": "NVIDIA",
            "accent": (118, 185, 0),  # Nvidia green
            "tag": "AI HARDWARE & ACCELERATION",
            "sub": "Blackwell & GPU Superclusters",
        },
        "google": {
            "name": "GOOGLE GEMINI",
            "accent": (66, 133, 244),  # Google blue
            "tag": "MULTIMODAL INTELLIGENCE",
            "sub": "Gemini Ultra & Deep Research",
        },
        "meta": {
            "name": "META AI",
            "accent": (37, 99, 235),  # Meta blue
            "tag": "OPEN SOURCE AI",
            "sub": "Llama Open Models Ecosystem",
        },
        "microsoft": {
            "name": "MICROSOFT",
            "accent": (0, 164, 239),  # Cyan
            "tag": "CLOUD & ENTERPRISE AI",
            "sub": "Azure Supercomputing & Copilot",
        },
        "tsmc": {
            "name": "TSMC",
            "accent": (239, 68, 68),  # Red
            "tag": "SEMICONDUCTOR FABRICATION",
            "sub": "Advanced Silicon Foundry",
        },
        "xai": {
            "name": "xAI",
            "accent": (248, 250, 252),  # Clean white / slate
            "tag": "FRONTIER AI SYSTEMS",
            "sub": "Grok & Colossus Supercomputer",
        },
    }

    def detect_brand(self, text: str) -> str | None:
        """Find matching known tech entity in text."""
        lower = text.lower()
        for key in self.BRAND_CONFIGS:
            if key in lower:
                return key
        if "claude" in lower:
            return "anthropic"
        if "chatgpt" in lower or "gpt" in lower:
            return "openai"
        if "blackwell" in lower or "jensen" in lower or "geforce" in lower:
            return "nvidia"
        if "gemini" in lower or "deepmind" in lower:
            return "google"
        if "llama" in lower:
            return "meta"
        if "grok" in lower or "colossus" in lower:
            return "xai"
        return None

    def generate_card(
        self,
        entity_key: str,
        output_path: Path,
        custom_subtitle: str | None = None,
        width: int = 720,
        height: int = 1280,
    ) -> Path:
        """Create a 9:16 high-tech brand card PNG image."""
        cfg = self.BRAND_CONFIGS.get(
            entity_key.lower(),
            {
                "name": entity_key.upper(),
                "accent": (59, 130, 246),
                "tag": "TECHNOLOGY INTELLIGENCE",
                "sub": custom_subtitle or "AI Industry Analysis",
            },
        )

        accent = cfg["accent"]
        name = cfg["name"]
        tag = cfg["tag"]
        sub = custom_subtitle or cfg["sub"]

        # 1. Base dark obsidian canvas
        img = Image.new("RGB", (width, height), color=(8, 12, 20))
        draw = ImageDraw.Draw(img)

        # 2. Gradient background lighting effect
        for y in range(0, height, 4):
            ratio = y / height
            # Dark indigo at top to slate black at bottom
            r = int(8 + 12 * (1 - ratio))
            g = int(12 + 16 * (1 - ratio))
            b = int(24 + 32 * (1 - ratio))
            draw.rectangle([0, y, width, y + 4], fill=(r, g, b))

        # 3. Subtle cyber circuit grid lines
        grid_color = (20, 28, 44)
        for x in range(0, width, 60):
            draw.line([(x, 0), (x, height)], fill=grid_color, width=1)
        for y in range(0, height, 60):
            draw.line([(0, y), (width, y)], fill=grid_color, width=1)

        # 4. Central card border frame with glowing corner brackets
        margin_x = 44
        margin_y = 120
        card_box = [margin_x, margin_y, width - margin_x, height - margin_y]

        # Inner dark card fill
        draw.rectangle(card_box, fill=(12, 18, 30), outline=(30, 41, 59), width=2)

        # Corner bracket highlights with brand accent color
        corner_len = 36
        c_w = 4
        # Top-left
        draw.line([(margin_x, margin_y), (margin_x + corner_len, margin_y)], fill=accent, width=c_w)
        draw.line([(margin_x, margin_y), (margin_x, margin_y + corner_len)], fill=accent, width=c_w)
        # Top-right
        draw.line(
            [(width - margin_x, margin_y), (width - margin_x - corner_len, margin_y)],
            fill=accent,
            width=c_w,
        )
        draw.line(
            [(width - margin_x, margin_y), (width - margin_x, margin_y + corner_len)],
            fill=accent,
            width=c_w,
        )
        # Bottom-left
        draw.line(
            [(margin_x, height - margin_y), (margin_x + corner_len, height - margin_y)],
            fill=accent,
            width=c_w,
        )
        draw.line(
            [(margin_x, height - margin_y), (margin_x, height - margin_y - corner_len)],
            fill=accent,
            width=c_w,
        )
        # Bottom-right
        draw.line(
            [
                (width - margin_x, height - margin_y),
                (width - margin_x - corner_len, height - margin_y),
            ],
            fill=accent,
            width=c_w,
        )
        draw.line(
            [
                (width - margin_x, height - margin_y),
                (width - margin_x, height - margin_y - corner_len),
            ],
            fill=accent,
            width=c_w,
        )

        # 5. Top category badge pill
        pill_w = 280
        pill_h = 32
        pill_x1 = (width - pill_w) // 2
        pill_y1 = margin_y + 80
        draw.rounded_rectangle(
            [pill_x1, pill_y1, pill_x1 + pill_w, pill_y1 + pill_h],
            radius=16,
            fill=(20, 30, 48),
            outline=accent,
            width=1,
        )
        draw.text((width // 2, pill_y1 + pill_h // 2), tag, fill=accent, anchor="mm")

        # 6. Central Brand Name
        center_y = height // 2 - 40
        # Brand decorative icon line
        draw.line(
            [(width // 2 - 40, center_y - 80), (width // 2 + 40, center_y - 80)],
            fill=accent,
            width=3,
        )
        draw.text((width // 2, center_y), name, fill=(255, 255, 255), anchor="mm")

        # 7. Subtitle description
        draw.text((width // 2, center_y + 80), sub, fill=(148, 163, 184), anchor="mm")

        # 8. Bottom tech indicator bar
        bot_y = height - margin_y - 80
        draw.line(
            [(margin_x + 60, bot_y), (width - margin_x - 60, bot_y)], fill=(30, 41, 59), width=1
        )
        draw.text(
            (width // 2, bot_y + 30),
            "INDUSTRY DEVELOPMENT REPORT",
            fill=(100, 116, 139),
            anchor="mm",
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path, "PNG")
        return output_path
