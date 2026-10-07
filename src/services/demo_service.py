"""Zero-API-key local sandbox demo pipeline service."""

import hashlib
import shutil
import struct
import time
import uuid
import wave
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from src.core.config import settings
from src.models.entities import Article, StoryCluster
from src.models.schemas import FeedItem
from src.repositories.article_repository import ArticleRepository
from src.repositories.cost_repository import CostRepository
from src.repositories.render_repository import RenderRepository
from src.repositories.script_repository import ScriptRepository
from src.services.caption_service import CaptionService
from src.services.clustering_service import ClusteringService
from src.services.render_service import RenderService
from src.services.storage_service import StorageService, get_storage_service
from src.services.tts_service import TtsService


@dataclass
class DemoRunResult:
    """Encapsulates output artifacts and metadata from a zero-API-key demo execution."""

    article_id: int
    cluster_id: int
    script_id: int
    job_id: int
    video_path: str
    duration_seconds: float
    is_mock_render: bool
    title: str
    beats: list[dict[str, Any]]
    audio_path: str
    captions_path: str
    stage_durations: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        """Convert result object into a serializable dictionary."""
        return {
            "status": "success",
            "article_id": self.article_id,
            "cluster_id": self.cluster_id,
            "script_id": self.script_id,
            "job_id": self.job_id,
            "video_path": self.video_path,
            "duration_seconds": self.duration_seconds,
            "is_mock_render": self.is_mock_render,
            "title": self.title,
            "beats_count": len(self.beats),
            "audio_path": self.audio_path,
            "captions_path": self.captions_path,
            "stage_durations": self.stage_durations,
        }


