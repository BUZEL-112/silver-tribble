"""FastAPI web server and interactive dashboard for AI Video Production Platform."""

import json
import math
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.core.config import find_yaml_config_path, reload_settings, settings
from src.core.database import get_session, init_db
from src.flows.video_pipeline_flow import run_roundup_pipeline, run_video_pipeline
from src.models.schemas import (
    HealthStatus,
    PruneResult,
    ScriptAuditReport,
    SentenceMediaPlacement,
    VisualAssetResponse,
    WordCaption,
    YouTubeMetadata,
)
from src.repositories.action_log_repository import ActionLogRepository
from src.repositories.article_repository import ArticleRepository
from src.repositories.asset_repository import AssetRepository
from src.repositories.cost_repository import CostRepository
from src.repositories.render_repository import RenderRepository
from src.repositories.script_repository import ScriptRepository
from src.services.cache_pruning_service import CachePruningService
from src.services.caption_service import CaptionService
from src.services.clustering_service import ClusteringService
from src.services.health_service import HealthService
from src.services.media_service import MediaService
from src.services.render_service import RenderService
from src.services.rss_service import RssService
from src.services.script_auditor_service import ScriptAuditorService
from src.services.script_service import ScriptService
from src.services.storage_service import get_storage_service
from src.services.subtitle_service import SubtitleService
from src.services.tts_service import TtsService
from src.services.youtube_metadata_service import YouTubeMetadataService

settings.ensure_directories()
init_db()

