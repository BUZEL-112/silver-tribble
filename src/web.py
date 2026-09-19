"""FastAPI web server and interactive dashboard for AI Video Production Platform."""

import json
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.core.config import find_yaml_config_path, reload_settings, settings
from src.core.database import get_session, init_db
from src.flows.video_pipeline_flow import run_video_pipeline
from src.models.schemas import SentenceMediaPlacement, WordCaption
from src.repositories.action_log_repository import ActionLogRepository
from src.repositories.article_repository import ArticleRepository
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
from src.services.tts_service import TtsService

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


class PipelineRunRequest(BaseModel):
    cluster_id: int | None = None
    aspect_ratio: str = "9:16"
    dry_run: bool = False


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
        return {
            "status": "success",
            "articles_embedded": embedded_count,
            "clusters_created": len(clusters),
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

            media_svc = MediaService(storage_service=storage, cost_repo=cost_repo)

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
                media_svc = MediaService(storage_service=storage, cost_repo=cost_repo)
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
            aspect_ratio=req.aspect_ratio,
            dry_run=req.dry_run,
        )
        return {"status": "success", **result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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
def get_clusters(limit: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
    """List recent story clusters."""
    with get_session() as session:
        art_repo = ArticleRepository(session)
        clusters = art_repo.get_recent_clusters(limit=limit)
        return [
            {
                "id": c.id,
                "title": c.title,
                "summary": c.summary,
                "article_count": c.article_count,
                "status": c.status,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in clusters
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
        "default_media_type_ratio": settings.default_media_type_ratio,
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

    with get_session() as session:
        action_repo = ActionLogRepository(session)
        action_repo.record_action(
            stage="pipeline",
            action="update_settings",
            actor="web",
            status="success",
            message="Updated watermark and timing configuration",
            details={
                "watermark_text": settings.watermark_text,
                "watermark_position": settings.watermark_position,
                "intro_delay_seconds": settings.intro_delay_seconds,
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