class DemoService:
    """Orchestrates zero-API-key end-to-end sandbox pipeline demonstration."""

    def __init__(
        self,
        session: Session,
        storage_service: StorageService | None = None,
    ) -> None:
        self.session = session
        self.storage_service = storage_service or get_storage_service()
        self.article_repo = ArticleRepository(session)
        self.script_repo = ScriptRepository(session)
        self.render_repo = RenderRepository(session)
        self.cost_repo = CostRepository(session)
        self.clustering_service = ClusteringService(
            article_repo=self.article_repo,
            cost_repo=self.cost_repo,
        )
        self.caption_service = CaptionService(
            storage_service=self.storage_service,
            cost_repo=self.cost_repo,
        )

    def _seed_mock_article(self) -> Article:
        """Seed a realistic mock AI news article into the database."""
        token = uuid.uuid4().hex[:8]
        item = FeedItem(
            title="OpenAI Unveils Autonomous Code Engine With Real-Time Self-Correction",
            link=f"https://example.com/ai-news/mock-code-engine-breakthrough-{token}",
            summary=(
                "Researchers have demonstrated an autonomous code agent that "
                "actively debugs, refactors, and tests multi-tier web applications "
                "without human intervention, achieving record benchmark scores."
            ),
            source="AI News Wire",
            published_at=datetime.now(UTC),
        )
        saved = self.article_repo.save_feed_items([item])
        if not saved:
            existing = self.article_repo.get_articles(limit=1)
            if existing:
                return existing[0]
            raise RuntimeError("Failed to seed mock article into database")
        return saved[0]

    def _cluster_article(self, article: Article) -> StoryCluster:
        """Cluster seeded article using local FastEmbed or deterministic grouping."""
        # Compute embeddings for the article
        self.clustering_service.generate_embeddings_for_new_articles(article_ids=[article.id])
        clusters = self.clustering_service.cluster_recent_articles(article_ids=[article.id])

        if clusters:
            return clusters[0]

        # Explicit deterministic grouping fallback
        cluster_hash = hashlib.sha256(f"demo_cluster_{article.id}".encode()).hexdigest()[:16]
        cluster = self.article_repo.save_story_cluster(
            cluster_hash=cluster_hash,
            title=article.title,
            summary=article.summary,
            article_ids=[article.id],
            cluster_run_id=f"demo_run_{uuid.uuid4().hex[:6]}",
            run_cluster_index=1,
        )
        cluster.status = "clustered"
        self.session.flush()
        return cluster

    def _build_sample_beats(self) -> list[dict[str, Any]]:
        """Generate a structured 5-beat script outline for the demo."""
        return [
            {
                "beat_number": 1,
                "beat_type": "hook",
                "core_point": "Autonomous AI coding engine introduced",
                "on_screen_text": "AI WRITES CODE",
                "visual_direction": "Dramatic zoom on glowing terminal text",
                "estimated_duration_seconds": 1.5,
                "target_duration_seconds": 1.5,
                "narration_text": (
                    "AI agents just learned to write code without human help, "
                    "and developers are watching closely."
                ),
                "emotion": "excited",
                "shot_type": "close_up",
            },
            {
                "beat_number": 2,
                "beat_type": "context",
                "core_point": "Engine automatically repairs and deploys applications",
                "on_screen_text": "FULL-STACK REPAIR",
                "visual_direction": "Animated code diff scrolling across dark canvas",
                "estimated_duration_seconds": 1.5,
                "target_duration_seconds": 1.5,
                "narration_text": (
                    "A new autonomous engine was unveiled that can isolate bugs, "
                    "refactor modules, and test whole applications."
                ),
                "emotion": "analytical",
                "shot_type": "medium",
            },
            {
                "beat_number": 3,
                "beat_type": "breakthrough",
                "core_point": "Zero-shot benchmark record achieved",
                "on_screen_text": "RECORD BENCHMARKS",
                "visual_direction": "Glowing performance chart spiking upward",
                "estimated_duration_seconds": 1.5,
                "target_duration_seconds": 1.5,
                "narration_text": (
                    "The architecture sets state of the art results on benchmark suites "
                    "that once challenged senior engineers."
                ),
                "emotion": "triumphant",
                "shot_type": "wide",
            },
            {
                "beat_number": 4,
                "beat_type": "skepticism",
                "core_point": "Legacy production environments pose edge cases",
                "on_screen_text": "EDGE CASES REMAIN",
                "visual_direction": "Warning graphic detailing legacy software complexity",
                "estimated_duration_seconds": 1.5,
                "target_duration_seconds": 1.5,
                "narration_text": (
                    "Critics point out that legacy enterprise repositories still contain "
                    "quirks that can trip up autonomous models."
                ),
                "emotion": "skeptical",
                "shot_type": "medium",
            },
            {
                "beat_number": 5,
                "beat_type": "outro",
                "core_point": "Viewer engagement call to action",
                "on_screen_text": "SUBSCRIBE FOR AI UPDATES",
                "visual_direction": "Clean studio branding card with subscribe animation",
                "estimated_duration_seconds": 1.5,
                "target_duration_seconds": 1.5,
                "narration_text": (
                    "Subscribe for daily AI breakthroughs, and share whether you would "
                    "let an AI deploy your code."
                ),
                "emotion": "engaging",
                "shot_type": "close_up",
            },
        ]

    def _generate_deterministic_audio(
        self,
        output_path: Path,
        duration_seconds: float = 7.5,
    ) -> float:
        """Create a valid mono 24kHz PCM WAV file as a deterministic local audio fallback."""
        sample_rate = 24000
        num_samples = int(sample_rate * duration_seconds)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            # Write silence / zero amplitude PCM samples
            data = struct.pack(f"<{num_samples}h", *([0] * num_samples))
            wav_file.writeframes(data)
        return duration_seconds

    def _synthesize_speech_with_fallback(
        self,
        text: str,
        job_id: int,
    ) -> tuple[str, float]:
        """Synthesize speech using Edge-TTS with deterministic local fallback."""
        tts_service = TtsService(
            storage_service=self.storage_service,
            cost_repo=self.cost_repo,
            tts_provider="edge_tts",
        )
        try:
            return tts_service.synthesize_speech(
                text=text,
                job_id=job_id,
                voice_name="en-US-ChristopherNeural",
            )
        except Exception:
            # Deterministic local audio fallback when offline or edge-tts is unavailable
            local_wav_path = settings.storage_local_dir / f"audio/narration_job_{job_id}.wav"
            word_count = len(text.split())
            calc_duration = max(5.0, min(10.0, word_count * 0.12))
            actual_duration = self._generate_deterministic_audio(local_wav_path, calc_duration)
            destination_key = f"audio/narration_job_{job_id}.wav"
            stored_path = self.storage_service.save_file(local_wav_path, destination_key)
            self.render_repo.update_job_audio(job_id, stored_path, actual_duration)
            return stored_path, actual_duration

    def run_demo(
        self,
        aspect_ratio: str = "9:16",
        dry_run: bool = False,
        progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> DemoRunResult:
        """Execute complete zero-API-key sandbox demonstration pipeline."""
        stage_durations: dict[str, float] = {}

        def notify(stage: str, details: dict[str, Any]) -> None:
            if progress_callback:
                progress_callback(stage, details)

        # Stage 1: Seed Mock Article
        t0 = time.time()
        article = self._seed_mock_article()
        stage_durations["ingestion"] = round(time.time() - t0, 3)
        notify(
            "ingestion",
            {
                "article_id": article.id,
                "title": article.title,
                "source": article.source,
                "link": article.link,
                "elapsed": stage_durations["ingestion"],
            },
        )

        # Stage 2: Cluster Article
        t0 = time.time()
        cluster = self._cluster_article(article)
        stage_durations["clustering"] = round(time.time() - t0, 3)
        notify(
            "clustering",
            {
                "cluster_id": cluster.id,
                "cluster_hash": cluster.cluster_hash,
                "article_count": cluster.article_count,
                "elapsed": stage_durations["clustering"],
            },
        )

        # Stage 3: Generate 5-Beat Script Outline
        t0 = time.time()
        beats = self._build_sample_beats()
        full_narration = " ".join(b["narration_text"] for b in beats)
        script = self.script_repo.create_script(
            cluster_id=cluster.id,
            title=cluster.title,
            aspect_ratio=aspect_ratio,
            beats=beats,
            full_narration=full_narration,
        )
        stage_durations["scripting"] = round(time.time() - t0, 3)
        notify(
            "scripting",
            {
                "script_id": script.id,
                "title": script.title,
                "beats_count": len(beats),
                "aspect_ratio": aspect_ratio,
                "elapsed": stage_durations["scripting"],
            },
        )

        # Stage 4: Create Render Job and Synthesize Speech
        t0 = time.time()
        job = self.render_repo.create_job(script_id=script.id, aspect_ratio=aspect_ratio)
        audio_path, duration = self._synthesize_speech_with_fallback(script.full_narration, job.id)
        stage_durations["tts"] = round(time.time() - t0, 3)
        notify(
            "tts",
            {
                "job_id": job.id,
                "audio_path": audio_path,
                "duration_seconds": duration,
                "elapsed": stage_durations["tts"],
            },
        )

        # Stage 5: Align Captions
        t0 = time.time()
        captions_path, captions = self.caption_service.generate_captions(
            audio_path_or_url=audio_path,
            job_id=job.id,
            reference_text=script.full_narration,
            total_duration=duration,
        )
        self.render_repo.update_job_captions(job.id, captions_path)
        stage_durations["alignment"] = round(time.time() - t0, 3)
        notify(
            "alignment",
            {
                "captions_path": captions_path,
                "captions_count": len(captions),
                "elapsed": stage_durations["alignment"],
            },
        )

        # Stage 6: Render Remotion Video
        t0 = time.time()
        render_service = RenderService(
            render_repo=self.render_repo,
            cost_repo=self.cost_repo,
            storage_service=self.storage_service,
        )
        audio_local_path = self.storage_service.get_local_path(audio_path)
        render_service.prepare_render_props(
            job=job,
            script=script,
            captions=captions,
            audio_local_path=audio_local_path,
            duration_seconds=duration,
        )

        has_local_remotion = (
            render_service.remotion_dir / "node_modules" / ".bin" / "remotion"
        ).exists()
        has_remotion_cli = bool(shutil.which("remotion")) or has_local_remotion

        is_mock_render = dry_run or not has_remotion_cli
        if is_mock_render:
            output_path = render_service.execute_render(job_id=job.id, dry_run=True)
        else:
            try:
                output_path = render_service.execute_render(job_id=job.id, dry_run=False)
            except Exception:
                # Fallback to mock render if Remotion binary encounters an execution error
                is_mock_render = True
                output_path = render_service.execute_render(job_id=job.id, dry_run=True)

        stage_durations["render"] = round(time.time() - t0, 3)
        notify(
            "render",
            {
                "video_path": str(output_path.resolve()),
                "is_mock_render": is_mock_render,
                "elapsed": stage_durations["render"],
            },
        )

        self.session.flush()

        return DemoRunResult(
            article_id=article.id,
            cluster_id=cluster.id,
            script_id=script.id,
            job_id=job.id,
            video_path=str(output_path.resolve()),
            duration_seconds=duration,
            is_mock_render=is_mock_render,
            title=script.title,
            beats=beats,
            audio_path=audio_path,
            captions_path=captions_path,
            stage_durations=stage_durations,
        )
