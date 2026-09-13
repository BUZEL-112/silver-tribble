"""Prefect orchestration workflow coordinating end-to-end video production."""

from pathlib import Path
from prefect import flow, task
from src.core.config import settings
from src.core.database import get_session, init_db
from src.repositories.article_repository import ArticleRepository
from src.repositories.cost_repository import CostRepository
from src.repositories.render_repository import RenderRepository
from src.repositories.script_repository import ScriptRepository
from src.services.caption_service import CaptionService
from src.services.clustering_service import ClusteringService
from src.services.render_service import RenderService
from src.services.rss_service import RssService
from src.services.script_service import ScriptService
from src.services.storage_service import get_storage_service
from src.services.tts_service import TtsService


@task(name="ingest_rss_feeds", retries=2, retry_delay_seconds=5)
def ingest_feeds_task() -> int:
    """Ingest AI news RSS feeds and store new articles."""
    rss_service = RssService()
    items = rss_service.fetch_all_feeds()
    with get_session() as session:
        repo = ArticleRepository(session)
        saved = repo.save_feed_items(items)
        return len(saved)


@task(name="cluster_articles_task", retries=2, retry_delay_seconds=5)
def cluster_articles_task() -> list[int]:
    """Compute embeddings and group articles into story clusters."""
    with get_session() as session:
        article_repo = ArticleRepository(session)
        cost_repo = CostRepository(session)
        clustering_service = ClusteringService(article_repo, cost_repo)

        clustering_service.generate_embeddings_for_new_articles()
        clusters = clustering_service.cluster_recent_articles()
        return [c.id for c in clusters]


@task(name="generate_script_task", retries=2, retry_delay_seconds=5)
def generate_script_task(cluster_id: int, aspect_ratio: str = "9:16") -> int:
    """Generate structured beat sheet and comedic narration for a story cluster."""
    with get_session() as session:
        article_repo = ArticleRepository(session)
        script_repo = ScriptRepository(session)
        cost_repo = CostRepository(session)
        script_service = ScriptService(article_repo, script_repo, cost_repo)

        script_record = script_service.generate_full_script(
            cluster_id=cluster_id,
            aspect_ratio=aspect_ratio,
        )
        return script_record.id


@task(name="synthesize_voice_and_captions_task", retries=2, retry_delay_seconds=5)
def voice_and_captions_task(
    script_id: int,
    aspect_ratio: str = "9:16",
) -> tuple[int, str, str, float]:
    """Synthesize Gemini TTS audio and compute Whisper word alignment."""
    settings.ensure_directories()
    storage = get_storage_service()

    with get_session() as session:
        script_repo = ScriptRepository(session)
        render_repo = RenderRepository(session)
        cost_repo = CostRepository(session)

        script = script_repo.get_script_by_id(script_id)
        if not script:
            raise ValueError(f"Script record {script_id} not found")

        job = render_repo.create_job(script_id=script_id, aspect_ratio=aspect_ratio)

        tts_service = TtsService(storage, cost_repo)
        audio_path, duration = tts_service.synthesize_speech(
            text=script.full_narration,
            job_id=job.id,
        )
        render_repo.update_job_audio(job.id, audio_path, duration)

        caption_service = CaptionService(storage, cost_repo)
        captions_path, _captions = caption_service.generate_captions(
            audio_path_or_url=audio_path,
            job_id=job.id,
            reference_text=script.full_narration,
            total_duration=duration,
        )
        render_repo.update_job_captions(job.id, captions_path)

        return job.id, audio_path, captions_path, duration


@task(name="render_video_task", retries=1)
def render_video_task(job_id: int, dry_run: bool = False) -> str:
    """Build Remotion props and render final MP4 file."""
    storage = get_storage_service()

    with get_session() as session:
        render_repo = RenderRepository(session)
        cost_repo = CostRepository(session)
        script_repo = ScriptRepository(session)

        job = render_repo.get_job_by_id(job_id)
        if not job:
            raise ValueError(f"Render job {job_id} not found")

        script = script_repo.get_script_by_id(job.script_id)
        if not script:
            raise ValueError(f"Script {job.script_id} not found")

        caption_service = CaptionService(storage, cost_repo)
        _, captions = caption_service.generate_captions(
            audio_path_or_url=job.audio_path or "",
            job_id=job.id,
            reference_text=script.full_narration,
            total_duration=job.duration_seconds or 30.0,
        )

        audio_local_path = storage.get_local_path(job.audio_path or "")

        render_service = RenderService(render_repo, cost_repo, storage)
        render_service.prepare_render_props(
            job=job,
            script=script,
            captions=captions,
            audio_local_path=audio_local_path,
            duration_seconds=job.duration_seconds or 30.0,
        )

        output_path = render_service.execute_render(job_id=job.id, dry_run=dry_run)
        return str(output_path.resolve())


@flow(name="ai_news_video_pipeline", log_prints=True)
def run_video_pipeline(
    cluster_id: int | None = None,
    aspect_ratio: str = "9:16",
    dry_run: bool = False,
) -> dict[str, str]:
    """End-to-end execution flow from news clustering to finished video."""
    init_db()

    target_cluster_id = cluster_id
    if target_cluster_id is None:
        ingest_feeds_task()
        cluster_ids = cluster_articles_task()
        if not cluster_ids:
            raise RuntimeError("No story clusters found after ingestion and clustering")
        target_cluster_id = cluster_ids[0]

    script_id = generate_script_task(cluster_id=target_cluster_id, aspect_ratio=aspect_ratio)
    job_id, _audio, _captions, _duration = voice_and_captions_task(
        script_id=script_id,
        aspect_ratio=aspect_ratio,
    )
    video_path = render_video_task(job_id=job_id, dry_run=dry_run)

    return {
        "cluster_id": str(target_cluster_id),
        "script_id": str(script_id),
        "job_id": str(job_id),
        "video_path": video_path,
    }