app = FastAPI(
    title="Modular AI Video Production Platform",
    description="REST API and visual operations dashboard for automated video creation",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static asset directories
if settings.media_cache_dir.exists():
    media_dir = str(settings.media_cache_dir.resolve())
    app.mount("/static/media", StaticFiles(directory=media_dir), name="media")

if settings.remotion_output_dir.exists():
    videos_dir = str(settings.remotion_output_dir.resolve())
    app.mount("/static/videos", StaticFiles(directory=videos_dir), name="videos")

if (settings.storage_local_dir / "audio").exists():
    audio_dir = str((settings.storage_local_dir / "audio").resolve())
    app.mount("/static/audio", StaticFiles(directory=audio_dir), name="audio")


class ScriptCreateRequest(BaseModel):
    cluster_id: int
    aspect_ratio: str = "9:16"
    planner_model: str | None = None
    writer_model: str | None = None


class VoiceCreateRequest(BaseModel):
    script_id: int
    aspect_ratio: str = "9:16"


class MediaCreateRequest(BaseModel):
    job_id: int


class RenderCreateRequest(BaseModel):
    job_id: int
    dry_run: bool = False


class MediaPlacementUpdateRequest(BaseModel):
    query: str | None = None
    file_path: str | None = None
    url: str | None = None
    provider: str | None = "pexels"


class JobReRenderRequest(BaseModel):
    dry_run: bool = False
    show_material_indices: bool = False


class PipelineRunRequest(BaseModel):
    cluster_id: int | None = None
    cluster_ids: list[int] | None = None
    aspect_ratio: str = "9:16"
    dry_run: bool = False


class RoundupRunRequest(BaseModel):
    cluster_ids: list[int] | None = None
    top_n: int = 3
    aspect_ratio: str = "9:16"
    dry_run: bool = False
    writer_model: str | None = None


class RoundupScriptRequest(BaseModel):
    cluster_ids: list[int] | None = None
    top_n: int = 3
    aspect_ratio: str = "9:16"
    writer_model: str | None = None


class ScriptUpdateRequest(BaseModel):
    title: str | None = None
    full_narration: str | None = None
    beats: list[dict[str, Any]] | None = None


WatermarkPosition = Literal["top-right", "top-left", "bottom-right", "bottom-left"]


class SettingsUpdateRequest(BaseModel):
    watermark_text: str | None = None
    watermark_image_path: str | None = None
    watermark_position: WatermarkPosition | None = None
    watermark_opacity: float | None = Field(default=None, ge=0.0, le=1.0)
    intro_delay_seconds: float | None = Field(default=None, ge=0.0)
    outro_duration_seconds: float | None = Field(default=None, ge=0.0)
    cluster_review_timeout_seconds: float | None = Field(default=None, ge=1.0)
    channel_badge_text: str | None = None
    caption_style: str | None = None
    caption_level: float | None = Field(default=None, ge=5.0, le=90.0)
    caption_font_size: int | None = Field(default=None, ge=20, le=96)
    caption_uppercase: bool | None = None
    subscribe_title: str | None = None
    subscribe_subtitle: str | None = None
    subscribe_button_text: str | None = None
    subscribe_duration_seconds: float | None = Field(default=None, ge=0.0)
    subscribe_style: str | None = None
    subscribe_enabled: bool | None = None
    horizontal_watermark_position: WatermarkPosition | None = None
    horizontal_caption_level: float | None = Field(default=None, ge=5.0, le=90.0)
    horizontal_channel_badge_text: str | None = None
    horizontal_lower_third_title: str | None = None


class ConfigLoadRequest(BaseModel):
    config_path: str


class ConfigSaveRequest(BaseModel):
    config_path: str = "config.yaml"
    yaml_content: str


# ---------------------------------------------------------------------------
# REST API Endpoints
# ---------------------------------------------------------------------------


@app.post("/api/pipeline/ingest")
def trigger_ingest() -> dict[str, Any]:
    """Trigger RSS feed ingestion and save new articles."""
    try:
        service = RssService()
        items = service.fetch_all_feeds()
        with get_session() as session:
            art_repo = ArticleRepository(session)
            action_repo = ActionLogRepository(session)
            with action_repo.track_operation(
                stage="ingest",
                action="fetch_rss_feeds",
                actor="web",
                details={"fetched_count": len(items)},
            ):
                saved = art_repo.save_feed_items(items)

        return {
            "status": "success",
            "articles_fetched": len(items),
            "new_articles_saved": len(saved),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/pipeline/cluster")
def trigger_cluster(
    threshold: float = Query(0.82),
    model: str | None = Query(None),
) -> dict[str, Any]:
    """Trigger embeddings generation and story clustering."""
    try:
        with get_session() as session:
            art_repo = ArticleRepository(session)
            cost_repo = CostRepository(session)
            action_repo = ActionLogRepository(session)
            service = ClusteringService(article_repo=art_repo, cost_repo=cost_repo)

            with action_repo.track_operation(
                stage="cluster",
                action="cluster_articles",
                actor="web",
                details={"threshold": threshold, "model": model},
            ):
                embedded_count = service.generate_embeddings_for_new_articles(model=model)
                clusters = service.cluster_recent_articles(threshold=threshold)

            top_id = clusters[0].id if clusters else None
            clusters_count = len(clusters)

        return {
            "status": "success",
            "articles_embedded": embedded_count,
            "clusters_created": clusters_count,
            "top_cluster_id": top_id,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/pipeline/script")
def trigger_script(req: ScriptCreateRequest) -> dict[str, Any]:
    """Generate beat sheet and dialogue narration for a story cluster."""
    try:
        with get_session() as session:
            art_repo = ArticleRepository(session)
            script_repo = ScriptRepository(session)
            cost_repo = CostRepository(session)
            action_repo = ActionLogRepository(session)

            service = ScriptService(
                article_repo=art_repo,
                script_repo=script_repo,
                cost_repo=cost_repo,
            )

            with action_repo.track_operation(
                stage="script",
                action="generate_script",
                actor="web",
                details={"cluster_id": req.cluster_id, "aspect_ratio": req.aspect_ratio},
            ):
                record = service.generate_full_script(
                    cluster_id=req.cluster_id,
                    aspect_ratio=req.aspect_ratio,
                    planner_model=req.planner_model,
                    writer_model=req.writer_model,
                )
            record_id = record.id
            record_title = record.title
            record_narration = record.full_narration

        words = record_narration.split()
        return {
            "status": "success",
            "script_id": record_id,
            "title": record_title,
            "word_count": len(words),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/pipeline/voice")
def trigger_voice(req: VoiceCreateRequest) -> dict[str, Any]:
    """Synthesize voice track and compute Whisper caption alignment."""
    try:
        storage = get_storage_service()
        with get_session() as session:
            script_repo = ScriptRepository(session)
            render_repo = RenderRepository(session)
            cost_repo = CostRepository(session)
            action_repo = ActionLogRepository(session)

            script_record = script_repo.get_script_by_id(req.script_id)
            if not script_record:
                raise HTTPException(status_code=404, detail=f"Script {req.script_id} not found")

            job = render_repo.create_job(script_id=req.script_id, aspect_ratio=req.aspect_ratio)

            with action_repo.track_operation(
                stage="voice",
                action="synthesize_voice_and_captions",
                actor="web",
                job_id=job.id,
                details={"script_id": req.script_id},
            ):
                tts = TtsService(storage, cost_repo)
                audio_path, duration = tts.synthesize_speech(script_record.full_narration, job.id)
                render_repo.update_job_audio(job.id, audio_path, duration)

                captions_service = CaptionService(storage, cost_repo)
                captions_path, _captions = captions_service.generate_captions(
                    audio_path, job.id, script_record.full_narration, duration
                )
                render_repo.update_job_captions(job.id, captions_path)
            job_id = job.id

        return {
            "status": "success",
            "job_id": job_id,
            "audio_path": audio_path,
            "duration": round(duration, 2),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/pipeline/media")
def trigger_media(req: MediaCreateRequest) -> dict[str, Any]:
    """Retrieve sentence-level visual assets (Pexels / Giphy) for a render job."""
    try:
        storage = get_storage_service()
        with get_session() as session:
            render_repo = RenderRepository(session)
            script_repo = ScriptRepository(session)
            cost_repo = CostRepository(session)
            action_repo = ActionLogRepository(session)

            job = render_repo.get_job_by_id(req.job_id)
            if not job:
                raise HTTPException(status_code=404, detail=f"Render job {req.job_id} not found")

            script = script_repo.get_script_by_id(job.script_id)
            if not script:
                raise HTTPException(status_code=404, detail=f"Script {job.script_id} not found")

            captions: list[WordCaption] = []
            if job.captions_path:
                local_cap_path = storage.get_local_path(job.captions_path)
                if local_cap_path.exists():
                    data = json.loads(local_cap_path.read_text(encoding="utf-8"))
                    captions = [WordCaption(**item) for item in data]

            if not captions:
                caption_svc = CaptionService(storage, cost_repo)
                _, captions = caption_svc.generate_captions(
                    audio_path_or_url=job.audio_path or "",
                    job_id=job.id,
                    reference_text=script.full_narration,
                    total_duration=job.duration_seconds or 30.0,
                )

            asset_repo = AssetRepository(session)
            media_svc = MediaService(
                storage_service=storage,
                cost_repo=cost_repo,
                asset_repo=asset_repo,
            )

            with action_repo.track_operation(
                stage="media",
                action="fetch_media_assets",
                actor="web",
                job_id=job.id,
                details={"caption_count": len(captions)},
            ):
                media_items = media_svc.process_media_for_job(
                    job_id=job.id,
                    captions=captions,
                    beats=script.beats,
                )

            placements_path = settings.media_cache_dir / f"placements_job_{job.id}.json"
            placements_path.parent.mkdir(parents=True, exist_ok=True)
            placements_path.write_text(
                json.dumps([p.model_dump() for p in media_items], indent=2),
                encoding="utf-8",
            )
            job_id = job.id

        return {
            "status": "success",
            "job_id": job_id,
            "media_count": len(media_items),
            "media_items": [p.model_dump() for p in media_items],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/pipeline/render")
def trigger_render(req: RenderCreateRequest) -> dict[str, Any]:
    """Execute Remotion video render for a job."""
    try:
        storage = get_storage_service()
        with get_session() as session:
            render_repo = RenderRepository(session)
            cost_repo = CostRepository(session)
            script_repo = ScriptRepository(session)
            action_repo = ActionLogRepository(session)

            job = render_repo.get_job_by_id(req.job_id)
            if not job:
                raise HTTPException(status_code=404, detail=f"Render job {req.job_id} not found")

            script = script_repo.get_script_by_id(job.script_id)
            if not script:
                raise HTTPException(status_code=404, detail=f"Script {job.script_id} not found")

            captions: list[WordCaption] = []
            if job.captions_path:
                local_cap_path = storage.get_local_path(job.captions_path)
                if local_cap_path.exists():
                    data = json.loads(local_cap_path.read_text(encoding="utf-8"))
                    captions = [WordCaption(**item) for item in data]

            if not captions:
                caption_svc = CaptionService(storage, cost_repo)
                _, captions = caption_svc.generate_captions(
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

            if not placements:
                asset_repo = AssetRepository(session)
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

            audio_local_path = storage.get_local_path(job.audio_path or "")
            render_svc = RenderService(render_repo, cost_repo, storage)

            render_svc.prepare_render_props(
                job=job,
                script=script,
                captions=captions,
                audio_local_path=audio_local_path,
                duration_seconds=job.duration_seconds or 30.0,
                media_placements=placements,
            )

            with action_repo.track_operation(
                stage="render",
                action="render_video",
                actor="web",
                job_id=job.id,
                details={"dry_run": req.dry_run},
            ):
                output_path = render_svc.execute_render(job_id=job.id, dry_run=req.dry_run)

            job_id = job.id
            rendered_video_path = str(output_path.resolve())

        return {
            "status": "success",
            "job_id": job_id,
            "output_video_path": rendered_video_path,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/pipeline/run")
def trigger_run_all(req: PipelineRunRequest) -> dict[str, Any]:
    """Run full pipeline end-to-end from news clustering to finished video."""
    try:
        result = run_video_pipeline(
            cluster_id=req.cluster_id,
            cluster_ids=req.cluster_ids,
            aspect_ratio=req.aspect_ratio,
            dry_run=req.dry_run,
        )
        return {"status": "success", **result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/pipeline/roundup")
def trigger_roundup_pipeline(req: RoundupRunRequest) -> dict[str, Any]:
    """Run multi-story roundup pipeline end-to-end to finished video."""
    try:
        sorted_ids = sorted(list(set(req.cluster_ids))) if req.cluster_ids else None
        result = run_roundup_pipeline(
            cluster_ids=sorted_ids,
            top_n=req.top_n,
            aspect_ratio=req.aspect_ratio,
            dry_run=req.dry_run,
            writer_model=req.writer_model,
        )
        return {"status": "success", **result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/pipeline/roundup-script")
def trigger_roundup_script(req: RoundupScriptRequest) -> dict[str, Any]:
    """Generate multi-story news roundup script across clusters."""
    try:
        with get_session() as session:
            art_repo = ArticleRepository(session)
            script_repo = ScriptRepository(session)
            cost_repo = CostRepository(session)
            action_repo = ActionLogRepository(session)

            if req.cluster_ids:
                target_ids = sorted(list(set(req.cluster_ids)))
            else:
                recent = art_repo.get_recent_clusters(limit=req.top_n * 2)
                pending = [c for c in recent if c.status == "pending"]
                pool = pending if len(pending) >= req.top_n else recent
                target_ids = sorted([c.id for c in pool[: req.top_n]])

            if not target_ids:
                raise HTTPException(status_code=404, detail="No story clusters found for roundup.")

            service = ScriptService(
                article_repo=art_repo,
                script_repo=script_repo,
                cost_repo=cost_repo,
            )

            with action_repo.track_operation(
                stage="script",
                action="generate_roundup_script",
                actor="web",
                details={"cluster_ids": target_ids, "aspect_ratio": req.aspect_ratio},
            ):
                record = service.generate_roundup_script(
                    cluster_ids=target_ids,
                    aspect_ratio=req.aspect_ratio,
                    model=req.writer_model,
                )

            words = record.full_narration.split()
            return {
                "status": "success",
                "script_id": record.id,
                "title": record.title,
                "cluster_ids": target_ids,
                "beats_count": len(record.beats),
                "word_count": len(words),
            }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/assets", response_model=list[VisualAssetResponse])
def get_assets(
    limit: int = Query(50, ge=1, le=200),
    provider: str | None = Query(None),
    emotion: str | None = Query(None),
) -> list[VisualAssetResponse]:
    """Query visual assets from the reusable asset library."""
    with get_session() as session:
        repo = AssetRepository(session)
        records = repo.list_assets(limit=limit, provider=provider, emotion=emotion)
        return [
            VisualAssetResponse(
                id=r.id,
                asset_hash=r.asset_hash,
                source_url=r.source_url,
                local_path=r.local_path,
                media_type=r.media_type,
                provider=r.provider,
                query=r.query or "",
                tags=r.tags or [],
                emotion_tags=r.emotion_tags or [],
                shot_type=r.shot_type,
                aspect_ratio=r.aspect_ratio,
                vlm_score=r.vlm_score,
                vlm_reason=r.vlm_reason,
                usage_count=r.usage_count,
                created_at=r.created_at,
                last_used_at=r.last_used_at,
            )
            for r in records
        ]


@app.get("/api/logs")
def get_logs(
    limit: int = Query(100, ge=1, le=500),
    stage: str | None = Query(None),
    status: str | None = Query(None),
) -> list[dict[str, Any]]:
    """Query recent action logs."""
    with get_session() as session:
        repo = ActionLogRepository(session)
        logs = repo.get_recent_logs(limit=limit, stage=stage, status=status)
        return [
            {
                "id": log.id,
                "stage": log.stage,
                "action": log.action,
                "actor": log.actor,
                "status": log.status,
                "job_id": log.job_id,
                "message": log.message,
                "details": log.details,
                "duration_seconds": log.duration_seconds,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ]


@app.get("/api/clusters")
def get_clusters(
    page: int | None = Query(None, ge=1, description="Page number for pagination"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page"),
    limit: int | None = Query(None, ge=1, le=200, description="Legacy limit parameter"),
    status: str | None = Query(None, description="Filter by status (pending, completed)"),
    search: str | None = Query(None, description="Search keyword in title or summary"),
    include_articles: bool = Query(True, description="Whether to include member articles"),
    response: Response = None,
) -> Any:
    """List story clusters with support for pagination, search, and constituent articles."""
    with get_session() as session:
        art_repo = ArticleRepository(session)

        if page is not None:
            clusters, total = art_repo.list_story_clusters_paginated(
                status=status,
                search=search,
                page=page,
                page_size=page_size,
            )
            total_pages = math.ceil(total / page_size) if page_size > 0 else 1
        else:
            effective_limit = limit or 50
            clusters = art_repo.get_recent_clusters(limit=effective_limit)
            total = art_repo.count_story_clusters(status=status, search=search)
            total_pages = 1

        if response is not None:
            response.headers["X-Total-Count"] = str(total)

        articles_map: dict[int, dict[str, Any]] = {}
        if include_articles:
            all_art_ids = [aid for c in clusters for aid in (c.article_ids or [])]
            if all_art_ids:
                articles = art_repo.get_articles_by_ids(all_art_ids)
                articles_map = {
                    a.id: {
                        "id": a.id,
                        "title": a.title,
                        "link": a.link,
                        "source": a.source,
                        "summary": a.summary,
                        "published_at": a.published_at.isoformat() if a.published_at else None,
                        "created_at": a.created_at.isoformat() if a.created_at else None,
                    }
                    for a in articles
                }

        results: list[dict[str, Any]] = []
        for c in clusters:
            cluster_articles = (
                [articles_map[aid] for aid in (c.article_ids or []) if aid in articles_map]
                if include_articles
                else []
            )
            results.append(
                {
                    "id": c.id,
                    "cluster_hash": c.cluster_hash,
                    "title": c.title,
                    "summary": c.summary,
                    "article_count": c.article_count,
                    "article_ids": c.article_ids or [],
                    "articles": cluster_articles,
                    "status": c.status,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                }
            )

        if page is not None:
            return {
                "items": results,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
            }
        return results


@app.get("/api/clusters/count")
def get_clusters_count(
    status: str | None = Query(None, description="Filter by status"),
    search: str | None = Query(None, description="Search keyword"),
) -> dict[str, int]:
    """Retrieve fast aggregate count of story clusters."""
    with get_session() as session:
        art_repo = ArticleRepository(session)
        count = art_repo.count_story_clusters(status=status, search=search)
        return {"count": count}


@app.get("/api/stats")
def get_platform_stats() -> dict[str, Any]:
    """Retrieve aggregate KPI metrics across all subsystems."""
    with get_session() as session:
        art_repo = ArticleRepository(session)
        render_repo = RenderRepository(session)
        asset_repo = AssetRepository(session)
        cost_repo = CostRepository(session)

        articles_count = art_repo.count_articles()
        clusters_count = art_repo.count_story_clusters()
        jobs = render_repo.get_recent_jobs(limit=500)
        jobs_count = len(jobs)
        completed_jobs = len([j for j in jobs if j.status == "completed"])
        assets = asset_repo.list_assets(limit=500)
        assets_count = len(assets)
        total_spend = cost_repo.get_total_spend()

        return {
            "articles_count": articles_count,
            "clusters_count": clusters_count,
            "jobs_count": jobs_count,
            "completed_jobs_count": completed_jobs,
            "assets_count": assets_count,
            "total_spend_usd": round(total_spend, 4),
        }


@app.get("/api/costs")
def get_pipeline_costs() -> dict[str, Any]:
    """Retrieve spend analytics grouped by stage and per-video job."""
    with get_session() as session:
        cost_repo = CostRepository(session)
        total_spend = cost_repo.get_total_spend()
        spend_by_stage = cost_repo.get_spend_by_stage()
        per_video_costs = cost_repo.get_per_video_costs(limit=20)

        return {
            "total_spend_usd": round(total_spend, 4),
            "spend_by_stage": spend_by_stage,
            "per_video_costs": per_video_costs,
        }


@app.get("/api/clusters/trending")
def get_trending_clusters(
    limit: int = Query(10, ge=1, le=50),
    hours_back: int = Query(72, ge=1, le=720),
) -> list[dict[str, Any]]:
    """Retrieve velocity and priority ranked trending story clusters."""
    with get_session() as session:
        art_repo = ArticleRepository(session)
        trending = art_repo.get_trending_clusters(limit=limit, hours_back=hours_back)
        return [
            {
                "id": c.id,
                "cluster_hash": c.cluster_hash,
                "title": c.title,
                "summary": c.summary,
                "article_count": c.article_count,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "score": round(score, 3),
            }
            for c, score in trending
        ]


@app.get("/api/clusters/{cluster_id}")
def get_cluster(cluster_id: int) -> dict[str, Any]:
    """Retrieve details for a single cluster including its constituent articles."""
    with get_session() as session:
        art_repo = ArticleRepository(session)
        cluster = art_repo.get_cluster_by_id(cluster_id)
        if not cluster:
            raise HTTPException(status_code=404, detail=f"Story cluster {cluster_id} not found")

        articles: list[dict[str, Any]] = []
        if cluster.article_ids:
            art_records = art_repo.get_articles_by_ids(cluster.article_ids)
            articles = [
                {
                    "id": a.id,
                    "title": a.title,
                    "link": a.link,
                    "source": a.source,
                    "summary": a.summary,
                    "published_at": a.published_at.isoformat() if a.published_at else None,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in art_records
            ]

        return {
            "id": cluster.id,
            "cluster_hash": cluster.cluster_hash,
            "title": cluster.title,
            "summary": cluster.summary,
            "article_count": cluster.article_count,
            "article_ids": cluster.article_ids or [],
            "articles": articles,
            "status": cluster.status,
            "created_at": cluster.created_at.isoformat() if cluster.created_at else None,
        }


@app.get("/api/clusters/{cluster_id}/articles")
def get_cluster_articles(cluster_id: int) -> list[dict[str, Any]]:
    """Retrieve all articles belonging to a specific story cluster."""
    with get_session() as session:
        art_repo = ArticleRepository(session)
        cluster = art_repo.get_cluster_by_id(cluster_id)
        if not cluster:
            raise HTTPException(status_code=404, detail=f"Story cluster {cluster_id} not found")

        if not cluster.article_ids:
            return []

        art_records = art_repo.get_articles_by_ids(cluster.article_ids)
        return [
            {
                "id": a.id,
                "title": a.title,
                "link": a.link,
                "source": a.source,
                "summary": a.summary,
                "published_at": a.published_at.isoformat() if a.published_at else None,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in art_records
        ]


@app.get("/api/scripts/{script_id}")
def get_script(script_id: int) -> dict[str, Any]:
    """Retrieve details for a single script record."""
    with get_session() as session:
        repo = ScriptRepository(session)
        script = repo.get_script_by_id(script_id)
        if not script:
            raise HTTPException(status_code=404, detail=f"Script {script_id} not found")
        return {
            "id": script.id,
            "cluster_id": script.cluster_id,
            "title": script.title,
            "aspect_ratio": script.aspect_ratio,
            "beats": script.beats,
            "full_narration": script.full_narration,
            "word_count": len(script.full_narration.split()),
            "created_at": script.created_at.isoformat() if script.created_at else None,
        }


@app.put("/api/scripts/{script_id}")
def update_script(script_id: int, req: ScriptUpdateRequest) -> dict[str, Any]:
    """Update narration dialogue and beat sheet for a script before rendering."""
    with get_session() as session:
        repo = ScriptRepository(session)
        script = repo.get_script_by_id(script_id)
        if not script:
            raise HTTPException(status_code=404, detail=f"Script {script_id} not found")

        if req.title is not None:
            script.title = req.title
        if req.full_narration is not None:
            script.full_narration = req.full_narration
        if req.beats is not None:
            script.beats = req.beats

        session.flush()

        action_repo = ActionLogRepository(session)
        action_repo.record_action(
            stage="script",
            action="update_script",
            actor="web",
            status="success",
            message=f"Updated script #{script_id}",
            details={"script_id": script_id},
        )

        return {
            "status": "success",
            "script_id": script.id,
            "title": script.title,
            "word_count": len(script.full_narration.split()),
        }


@app.get("/api/scripts/{script_id}/audit", response_model=ScriptAuditReport)
def audit_script(script_id: int) -> ScriptAuditReport:
    """Audit script retention, hook strength, pacing, and viral potential."""
    with get_session() as session:
        repo = ScriptRepository(session)
        script = repo.get_script_by_id(script_id)
        if not script:
            raise HTTPException(status_code=404, detail=f"Script {script_id} not found")

        auditor = ScriptAuditorService()
        return auditor.audit_script(
            title=script.title,
            full_narration=script.full_narration,
            beats=script.beats if isinstance(script.beats, list) else None,
        )


@app.get("/api/jobs")
def get_jobs(limit: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
    """List render jobs and their status."""
    with get_session() as session:
        repo = RenderRepository(session)
        all_jobs = repo.get_recent_jobs(limit=limit)

        results = []
        for j in all_jobs:
            results.append(
                {
                    "id": j.id,
                    "script_id": j.script_id,
                    "aspect_ratio": j.aspect_ratio,
                    "status": j.status,
                    "duration_seconds": j.duration_seconds,
                    "audio_path": j.audio_path,
                    "captions_path": j.captions_path,
                    "output_video_path": j.output_video_path,
                    "created_at": j.created_at.isoformat() if j.created_at else None,
                    "completed_at": j.completed_at.isoformat() if j.completed_at else None,
                }
            )
        return results


@app.get("/api/jobs/{job_id}/media")
def get_job_media(job_id: int) -> list[dict[str, Any]]:
    """Retrieve indexed sentence-level visual placements for a render job."""
    storage = get_storage_service()
    with get_session() as session:
        cost_repo = CostRepository(session)
        asset_repo = AssetRepository(session)
        media_svc = MediaService(
            storage_service=storage,
            cost_repo=cost_repo,
            asset_repo=asset_repo,
        )
        placements = media_svc.get_job_placements(job_id)
        return [p.model_dump() for p in placements]


@app.put("/api/jobs/{job_id}/media/{sentence_index}")
def update_job_media_placement(
    job_id: int,
    sentence_index: int,
    req: MediaPlacementUpdateRequest,
) -> dict[str, Any]:
    """Replace visual media for a specific sentence index by search query, local file, or URL."""
    storage = get_storage_service()
    with get_session() as session:
        render_repo = RenderRepository(session)
        cost_repo = CostRepository(session)
        asset_repo = AssetRepository(session)
        action_repo = ActionLogRepository(session)

        job = render_repo.get_job_by_id(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Render job {job_id} not found")

        media_svc = MediaService(
            storage_service=storage,
            cost_repo=cost_repo,
            asset_repo=asset_repo,
        )

        if not req.query and not req.file_path and not req.url:
            raise HTTPException(
                status_code=400,
                detail="Must provide either query, file_path, or url to update placement",
            )

        with action_repo.track_operation(
            stage="media",
            action="edit_media_placement",
            actor="web",
            job_id=job.id,
            details={"sentence_index": sentence_index},
        ):
            if req.query:
                prov = req.provider or "pexels"
                updated = media_svc.search_and_replace_placement(
                    job_id=job.id,
                    sentence_index=sentence_index,
                    query=req.query,
                    provider=prov,
                    media_type="video",
                    aspect_ratio=job.aspect_ratio or "9:16",
                )
            elif req.file_path:
                updated = media_svc.update_placement_media(
                    job_id=job.id,
                    sentence_index=sentence_index,
                    new_media_path_or_url=req.file_path,
                    provider="custom",
                )
            else:
                updated = media_svc.update_placement_media(
                    job_id=job.id,
                    sentence_index=sentence_index,
                    new_media_path_or_url=req.url or "",
                    provider="custom",
                )

        return {
            "status": "success",
            "job_id": job.id,
            "placement": updated.model_dump(),
        }


@app.post("/api/jobs/{job_id}/re-render")
def trigger_job_re_render(job_id: int, req: JobReRenderRequest) -> dict[str, Any]:
    """Re-render finalized video using updated media placements."""
    storage = get_storage_service()
    with get_session() as session:
        render_repo = RenderRepository(session)
        script_repo = ScriptRepository(session)
        cost_repo = CostRepository(session)
        action_repo = ActionLogRepository(session)

        job = render_repo.get_job_by_id(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Render job {job_id} not found")

        script = script_repo.get_script_by_id(job.script_id)
        if not script:
            raise HTTPException(status_code=404, detail=f"Script {job.script_id} not found")

        captions: list[WordCaption] = []
        if job.captions_path:
            local_cap_path = storage.get_local_path(job.captions_path)
            if local_cap_path.exists():
                cap_data = json.loads(local_cap_path.read_text(encoding="utf-8"))
                captions = [WordCaption(**item) for item in cap_data]

        render_svc = RenderService(render_repo, cost_repo, storage)
        with action_repo.track_operation(
            stage="render",
            action="re_render_video",
            actor="web",
            job_id=job.id,
            details={"dry_run": req.dry_run, "show_indices": req.show_material_indices},
        ):
            out_path = render_svc.re_render_job(
                job_id=job.id,
                dry_run=req.dry_run,
                show_material_indices=req.show_material_indices,
                script=script,
                captions=captions,
            )

        return {
            "status": "success",
            "job_id": job.id,
            "output_video_path": str(out_path.resolve()),
        }


@app.get("/api/jobs/{job_id}/video")
def stream_job_video(job_id: int) -> FileResponse:
    """Stream rendered MP4 video for in-browser playback."""
    storage = get_storage_service()
    with get_session() as session:
        repo = RenderRepository(session)
        job = repo.get_job_by_id(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Render job {job_id} not found")
        if not job.output_video_path:
            raise HTTPException(
                status_code=404, detail=f"Video output path for job {job_id} is missing"
            )

        local_path = storage.get_local_path(job.output_video_path)
        if not local_path.exists():
            raise HTTPException(
                status_code=404, detail=f"Video file for job {job_id} not found on disk"
            )

        return FileResponse(
            path=str(local_path),
            media_type="video/mp4",
            filename=local_path.name,
        )


@app.get("/api/jobs/{job_id}/download")
def download_job_video(job_id: int) -> FileResponse:
    """Download the finalized rendered video file with attachment disposition."""
    storage = get_storage_service()
    with get_session() as session:
        repo = RenderRepository(session)
        job = repo.get_job_by_id(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Render job {job_id} not found")
        if not job.output_video_path:
            raise HTTPException(
                status_code=404, detail=f"Video output path for job {job_id} is missing"
            )

        local_path = storage.get_local_path(job.output_video_path)
        if not local_path.exists():
            raise HTTPException(
                status_code=404, detail=f"Video file for job {job_id} not found on disk"
            )

        return FileResponse(
            path=str(local_path),
            media_type="video/mp4",
            filename=local_path.name,
            headers={"Content-Disposition": f'attachment; filename="{local_path.name}"'},
        )


@app.get("/api/jobs/{job_id}/subtitles")
def get_job_subtitles(
    job_id: int,
    format: Literal["srt", "vtt"] = Query("srt"),
    download: bool = Query(False),
) -> Any:
    """Generate or retrieve SRT/WebVTT subtitles for a rendered job."""
    storage = get_storage_service()
    with get_session() as session:
        repo = RenderRepository(session)
        job = repo.get_job_by_id(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Render job {job_id} not found")
        if not job.captions_path:
            raise HTTPException(
                status_code=404, detail=f"Captions path for job {job_id} is missing"
            )

        local_cap_path = storage.get_local_path(job.captions_path)
        if not local_cap_path.exists():
            raise HTTPException(
                status_code=404, detail=f"Captions file for job {job_id} not found on disk"
            )

        raw_captions = json.loads(local_cap_path.read_text(encoding="utf-8"))
        captions = [WordCaption(**c) for c in raw_captions]

        subtitle_svc = SubtitleService()
        if format == "vtt":
            content = subtitle_svc.generate_vtt(captions)
            media_type = "text/vtt"
            filename = f"job_{job_id}.vtt"
        else:
            content = subtitle_svc.generate_srt(captions)
            media_type = "text/plain"
            filename = f"job_{job_id}.srt"

        if download:
            headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
            return Response(content=content, media_type=media_type, headers=headers)

        return {"job_id": job_id, "format": format, "content": content}


@app.get("/api/jobs/{job_id}/youtube-metadata", response_model=YouTubeMetadata)
def get_job_youtube_metadata(job_id: int) -> YouTubeMetadata:
    """Generate YouTube package including title, description, timestamped chapters, and tags."""
    storage = get_storage_service()
    with get_session() as session:
        render_repo = RenderRepository(session)
        script_repo = ScriptRepository(session)
        job = render_repo.get_job_by_id(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Render job {job_id} not found")

        script = script_repo.get_script_by_id(job.script_id)
        if not script:
            raise HTTPException(status_code=404, detail=f"Script for job {job_id} not found")

        captions: list[WordCaption] = []
        if job.captions_path:
            local_cap_path = storage.get_local_path(job.captions_path)
            if local_cap_path.exists():
                raw = json.loads(local_cap_path.read_text(encoding="utf-8"))
                captions = [WordCaption(**c) for c in raw]

        metadata_svc = YouTubeMetadataService()
        return metadata_svc.generate_metadata(
            title=script.title,
            full_narration=script.full_narration,
            beats=script.beats if isinstance(script.beats, list) else None,
            captions=captions,
            duration_seconds=job.duration_seconds or 0.0,
        )


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    """Retrieve current branding, watermark, and timing configuration."""
    return {
        "watermark_text": settings.watermark_text,
        "watermark_image_path": settings.watermark_image_path,
        "watermark_position": settings.watermark_position,
        "watermark_opacity": settings.watermark_opacity,
        "intro_delay_seconds": settings.intro_delay_seconds,
        "outro_duration_seconds": settings.outro_duration_seconds,
        "cluster_review_timeout_seconds": settings.cluster_review_timeout_seconds,
        "default_media_type_ratio": settings.default_media_type_ratio,
        "channel_badge_text": settings.channel_badge_text,
        "caption_style": settings.caption_style,
        "caption_level": settings.caption_level,
        "caption_font_size": settings.caption_font_size,
        "caption_uppercase": settings.caption_uppercase,
        "subscribe_title": settings.subscribe_title,
        "subscribe_subtitle": settings.subscribe_subtitle,
        "subscribe_button_text": settings.subscribe_button_text,
        "subscribe_duration_seconds": settings.subscribe_duration_seconds,
        "subscribe_style": settings.subscribe_style,
        "subscribe_enabled": settings.subscribe_enabled,
        "horizontal_watermark_position": settings.horizontal_watermark_position,
        "horizontal_caption_level": settings.horizontal_caption_level,
        "horizontal_channel_badge_text": settings.horizontal_channel_badge_text,
        "horizontal_lower_third_title": settings.horizontal_lower_third_title,
        "pexels_configured": bool(settings.pexels_api_key),
        "giphy_configured": bool(settings.giphy_api_key),
    }


@app.post("/api/settings")
def update_settings(req: SettingsUpdateRequest) -> dict[str, Any]:
    """Update watermark and timing configuration."""
    if req.watermark_text is not None:
        settings.watermark_text = req.watermark_text
    if req.watermark_image_path is not None:
        settings.watermark_image_path = req.watermark_image_path
    if req.watermark_position is not None:
        settings.watermark_position = req.watermark_position
    if req.watermark_opacity is not None:
        settings.watermark_opacity = req.watermark_opacity
    if req.intro_delay_seconds is not None:
        settings.intro_delay_seconds = req.intro_delay_seconds
    if req.outro_duration_seconds is not None:
        settings.outro_duration_seconds = req.outro_duration_seconds
    if req.cluster_review_timeout_seconds is not None:
        settings.cluster_review_timeout_seconds = req.cluster_review_timeout_seconds
    if req.channel_badge_text is not None:
        settings.channel_badge_text = req.channel_badge_text
    if req.caption_style is not None:
        settings.caption_style = req.caption_style
    if req.caption_level is not None:
        settings.caption_level = req.caption_level
    if req.caption_font_size is not None:
        settings.caption_font_size = req.caption_font_size
    if req.caption_uppercase is not None:
        settings.caption_uppercase = req.caption_uppercase
    if req.subscribe_title is not None:
        settings.subscribe_title = req.subscribe_title
    if req.subscribe_subtitle is not None:
        settings.subscribe_subtitle = req.subscribe_subtitle
    if req.subscribe_button_text is not None:
        settings.subscribe_button_text = req.subscribe_button_text
    if req.subscribe_duration_seconds is not None:
        settings.subscribe_duration_seconds = req.subscribe_duration_seconds
    if req.subscribe_style is not None:
        settings.subscribe_style = req.subscribe_style
    if req.subscribe_enabled is not None:
        settings.subscribe_enabled = req.subscribe_enabled
    if req.horizontal_watermark_position is not None:
        settings.horizontal_watermark_position = req.horizontal_watermark_position
    if req.horizontal_caption_level is not None:
        settings.horizontal_caption_level = req.horizontal_caption_level
    if req.horizontal_channel_badge_text is not None:
        settings.horizontal_channel_badge_text = req.horizontal_channel_badge_text
    if req.horizontal_lower_third_title is not None:
        settings.horizontal_lower_third_title = req.horizontal_lower_third_title

    with get_session() as session:
        action_repo = ActionLogRepository(session)
        action_repo.record_action(
            stage="pipeline",
            action="update_settings",
            actor="web",
            status="success",
            message="Updated watermark, captions, and branding configuration",
            details={
                "watermark_text": settings.watermark_text,
                "watermark_position": settings.watermark_position,
                "caption_style": settings.caption_style,
                "caption_level": settings.caption_level,
                "subscribe_title": settings.subscribe_title,
                "horizontal_caption_level": settings.horizontal_caption_level,
            },
        )

    return {"status": "success", "settings": get_settings()}


@app.get("/api/config/active")
def get_active_config() -> dict[str, Any]:
    """Retrieve active configuration file path and current parameters."""
    yaml_path = find_yaml_config_path()
    return {
        "status": "success",
        "config_source": settings.config_source_label,
        "config_path": str(yaml_path.resolve()) if yaml_path else None,
        "is_yaml": yaml_path is not None,
        "settings": get_settings(),
    }


@app.get("/api/config/yaml")
def get_config_yaml(path: str | None = Query(None)) -> dict[str, Any]:
    """Read YAML configuration content from a specified file or active config."""
    target_path = Path(path) if path else (find_yaml_config_path() or Path("config_example.yaml"))
    if not target_path.is_absolute():
        target_path = Path.cwd() / target_path

    if not target_path.exists():
        example_path = Path.cwd() / "config_example.yaml"
        if example_path.exists():
            return {
                "status": "success",
                "path": str(target_path),
                "exists": False,
                "yaml_content": example_path.read_text(encoding="utf-8"),
                "is_example": True,
            }
        raise HTTPException(status_code=404, detail=f"Configuration file {target_path} not found")

    content = target_path.read_text(encoding="utf-8")
    return {
        "status": "success",
        "path": str(target_path),
        "exists": True,
        "yaml_content": content,
        "is_example": False,
    }


@app.post("/api/config/load")
def load_config_file(req: ConfigLoadRequest) -> dict[str, Any]:
    """Switch active configuration to a specified YAML file (plug and play)."""
    target = Path(req.config_path)
    if not target.is_absolute():
        target = Path.cwd() / target

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"Config file {target} does not exist")

    try:
        raw_text = target.read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw_text)
        if not isinstance(parsed, dict):
            raise ValueError("Root element must be a YAML mapping/dictionary")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid YAML syntax: {exc}") from exc

    reload_settings(target)

    with get_session() as session:
        action_repo = ActionLogRepository(session)
        action_repo.record_action(
            stage="pipeline",
            action="switch_config_file",
            actor="web",
            status="success",
            message=f"Switched active configuration to {target.name}",
            details={"config_path": str(target)},
        )

    return {
        "status": "success",
        "message": f"Successfully switched configuration to {target}",
        "config_source": settings.config_source_label,
        "settings": get_settings(),
    }


@app.post("/api/config/save")
def save_config_yaml(req: ConfigSaveRequest) -> dict[str, Any]:
    """Save YAML content to file and hot-reload runtime pipeline settings."""
    try:
        parsed = yaml.safe_load(req.yaml_content)
        if not isinstance(parsed, dict):
            raise ValueError("Root element must be a YAML mapping/dictionary")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid YAML syntax: {exc}") from exc

    target = Path(req.config_path)
    if not target.is_absolute():
        target = Path.cwd() / target

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(req.yaml_content, encoding="utf-8")

    reload_settings(target)

    with get_session() as session:
        action_repo = ActionLogRepository(session)
        action_repo.record_action(
            stage="pipeline",
            action="save_config_yaml",
            actor="web",
            status="success",
            message=f"Saved and applied configuration to {target.name}",
            details={"config_path": str(target)},
        )

    return {
        "status": "success",
        "message": f"Saved and applied configuration to {target}",
        "config_source": settings.config_source_label,
        "settings": get_settings(),
    }


@app.get("/api/health", response_model=HealthStatus)
def get_system_health() -> HealthStatus:
    """Run comprehensive system diagnostics on database, storage, tools, and providers."""
    health_svc = HealthService()
    return health_svc.run_health_check()


@app.post("/api/system/prune", response_model=PruneResult)
def prune_system_cache(
    retention_hours: int | None = Query(None, ge=1, le=8760),
) -> PruneResult:
    """Prune unindexed temporary media files older than retention hours."""
    with get_session() as session:
        asset_repo = AssetRepository(session)
        pruning_svc = CachePruningService(asset_repo=asset_repo)
        return pruning_svc.prune_cache(retention_hours=retention_hours)


# ---------------------------------------------------------------------------
# Modern Web UI (Served at /)
# ---------------------------------------------------------------------------

DASHBOARD_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "dashboard.html"


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """Serve the single-page interactive pipeline operations dashboard."""
    if DASHBOARD_TEMPLATE_PATH.exists():
        content = DASHBOARD_TEMPLATE_PATH.read_text(encoding="utf-8")
    else:
        content = "<!DOCTYPE html><html><body><h1>AI Video Studio</h1></body></html>"
    return HTMLResponse(content=content)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.web:app", host="0.0.0.0", port=8000, reload=True)
