"""Visual asset inspection service supporting off, multimodal (VLM), and HIL modes."""

import json
import subprocess
from pathlib import Path
from typing import Literal

from src.core.config import settings


class MediaInspector:
    """Evaluates relevance and quality of candidate visual media assets."""

    def __init__(
        self,
        mode: Literal["off", "multimodal", "hil"] | None = None,
        model_name: str | None = None,
        min_score: float | None = None,
        api_key: str | None = None,
    ) -> None:
        self.mode = mode or settings.media_inspector_mode
        self.model_name = model_name or settings.media_inspector_model
        self.min_score = min_score if min_score is not None else settings.media_inspector_min_score
        self.api_key = api_key or settings.gemini_api_key

    def _extract_preview_frame(self, media_path: Path) -> Path | None:
        """Extract a single JPEG preview frame from a video or GIF."""
        if media_path.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp"]:
            return media_path

        frame_path = media_path.with_suffix(".preview.jpg")
        try:
            cmd = [
                "ffmpeg",
                "-y",
                "-ss",
                "0.5",
                "-i",
                str(media_path),
                "-vframes",
                "1",
                "-q:v",
                "3",
                str(frame_path),
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if frame_path.exists() and frame_path.stat().st_size > 0:
                return frame_path
        except Exception:
            return None
        return None

    def inspect_candidate(
        self,
        sentence_text: str,
        keywords: list[str],
        media_path: Path,
        media_type: str,
    ) -> tuple[bool, str]:
        """Inspect a candidate asset and return (approved, reason)."""
        if self.mode == "off":
            return True, "Automated inspection mode is off"

        if self.mode == "multimodal":
            return self._inspect_multimodal(sentence_text, keywords, media_path)

        if self.mode == "hil":
            return self._inspect_hil(sentence_text, keywords, media_path, media_type)

        return True, "Default pass"

    def _load_system_prompt(self) -> str:
        """Load configured system prompt override or template file."""
        if settings.prompts_media_inspector_system_prompt:
            return settings.prompts_media_inspector_system_prompt

        prompt_file = Path(settings.prompts_media_inspector_file or "prompts/media_inspector.yaml")
        if prompt_file.is_file():
            try:
                import yaml

                data = yaml.safe_load(prompt_file.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "system_prompt" in data:
                    return str(data["system_prompt"])
            except Exception:
                pass
        return "You are a strict visual quality inspector for an AI technology news channel."

    def _inspect_multimodal(
        self,
        sentence_text: str,
        keywords: list[str],
        media_path: Path,
    ) -> tuple[bool, str]:
        """Call Gemini 2.0 Flash to evaluate image/video relevance to news sentence."""
        if not self.api_key or self.api_key == "your_gemini_api_key_here":
            return True, "Gemini API key not configured; skipping VLM inspection"

        preview_frame = self._extract_preview_frame(media_path)
        if not preview_frame or not preview_frame.exists():
            return True, "Could not extract preview frame for VLM inspection"

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)
            system_instruction = self._load_system_prompt()
            user_prompt = (
                f"Narration sentence: \"{sentence_text}\"\n"
                f"Keywords: {', '.join(keywords)}\n"
                f"Threshold: Minimum score {self.min_score:.1f}/10 to approve.\n"
                "Evaluate the visual frame against the narration context."
            )

            image_bytes = preview_frame.read_bytes()
            response = client.models.generate_content(
                model=self.model_name,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                    user_prompt,
                ],
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                ),
            )

            raw_text = (response.text or "").strip()
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1].split("```")[0].strip()

            verdict = json.loads(raw_text)
            score = float(verdict.get("score", 0.0))
            approved = bool(verdict.get("approved", score >= self.min_score))
            reason = verdict.get("reason", f"VLM score: {score}")

            return approved, f"VLM (Score {score:.1f}/{self.min_score}): {reason}"

        except Exception as exc:
            return True, f"VLM inspection error fallback: {exc}"

    def _inspect_hil(
        self,
        sentence_text: str,
        keywords: list[str],
        media_path: Path,
        media_type: str,
    ) -> tuple[bool, str]:
        """Interactive Human-in-the-Loop review prompt."""
        print("\n" + "=" * 60)
        print(" [HUMAN-IN-THE-LOOP MEDIA INSPECTOR]")
        print(f" Sentence: \"{sentence_text}\"")
        print(f" Keywords: {keywords}")
        print(f" Candidate File: {media_path.name} ({media_type})")
        print("=" * 60)

        import sys

        if not sys.stdin.isatty():
            # Non-interactive headless environment: auto-approve
            return True, "HIL non-interactive fallback approval"

        choice = input("Approve this asset? [Y/n]: ").strip().lower()
        if choice in ["", "y", "yes"]:
            return True, "Approved by human reviewer"
        return False, "Rejected by human reviewer"
