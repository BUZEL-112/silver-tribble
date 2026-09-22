"""YouTube publishing package generator for titles, descriptions, chapters, and hashtags."""

import json
from pathlib import Path
from typing import Any

from src.core.config import settings
from src.models.entities import RenderJob, ScriptRecord
from src.models.schemas import RenderBeatProp, YouTubeChapter, YouTubeMetadata
from src.services.storage_service import StorageService, get_storage_service


class YouTubeMetadataService:
    """Produces YouTube titles, descriptions with chapters, and SEO tags."""

    def __init__(self, storage_service: StorageService | None = None) -> None:
        self.storage = storage_service or get_storage_service()

    @staticmethod
    def format_timestamp(seconds: float) -> str:
        """Format total seconds into MM:SS timestamp string."""
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins:02d}:{secs:02d}"

    def build_chapters(
        self,
        beats: list[dict[str, Any]] | list[RenderBeatProp],
        total_duration: float,
    ) -> list[YouTubeChapter]:
        """Convert beat boundaries into YouTube-compatible chapter timestamps."""
        chapters: list[YouTubeChapter] = []
        if not beats:
            chapters.append(
                YouTubeChapter(
                    title="Introduction",
                    timestamp="00:00",
                    seconds=0.0,
                )
            )
            return chapters

        # Ensure first chapter always begins at 00:00 using first beat header if present
        first_title = "Introduction & Overview"
        if beats:
            first_b = beats[0]
            cand = getattr(first_b, "on_screen_text", None)
            if not cand and isinstance(first_b, dict):
                cand = (
                    first_b.get("header")
                    or first_b.get("title")
                    or first_b.get("on_screen_text")
                    or first_b.get("visual_direction")
                )
            if cand:
                first_title = str(cand).strip().title()

        chapters.append(
            YouTubeChapter(
                title=first_title,
                timestamp="00:00",
                seconds=0.0,
            )
        )

        for b in beats:
            start_t = getattr(b, "start_time", None)
            if start_t is None and isinstance(b, dict):
                start_t = b.get("start_time") if "start_time" in b else b.get("timestamp", 0.0)
            start_t = float(start_t or 0.0)

            title_candidate = getattr(b, "on_screen_text", None)
            if not title_candidate and isinstance(b, dict):
                title_candidate = (
                    b.get("header")
                    or b.get("title")
                    or b.get("on_screen_text")
                    or b.get("visual_direction")
                )
            title = str(title_candidate or "Story Beat").strip()

            if start_t > 2.0 and start_t < total_duration - 1.0:
                ts = self.format_timestamp(start_t)
                chapters.append(
                    YouTubeChapter(
                        title=title.title(),
                        timestamp=ts,
                        seconds=round(start_t, 2),
                    )
                )

        return chapters

    def generate_metadata(
        self,
        script: ScriptRecord | None = None,
        job: RenderJob | None = None,
        title: str | None = None,
        full_narration: str | None = None,
        beats: list[dict[str, Any]] | list[RenderBeatProp] | None = None,
        captions: list[Any] | None = None,
        duration_seconds: float = 30.0,
        aspect_ratio: str = "9:16",
    ) -> YouTubeMetadata:
        """Generate click-worthy title options, timestamped chapters, and tags."""
        base_title = title or (script.title if script else None) or "AI Breakthrough Update"
        clean_title = base_title.replace(":", " - ").strip()

        title_options = [
            clean_title,
            f"Why Everyone Is Talking About {clean_title}...",
            f"The Real Truth Behind {clean_title}",
        ]

        resolved_beats = beats or (script.beats if script else None) or []
        chapters = self.build_chapters(resolved_beats, duration_seconds)

        chapters_text = "\n".join(f"{c.timestamp} - {c.title}" for c in chapters)

        target_aspect = aspect_ratio or (job.aspect_ratio if job else None) or "9:16"
        hashtags = [
            "#ArtificialIntelligence",
            "#AINews",
            "#TechNews",
            "#MachineLearning",
            "#Shorts" if target_aspect == "9:16" else "#TechAnalysis",
        ]

        description_lines = [
            f"{base_title}: An in-depth breakdown of the latest AI news and research developments.",
            "",
            "Chapters:",
            chapters_text,
            "",
            "Subscribe for daily comedic, retention-tuned AI updates.",
            " ".join(hashtags),
        ]
        description = "\n".join(description_lines)

        tags = [
            "ai news",
            "artificial intelligence",
            "tech news",
            "machine learning",
            "future tech",
            "deep learning",
            base_title.lower(),
        ]

        return YouTubeMetadata(
            title_options=title_options,
            description=description,
            chapters=chapters,
            tags=tags,
            hashtags=hashtags,
        )

    def save_metadata(self, job_id: int, metadata: YouTubeMetadata) -> Path:
        """Persist metadata payload to disk as JSON artifact."""
        target_dir = settings.storage_local_dir / "youtube"
        target_dir.mkdir(parents=True, exist_ok=True)
        dest = target_dir / f"metadata_job_{job_id}.json"
        dest.write_text(json.dumps(metadata.model_dump(), indent=2), encoding="utf-8")
        return dest
