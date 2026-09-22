"""Prefect orchestration workflow coordinating end-to-end video production."""

import json
from pathlib import Path
from typing import Any

from prefect import flow, task

from src.core.config import settings
from src.core.database import get_session, init_db
from src.models.schemas import SentenceMediaPlacement, WordCaption
from src.repositories.action_log_repository import ActionLogRepository
from src.repositories.article_repository import ArticleRepository
from src.repositories.asset_repository import AssetRepository
from src.repositories.cost_repository import CostRepository
from src.repositories.render_repository import RenderRepository
from src.repositories.script_repository import ScriptRepository
from src.services.caption_service import CaptionService
from src.services.clustering_service import ClusteringService
from src.services.media_service import MediaService
from src.services.render_service import RenderService
from src.services.rss_service import RssService
from src.services.script_service import ScriptService
from src.services.storage_service import get_storage_service
from src.services.subtitle_service import SubtitleService
from src.services.tts_service import TtsService
from src.services.webhook_service import WebhookService
from src.services.youtube_metadata_service import YouTubeMetadataService


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
def cluster_articles_task(
    embedding_model: str | None = None,
    litellm_url: str | None = None,
    litellm_key: str | None = None,
    openai_key: str | None = None,
    gemini_key: str | None = None,
    embedding_base_url: str | None = None,
    embedding_key: str | None = None,
) -> list[int]:
    """Compute embeddings and group articles into story clusters."""
    with get_session() as session:
        article_repo = ArticleRepository(session)
        cost_repo = CostRepository(session)
        clustering_service = ClusteringService(
            article_repo=article_repo,
            cost_repo=cost_repo,
            base_url=litellm_url,
            api_key=litellm_key,
            openai_key=openai_key,
            gemini_key=gemini_key,
            embedding_base_url=embedding_base_url,
            embedding_api_key=embedding_key,
        )

        clustering_service.generate_embeddings_for_new_articles(model=embedding_model)
        clusters = clustering_service.cluster_recent_articles()
        return [c.id for c in clusters]


@task(name="generate_script_task", retries=2, retry_delay_seconds=5)
def generate_script_task(
    cluster_id: int,
    aspect_ratio: str = "9:16",
    planner_model: str | None = None,
    writer_model: str | None = None,
    litellm_url: str | None = None,
    litellm_key: str | None = None,
    openai_key: str | None = None,
    deepseek_key: str | None = None,
    gemini_key: str | None = None,
) -> int:
    """Generate structured beat sheet and comedic narration for a story cluster."""
    with get_session() as session:
        article_repo = ArticleRepository(session)
        script_repo = ScriptRepository(session)
        cost_repo = CostRepository(session)
        script_service = ScriptService(
            article_repo=article_repo,
            script_repo=script_repo,
            cost_repo=cost_repo,
            base_url=litellm_url,
            api_key=litellm_key,
            openai_key=openai_key,
            deepseek_key=deepseek_key,
            gemini_key=gemini_key,
        )

        script_record = script_service.generate_full_script(
            cluster_id=cluster_id,
            aspect_ratio=aspect_ratio,
            planner_model=planner_model,
            writer_model=writer_model,
        )
        return script_record.id


@task(name="generate_roundup_script_task", retries=2, retry_delay_seconds=5)
def generate_roundup_script_task(
    cluster_ids: list[int],
    aspect_ratio: str = "9:16",
    writer_model: str | None = None,
    litellm_url: str | None = None,
    litellm_key: str | None = None,
    openai_key: str | None = None,
    deepseek_key: str | None = None,
    gemini_key: str | None = None,
) -> int:
    """Generate multi-story roundup script across multiple clusters."""
    with get_session() as session:
        article_repo = ArticleRepository(session)
        script_repo = ScriptRepository(session)
        cost_repo = CostRepository(session)
        script_service = ScriptService(
            article_repo=article_repo,
            script_repo=script_repo,
            cost_repo=cost_repo,
            base_url=litellm_url,
            api_key=litellm_key,
            openai_key=openai_key,
            deepseek_key=deepseek_key,
            gemini_key=gemini_key,
        )

        script_record = script_service.generate_roundup_script(
            cluster_ids=cluster_ids,
            aspect_ratio=aspect_ratio,
            model=writer_model,
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
        asset_repo = AssetRepository(session)

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

        placements: list[SentenceMediaPlacement] = []
        placements_path = settings.media_cache_dir / f"placements_job_{job.id}.json"
        if placements_path.exists():
            try:
                raw_p = json.loads(placements_path.read_text(encoding="utf-8"))
                placements = [SentenceMediaPlacement(**item) for item in raw_p]
            except Exception:
                placements = []

        has_valid_media = any(p.local_path and Path(p.local_path).exists() for p in placements)
        has_media_keys = bool(settings.pexels_api_key or settings.giphy_api_key)

        if not placements or (has_media_keys and not has_valid_media):
            media_svc = MediaService(
                storage_service=storage,
                cost_repo=cost_repo,
                asset_repo=asset_repo,
            )
            placements = media_svc.process_media_for_job(
                job_id=job.id,
                captions=captions,
                beats=script.beats,
            )
            try:
                placements_path.parent.mkdir(parents=True, exist_ok=True)
                placements_path.write_text(
                    json.dumps([p.model_dump() for p in placements], indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass

        audio_local_path = storage.get_local_path(job.audio_path or "")

        render_service = RenderService(render_repo, cost_repo, storage)
        render_service.prepare_render_props(
            job=job,
            script=script,
            captions=captions,
            audio_local_path=audio_local_path,
            duration_seconds=job.duration_seconds or 30.0,
            media_placements=placements,
            intro_delay_seconds=settings.intro_delay_seconds,
            outro_duration_seconds=settings.outro_duration_seconds,
        )

        output_path = render_service.execute_render(job_id=job.id, dry_run=dry_run)
        return str(output_path.resolve())


@flow(name="ai_news_video_pipeline", log_prints=True)
def run_video_pipeline(
    cluster_id: int | None = None,
    cluster_ids: list[int] | None = None,
    aspect_ratio: str = "9:16",
    dry_run: bool = False,
    planner_model: str | None = None,
    writer_model: str | None = None,
    embedding_model: str | None = None,
    litellm_url: str | None = None,
    litellm_key: str | None = None,
    openai_key: str | None = None,
    deepseek_key: str | None = None,
    gemini_key: str | None = None,
    embedding_base_url: str | None = None,
    embedding_key: str | None = None,
) -> dict[str, Any]:
    """End-to-end execution flow from news clustering to finished video."""
    init_db()

    # Determine target cluster(s)
    if cluster_ids and len(cluster_ids) > 1:
        # Multi-cluster roundup flow
        return run_roundup_pipeline(
            cluster_ids=cluster_ids,
            aspect_ratio=aspect_ratio,
            dry_run=dry_run,
            writer_model=writer_model,
            embedding_model=embedding_model,
            litellm_url=litellm_url,
            litellm_key=litellm_key,
            openai_key=openai_key,
            deepseek_key=deepseek_key,
            gemini_key=gemini_key,
            embedding_base_url=embedding_base_url,
            embedding_key=embedding_key,
        )

    with get_session() as session:
        action_repo = ActionLogRepository(session)
        action_repo.record_action(
            stage="pipeline",
            action="pipeline_started",
            actor="pipeline",
            status="started",
            message="Starting end-to-end video pipeline run",
            details={
                "cluster_id": cluster_id,
                "cluster_ids": cluster_ids,
                "aspect_ratio": aspect_ratio,
                "dry_run": dry_run,
            },
        )

    target_cluster_id: int
    if cluster_ids and len(cluster_ids) == 1:
        target_cluster_id = cluster_ids[0]
    elif cluster_id is not None:
        target_cluster_id = cluster_id
    else:
        ingest_feeds_task()
        discovered_ids = cluster_articles_task(
            embedding_model=embedding_model,
            litellm_url=litellm_url,
            litellm_key=litellm_key,
            openai_key=openai_key,
            gemini_key=gemini_key,
            embedding_base_url=embedding_base_url,
            embedding_key=embedding_key,
        )
        if not discovered_ids:
            raise RuntimeError("No story clusters found after ingestion and clustering")
        target_cluster_id = discovered_ids[0]

    script_id = generate_script_task(
        cluster_id=target_cluster_id,
        aspect_ratio=aspect_ratio,
        planner_model=planner_model,
        writer_model=writer_model,
        litellm_url=litellm_url,
        litellm_key=litellm_key,
        openai_key=openai_key,
        deepseek_key=deepseek_key,
        gemini_key=gemini_key,
    )
    job_id, _audio, _captions, _duration = voice_and_captions_task(
        script_id=script_id,
        aspect_ratio=aspect_ratio,
    )
    video_path = render_video_task(job_id=job_id, dry_run=dry_run)

    # Export subtitles and YouTube publishing metadata
    storage = get_storage_service()
    subtitle_paths: dict[str, str] = {}
    yt_metadata_dict: dict[str, Any] = {}
    try:
        with get_session() as session:
            job = RenderRepository(session).get_job_by_id(job_id)
            script = ScriptRepository(session).get_script_by_id(script_id)
            if job and script and job.captions_path:
                local_cap = storage.get_local_path(job.captions_path)
                if local_cap.exists():
                    raw_caps = json.loads(local_cap.read_text(encoding="utf-8"))
                    caps = [WordCaption(**c) for c in raw_caps]
                    exported = SubtitleService().export_subtitles(caps, job_id=job_id)
                    subtitle_paths = {k: str(v) for k, v in exported.items()}

                    yt_meta = YouTubeMetadataService().generate_metadata(
                        title=script.title,
                        full_narration=script.full_narration,
                        beats=script.beats if isinstance(script.beats, list) else None,
                        captions=caps,
                        duration_seconds=job.duration_seconds or 0.0,
                    )
                    yt_metadata_dict = yt_meta.model_dump()
                    meta_path = settings.storage_local_dir / f"youtube_metadata_job_{job_id}.json"
                    meta_path.write_text(json.dumps(yt_metadata_dict, indent=2), encoding="utf-8")
    except Exception:
        pass

    with get_session() as session:
        ArticleRepository(session).update_cluster_status(target_cluster_id, "completed")
        ActionLogRepository(session).record_action(
            stage="pipeline",
            action="pipeline_completed",
            actor="pipeline",
            status="success",
            message=f"Completed video pipeline for cluster {target_cluster_id}",
            job_id=job_id,
            details={"video_path": video_path, "subtitles": subtitle_paths},
        )

    WebhookService().dispatch_event(
        event_name="pipeline.completed",
        data={
            "cluster_id": target_cluster_id,
            "script_id": script_id,
            "job_id": job_id,
            "video_path": video_path,
            "subtitles": subtitle_paths,
            "youtube_metadata": yt_metadata_dict,
        },
    )

    return {
        "cluster_id": str(target_cluster_id),
        "cluster_ids": [str(target_cluster_id)],
        "script_id": str(script_id),
        "job_id": str(job_id),
        "video_path": video_path,
        "subtitles": subtitle_paths,
        "youtube_metadata": yt_metadata_dict,
    }


@flow(name="ai_news_roundup_pipeline", log_prints=True)
def run_roundup_pipeline(
    cluster_ids: list[int] | None = None,
    top_n: int = 3,
    aspect_ratio: str = "9:16",
    dry_run: bool = False,
    writer_model: str | None = None,
    embedding_model: str | None = None,
    litellm_url: str | None = None,
    litellm_key: str | None = None,
    openai_key: str | None = None,
    deepseek_key: str | None = None,
    gemini_key: str | None = None,
    embedding_base_url: str | None = None,
    embedding_key: str | None = None,
) -> dict[str, Any]:
    """End-to-end execution flow for a multi-story news roundup video."""
    init_db()

    with get_session() as session:
        action_repo = ActionLogRepository(session)
        action_repo.record_action(
            stage="pipeline",
            action="roundup_pipeline_started",
            actor="pipeline",
            status="started",
            message="Starting end-to-end roundup video pipeline run",
            details={
                "cluster_ids": cluster_ids,
                "top_n": top_n,
                "aspect_ratio": aspect_ratio,
                "dry_run": dry_run,
            },
        )

    target_cluster_ids = sorted(list(set(cluster_ids))) if cluster_ids else []
    if not target_cluster_ids:
        ingest_feeds_task()
        cluster_articles_task(
            embedding_model=embedding_model,
            litellm_url=litellm_url,
            litellm_key=litellm_key,
            openai_key=openai_key,
            gemini_key=gemini_key,
            embedding_base_url=embedding_base_url,
            embedding_key=embedding_key,
        )
        with get_session() as session:
            art_repo = ArticleRepository(session)
            recent = art_repo.get_recent_clusters(limit=top_n * 2)
            pending = [c for c in recent if c.status == "pending"]
            pool = pending if len(pending) >= top_n else recent
            target_cluster_ids = sorted([c.id for c in pool[:top_n]])

    if not target_cluster_ids:
        raise RuntimeError("No story clusters found to produce a roundup video")

    script_id = generate_roundup_script_task(
        cluster_ids=target_cluster_ids,
        aspect_ratio=aspect_ratio,
        writer_model=writer_model,
        litellm_url=litellm_url,
        litellm_key=litellm_key,
        openai_key=openai_key,
        deepseek_key=deepseek_key,
        gemini_key=gemini_key,
    )

    job_id, _audio, _captions, _duration = voice_and_captions_task(
        script_id=script_id,
        aspect_ratio=aspect_ratio,
    )
    video_path = render_video_task(job_id=job_id, dry_run=dry_run)

    # Export subtitles and YouTube publishing metadata
    storage = get_storage_service()
    subtitle_paths: dict[str, str] = {}
    yt_metadata_dict: dict[str, Any] = {}
    try:
        with get_session() as session:
            job = RenderRepository(session).get_job_by_id(job_id)
            script = ScriptRepository(session).get_script_by_id(script_id)
            if job and script and job.captions_path:
                local_cap = storage.get_local_path(job.captions_path)
                if local_cap.exists():
                    raw_caps = json.loads(local_cap.read_text(encoding="utf-8"))
                    caps = [WordCaption(**c) for c in raw_caps]
                    exported = SubtitleService().export_subtitles(caps, job_id=job_id)
                    subtitle_paths = {k: str(v) for k, v in exported.items()}

                    yt_meta = YouTubeMetadataService().generate_metadata(
                        title=script.title,
                        full_narration=script.full_narration,
                        beats=script.beats if isinstance(script.beats, list) else None,
                        captions=caps,
                        duration_seconds=job.duration_seconds or 0.0,
                    )
                    yt_metadata_dict = yt_meta.model_dump()
                    meta_path = settings.storage_local_dir / f"youtube_metadata_job_{job_id}.json"
                    meta_path.write_text(json.dumps(yt_metadata_dict, indent=2), encoding="utf-8")
    except Exception:
        pass

    with get_session() as session:
        art_repo = ArticleRepository(session)
        for cid in target_cluster_ids:
            art_repo.update_cluster_status(cid, "completed")
        ActionLogRepository(session).record_action(
            stage="pipeline",
            action="roundup_pipeline_completed",
            actor="pipeline",
            status="success",
            message=f"Completed roundup video pipeline across clusters: {target_cluster_ids}",
            job_id=job_id,
            details={
                "video_path": video_path,
                "cluster_ids": target_cluster_ids,
                "subtitles": subtitle_paths,
            },
        )

    WebhookService().dispatch_event(
        event_name="pipeline.roundup_completed",
        data={
            "cluster_ids": target_cluster_ids,
            "script_id": script_id,
            "job_id": job_id,
            "video_path": video_path,
            "subtitles": subtitle_paths,
            "youtube_metadata": yt_metadata_dict,
        },
    )

    return {
        "cluster_ids": [str(cid) for cid in target_cluster_ids],
        "script_id": str(script_id),
        "job_id": str(job_id),
        "video_path": video_path,
        "subtitles": subtitle_paths,
        "youtube_metadata": yt_metadata_dict,
    }
