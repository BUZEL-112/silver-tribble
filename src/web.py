"""FastAPI web server and interactive dashboard for AI Video Production Platform."""

import hmac
import json
import math
import threading
import time
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.core.config import find_yaml_config_path, reload_settings, settings
from src.core.database import get_session, init_db
from src.core.security import (
    generate_session_token,
    invalidate_session_token,
    is_session_token_valid,
    mask_dict_secrets,
    verify_auth_token,
)
from src.flows.video_pipeline_flow import run_roundup_pipeline, run_video_pipeline
from src.models.schemas import (
    ClusterTriggerRequest,
    CustomProviderConfig,
    HealthStatus,
    ModelDefinition,
    ModelDefinitionResponse,
    ModelTestRequest,
    ModelTestResponse,
    ProviderCredentialsRequest,
    ProviderInfo,
    ProviderPriorityRequest,
    ProviderTestRequest,
    ProviderTestResponse,
    ProviderToggleRequest,
    PruneResult,
    RoleFallbacksUpdateRequest,
    RoleMappingsConfig,
    ScriptAuditReport,
    SentenceMediaPlacement,
    SystemConfigResponse,
    SystemConfigUpdateRequest,
    VisualAssetResponse,
    VisualConfigSchema,
    VisualConfigUpdateRequest,
    VisualPresetInfo,
    WordCaption,
    YouTubeMetadata,
    YouTubeUploadRequest,
    YouTubeUploadResult,
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
from src.services.cost_guardrail_service import CostGuardrailService
from src.services.demo_service import DemoService
from src.services.health_service import HealthService
from src.services.job_queue_service import JobQueueService
from src.services.media_service import MediaService
from src.services.provider_service import ProviderService
from src.services.render_service import RenderService
from src.services.rss_service import RssService
from src.services.script_auditor_service import ScriptAuditorService
from src.services.script_service import ScriptService
from src.services.storage_service import get_storage_service
from src.services.subtitle_service import SubtitleService
from src.services.system_config_service import SystemConfigService
from src.services.tts_service import TtsService
from src.services.visual_config_service import VisualConfigService
from src.services.youtube_metadata_service import YouTubeMetadataService
from src.services.youtube_upload_service import YouTubeUploadService

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


class InMemoryRateLimiter:
    """Thread-safe in-memory sliding window rate limiter."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, list[float]] = {}

    def is_allowed(
        self,
        key: str,
        limit: int,
        window_seconds: float,
    ) -> tuple[bool, dict[str, Any]]:
        """Evaluate if request for key is permitted under limit within window_seconds.

        Returns:
            Tuple of (allowed, metadata) containing limit, window, retry_after, and remaining count.
        """
        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            timestamps = self._records.get(key, [])
            timestamps = [ts for ts in timestamps if ts > cutoff]
            if len(timestamps) >= limit:
                retry_after = int(math.ceil(timestamps[0] + window_seconds - now))
                self._records[key] = timestamps
                return False, {
                    "limit": limit,
                    "window_seconds": window_seconds,
                    "retry_after": max(1, retry_after),
                    "remaining": 0,
                }
            timestamps.append(now)
            self._records[key] = timestamps
            remaining = max(0, limit - len(timestamps))
            return True, {
                "limit": limit,
                "window_seconds": window_seconds,
                "retry_after": 0,
                "remaining": remaining,
            }

    def reset(self) -> None:
        """Clear all rate limit tracking records."""
        with self._lock:
            self._records.clear()


class PipelineMetrics:
    """Thread-safe Prometheus metrics collector for pipeline telemetry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.runs_success: int = 0
        self.runs_failure: int = 0
        self.stage_durations: dict[str, float] = {
            "ingestion": 0.0,
            "clustering": 0.0,
            "script": 0.0,
            "tts": 0.0,
            "caption": 0.0,
            "render": 0.0,
        }
        self.active_render_jobs: int = 0

    def record_run(self, success: bool) -> None:
        """Increment success or failure count for pipeline runs."""
        with self._lock:
            if success:
                self.runs_success += 1
            else:
                self.runs_failure += 1

    def record_stage_duration(self, stage: str, duration: float) -> None:
        """Record latest execution duration for a specific pipeline stage."""
        with self._lock:
            self.stage_durations[stage] = max(0.0, float(duration))

    def set_active_render_jobs(self, count: int) -> None:
        """Set gauge count for active video render jobs."""
        with self._lock:
            self.active_render_jobs = max(0, count)

    def reset(self) -> None:
        """Reset counters and gauge metrics to initial zero values."""
        with self._lock:
            self.runs_success = 0
            self.runs_failure = 0
            for stage in self.stage_durations:
                self.stage_durations[stage] = 0.0
            self.active_render_jobs = 0

    def generate_prometheus_text(
        self,
        total_spend: float,
        daily_budget: float,
        active_render_jobs: int | None = None,
    ) -> str:
        """Format tracked telemetry into Prometheus text format."""
        with self._lock:
            active_jobs = (
                self.active_render_jobs if active_render_jobs is None else active_render_jobs
            )
            lines = [
                "# HELP ai_video_pipeline_runs_total Total number of pipeline execution runs.",
                "# TYPE ai_video_pipeline_runs_total counter",
                f'ai_video_pipeline_runs_total{{status="success"}} {self.runs_success}',
                f'ai_video_pipeline_runs_total{{status="failure"}} {self.runs_failure}',
                "",
                "# HELP ai_video_pipeline_duration_seconds Stage duration in seconds.",
                "# TYPE ai_video_pipeline_duration_seconds gauge",
            ]
            for stage in ["ingestion", "clustering", "script", "tts", "caption", "render"]:
                duration = self.stage_durations.get(stage, 0.0)
                m_key = f'ai_video_pipeline_duration_seconds{{stage="{stage}"}}'
                lines.append(f"{m_key} {duration:.4f}")

            lines.extend(
                [
                    "",
                    "# HELP ai_video_total_spend_usd Cumulative AI API expenditure in USD.",
                    "# TYPE ai_video_total_spend_usd gauge",
                    f"ai_video_total_spend_usd {total_spend:.4f}",
                    "",
                    "# HELP ai_video_daily_budget_usd Configured daily budget cap in USD.",
                    "# TYPE ai_video_daily_budget_usd gauge",
                    f"ai_video_daily_budget_usd {daily_budget:.4f}",
                    "",
                    "# HELP ai_video_active_render_jobs Current number of active render jobs.",
                    "# TYPE ai_video_active_render_jobs gauge",
                    f"ai_video_active_render_jobs {active_jobs}",
                    "",
                ]
            )
            return "\n".join(lines)


# Operational singletons for rate limiting, budget guardrails, concurrency, and metrics
cost_guardrail = CostGuardrailService()
render_lock = threading.Lock()
rate_limiter = InMemoryRateLimiter()
pipeline_metrics = PipelineMetrics()


def get_client_ip(request: Request) -> str:
    """Extract client IP address from proxy headers or connection info."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


def enforce_heavy_rate_limit(request: Request) -> None:
    """Validate client request against heavy pipeline execution rate limit."""
    if not settings.rate_limit_enabled:
        return

    client_ip = get_client_ip(request)
    key = f"heavy:{client_ip}"
    allowed, meta = rate_limiter.is_allowed(
        key=key,
        limit=settings.rate_limit_heavy_runs_per_hour,
        window_seconds=3600.0,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit exceeded for heavy execution endpoints: "
                f"{meta['limit']} runs per hour allowed. "
                f"Retry after {meta['retry_after']} seconds."
            ),
            headers={"Retry-After": str(meta["retry_after"])},
        )


def enforce_cost_guardrail() -> None:
    """Validate current spending against budget caps before running heavy operations."""
    proceed_result = cost_guardrail.can_proceed()
    if isinstance(proceed_result, tuple):
        can_proceed, message = proceed_result
    else:
        can_proceed, message = bool(proceed_result), "Cost guardrail budget exceeded"

    if not can_proceed:
        raise HTTPException(
            status_code=429,
            detail=message or "Cost guardrail budget exceeded",
        )


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next: Any) -> Response:
    """Middleware enforcing general rate limits on read requests."""
    if settings.rate_limit_enabled and request.method in ("GET", "HEAD"):
        path = request.url.path
        if path != "/metrics" and not path.startswith("/static"):
            client_ip = get_client_ip(request)
            key = f"read:{client_ip}"
            allowed, meta = rate_limiter.is_allowed(
                key=key,
                limit=settings.rate_limit_read_req_per_minute,
                window_seconds=60.0,
            )
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": (
                            f"Rate limit exceeded for read endpoints: "
                            f"{meta['limit']} requests per minute allowed. "
                            f"Retry after {meta['retry_after']} seconds."
                        )
                    },
                    headers={"Retry-After": str(meta["retry_after"])},
                )
    return await call_next(request)


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


class LoginRequest(BaseModel):
    password: str | None = None
    token: str | None = None


class RenderCreateRequest(BaseModel):
    job_id: int
    dry_run: bool = False
    async_mode: bool = False


class MediaPlacementUpdateRequest(BaseModel):
    query: str | None = None
    file_path: str | None = None
    url: str | None = None
    provider: (
        Literal[
            "pexels",
            "pixabay",
            "giphy",
            "google_search",
            "brand_card",
            "flux_generation",
            "ai_generated",
            "asset_library",
            "fallback",
            "custom",
        ]
        | None
    ) = None


class JobReRenderRequest(BaseModel):
    dry_run: bool = False
    show_material_indices: bool = False


class VideoResolutionConvertRequest(BaseModel):
    resolution: Literal["360p", "480p", "720p", "1080p"] = Field(
        default="720p",
        description="Target video resolution spec (360p, 480p, 720p, 1080p)",
    )


class BeatConfigUpdateRequest(BaseModel):
    content: str = Field(
        ...,
        min_length=10,
        description="YAML content for beat generator prompt configuration",
    )
    filename: str | None = Field(
        default=None,
        description="Optional prompt filename in prompts directory",
    )


class PipelineRunRequest(BaseModel):
    cluster_id: int | None = None
    cluster_ids: list[int] | None = None
    aspect_ratio: str = "9:16"
    dry_run: bool = False
    async_mode: bool = False


class DemoPipelineRequest(BaseModel):
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
    caption_style: Literal["hormozi", "minimal", "karaoke", "news_ticker", "cinematic"] | None = (
        None
    )
    caption_level: float | None = Field(default=None, ge=5.0, le=90.0)
    caption_font_size: int | None = Field(default=None, ge=20, le=96)
    caption_uppercase: bool | None = None
    subscribe_title: str | None = None
    subscribe_subtitle: str | None = None
    subscribe_button_text: str | None = None
    subscribe_duration_seconds: float | None = Field(default=None, ge=0.0)
    subscribe_style: Literal["card", "lower_third", "minimal_badge"] | None = None
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


@app.get("/api/auth/status")
def get_auth_status(request: Request) -> dict[str, Any]:
    """Check whether authentication is enforced and whether client is authenticated."""
    configured = bool(settings.api_auth_token or settings.admin_password)
    cookie_token = request.cookies.get("ai_video_session")
    is_authenticated = not configured or is_session_token_valid(cookie_token)
    return {
        "auth_required": configured,
        "authenticated": is_authenticated,
    }


@app.post("/api/auth/login")
def login(req: LoginRequest, response: Response) -> dict[str, Any]:
    """Authenticate dashboard session with admin password or bearer token."""
    configured_token = settings.api_auth_token
    configured_password = settings.admin_password

    if not configured_token and not configured_password:
        return {"status": "success", "message": "Authentication not configured"}

    valid = False
    if req.token and configured_token and hmac.compare_digest(req.token, configured_token):
        valid = True
    elif (
        req.password
        and configured_password
        and hmac.compare_digest(req.password, configured_password)
    ):
        valid = True
    elif req.password and configured_token and hmac.compare_digest(req.password, configured_token):
        valid = True

    if not valid:
        raise HTTPException(status_code=401, detail="Invalid password or token")

    session_token = generate_session_token()
    response.set_cookie(
        key="ai_video_session",
        value=session_token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=86400 * 7,
    )
    return {"status": "success", "token": session_token}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response) -> dict[str, Any]:
    """Invalidate session token and clear authentication cookie."""
    cookie_token = request.cookies.get("ai_video_session")
    if cookie_token:
        invalidate_session_token(cookie_token)
    response.delete_cookie("ai_video_session")
    return {"status": "success"}


@app.get("/api/budget")
def get_budget_status() -> dict[str, Any]:
    """Query current spend against configured daily and monthly cost caps."""
    with get_session() as session:
        cost_repo = CostRepository(session)
        total_spend = cost_repo.get_total_spend()

    daily_cap = settings.cost_daily_budget_usd
    monthly_cap = settings.cost_monthly_budget_usd
    daily_exceeded = bool(daily_cap and total_spend >= daily_cap)
    monthly_exceeded = bool(monthly_cap and total_spend >= monthly_cap)

    return {
        "total_spend_usd": round(total_spend, 4),
        "daily_budget_usd": daily_cap,
        "monthly_budget_usd": monthly_cap,
        "daily_budget_exceeded": daily_exceeded,
        "monthly_budget_exceeded": monthly_exceeded,
    }


@app.post("/api/pipeline/ingest")
def trigger_ingest() -> dict[str, Any]:
    """Trigger RSS feed ingestion and save new articles."""
    start_time = time.time()
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

        pipeline_metrics.record_stage_duration("ingestion", time.time() - start_time)
        return {
            "status": "success",
            "articles_fetched": len(items),
            "new_articles_saved": len(saved),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/pipeline/cluster")
def trigger_cluster(
    request: Request,
    req: ClusterTriggerRequest | None = None,
    threshold: float | None = Query(None),
    model: str | None = Query(None),
) -> dict[str, Any]:
    """Trigger embeddings generation and story clustering."""
    enforce_heavy_rate_limit(request)
    enforce_cost_guardrail()
    cluster_start = time.time()
    try:
        eff_threshold = 0.82
        if req and req.threshold is not None:
            eff_threshold = req.threshold
        elif threshold is not None:
            eff_threshold = threshold

        eff_model = req.model if req and req.model else model
        eff_article_ids = req.article_ids if req else None
        eff_hours_back = req.hours_back if req else None
        eff_run_id = req.cluster_run_id if req else None

        with get_session() as session:
            art_repo = ArticleRepository(session)
            cost_repo = CostRepository(session)
            action_repo = ActionLogRepository(session)
            service = ClusteringService(article_repo=art_repo, cost_repo=cost_repo)

            with action_repo.track_operation(
                stage="cluster",
                action="cluster_articles",
                actor="web",
                details={
                    "threshold": eff_threshold,
                    "model": eff_model,
                    "article_ids": eff_article_ids,
                    "hours_back": eff_hours_back,
                    "cluster_run_id": eff_run_id,
                },
            ):
                embedded_count = service.generate_embeddings_for_new_articles(
                    model=eff_model,
                    article_ids=eff_article_ids,
                )
                if eff_article_ids is None and eff_hours_back is None and eff_run_id is None:
                    clusters = service.cluster_recent_articles(threshold=eff_threshold)
                else:
                    clusters = service.cluster_recent_articles(
                        threshold=eff_threshold,
                        article_ids=eff_article_ids,
                        hours_back=eff_hours_back,
                        cluster_run_id=eff_run_id,
                    )

            top_id = clusters[0].id if clusters else None
            clusters_count = len(clusters)
            cluster_run_id = getattr(service, "last_run_id", None) or (
                getattr(clusters[0], "cluster_run_id", "run_default") if clusters else None
            )
            cluster_payload = [
                {
                    "id": c.id,
                    "cluster_run_id": getattr(c, "cluster_run_id", cluster_run_id or "run_default"),
                    "run_cluster_index": getattr(c, "run_cluster_index", idx + 1),
                    "title": c.title,
                    "article_count": c.article_count,
                }
                for idx, c in enumerate(clusters)
            ]

        pipeline_metrics.record_stage_duration("clustering", time.time() - cluster_start)
        return {
            "status": "success",
            "articles_embedded": embedded_count,
            "clusters_created": clusters_count,
            "clusters_count": clusters_count,
            "top_cluster_id": top_id,
            "cluster_run_id": cluster_run_id,
            "clusters": cluster_payload,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/pipeline/cluster/run")
def trigger_cluster_run(
    request: Request,
    req: ClusterTriggerRequest | None = None,
    threshold: float | None = Query(None),
    model: str | None = Query(None),
) -> dict[str, Any]:
    """Execute clustering pipeline run with rate limiting and cost validation."""
    return trigger_cluster(request=request, req=req, threshold=threshold, model=model)


@app.post("/api/pipeline/script")
def trigger_script(req: ScriptCreateRequest) -> dict[str, Any]:
    """Generate beat sheet and dialogue narration for a story cluster."""
    script_start = time.time()
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
        pipeline_metrics.record_stage_duration("script", time.time() - script_start)
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
                tts_start = time.time()
                tts = TtsService(storage, cost_repo)
                audio_path, duration = tts.synthesize_speech(script_record.full_narration, job.id)
                pipeline_metrics.record_stage_duration("tts", time.time() - tts_start)
                render_repo.update_job_audio(job.id, audio_path, duration)

                cap_start = time.time()
                captions_service = CaptionService(storage, cost_repo)
                captions_path, _captions = captions_service.generate_captions(
                    audio_path, job.id, script_record.full_narration, duration
                )
                pipeline_metrics.record_stage_duration("caption", time.time() - cap_start)
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
def trigger_render(
    request: Request,
    req: RenderCreateRequest,
    response: Response,
    _: bool = Depends(verify_auth_token),
) -> dict[str, Any]:
    """Execute Remotion video render for a job."""
    enforce_heavy_rate_limit(request)
    enforce_cost_guardrail()

    if req.async_mode:
        queue_svc = JobQueueService()
        queue_svc.submit_render_job(job_id=req.job_id, dry_run=req.dry_run)
        response.status_code = 202
        return {
            "status": "queued",
            "job_id": req.job_id,
            "message": "Render job dispatched to queue",
        }

    if not render_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="A render job is already in progress. Only one concurrent render is permitted.",
        )

    pipeline_metrics.set_active_render_jobs(1)
    render_start = time.time()
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
                cap_path, captions = caption_svc.generate_captions(
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

        pipeline_metrics.record_stage_duration("render", time.time() - render_start)
        return {
            "status": "success",
            "job_id": job_id,
            "output_video_path": rendered_video_path,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        pipeline_metrics.set_active_render_jobs(0)
        render_lock.release()


@app.post("/api/pipeline/run")
def trigger_run_all(
    request: Request,
    req: PipelineRunRequest,
    response: Response,
    _: bool = Depends(verify_auth_token),
) -> dict[str, Any]:
    """Run full pipeline end-to-end from news clustering to finished video."""
    enforce_heavy_rate_limit(request)
    enforce_cost_guardrail()

    if req.async_mode:
        queue_svc = JobQueueService()
        job_id = queue_svc.submit_pipeline_job(
            cluster_id=req.cluster_id,
            cluster_ids=req.cluster_ids,
            aspect_ratio=req.aspect_ratio,
            dry_run=req.dry_run,
        )
        response.status_code = 202
        return {
            "status": "queued",
            "job_id": job_id,
            "message": "Pipeline run dispatched to background queue",
        }

    try:
        result = run_video_pipeline(
            cluster_id=req.cluster_id,
            cluster_ids=req.cluster_ids,
            aspect_ratio=req.aspect_ratio,
            dry_run=req.dry_run,
        )
        pipeline_metrics.record_run(success=True)
        return {"status": "success", **result}
    except HTTPException:
        pipeline_metrics.record_run(success=False)
        raise
    except Exception as exc:
        pipeline_metrics.record_run(success=False)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/pipeline/demo")
def trigger_demo_get(
    aspect_ratio: str = Query("9:16", description="Aspect ratio (9:16 or 16:9)"),
    dry_run: bool = Query(False, description="Force mock render without Remotion CLI"),
) -> dict[str, Any]:
    """Execute zero-API-key local sandbox demo pipeline via GET."""
    try:
        with get_session() as session:
            service = DemoService(session=session)
            result = service.run_demo(aspect_ratio=aspect_ratio, dry_run=dry_run)
            return result.to_dict()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/pipeline/demo")
def trigger_demo_post(
    req: DemoPipelineRequest | None = None,
) -> dict[str, Any]:
    """Execute zero-API-key local sandbox demo pipeline via POST."""
    aspect_ratio = req.aspect_ratio if req else "9:16"
    dry_run = req.dry_run if req else False
    try:
        with get_session() as session:
            service = DemoService(session=session)
            result = service.run_demo(aspect_ratio=aspect_ratio, dry_run=dry_run)
            return result.to_dict()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}/progress")
def get_job_progress(job_id: int) -> dict[str, Any]:
    """Retrieve real-time execution progress, stage, and completion artifact."""
    progress = JobQueueService.get_progress(job_id)
    if not progress:
        raise HTTPException(status_code=404, detail=f"Job #{job_id} not found")
    return progress


@app.post("/api/jobs/{job_id}/publish-youtube", response_model=YouTubeUploadResult)
def publish_to_youtube(
    job_id: int,
    req: YouTubeUploadRequest,
    _: bool = Depends(verify_auth_token),
) -> YouTubeUploadResult:
    """Upload completed video to YouTube channel using configured OAuth credentials."""
    upload_svc = YouTubeUploadService()
    if not upload_svc.is_configured():
        raise HTTPException(
            status_code=400,
            detail=(
                "YouTube OAuth credentials not configured. Please supply client_id, "
                "client_secret, and refresh_token in settings."
            ),
        )
    try:
        req.job_id = job_id
        return upload_svc.upload_video_for_job(req)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/youtube/status")
def get_youtube_status() -> dict[str, Any]:
    """Check whether YouTube channel authorization is configured."""
    upload_svc = YouTubeUploadService()
    return {
        "configured": upload_svc.is_configured(),
        "client_id": upload_svc.client_id[:6] + "..." if upload_svc.client_id else None,
    }


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


@app.get("/api/articles")
def get_articles_list(
    hours_back: float | None = Query(None, ge=0.1, description="Articles from past X hours"),
    limit: int | None = Query(
        None, ge=1, description="Max articles to return (optional, defaults to all if omitted)"
    ),
    search: str | None = Query(None, description="Keyword search in title or summary"),
    source: str | None = Query(None, description="Filter by RSS source"),
) -> list[dict[str, Any]]:
    """Retrieve articles with optional recency window and keyword filtering."""
    with get_session() as session:
        art_repo = ArticleRepository(session)
        articles = art_repo.get_articles(
            hours_back=hours_back,
            limit=limit,
            search=search,
            source=source,
        )
        return [
            {
                "id": a.id,
                "title": a.title,
                "link": a.link,
                "source": a.source,
                "summary": a.summary,
                "published_at": a.published_at.isoformat() if a.published_at else None,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "has_embedding": bool(a.embedding),
            }
            for a in articles
        ]


@app.get("/api/cluster-runs")
def get_cluster_runs(
    limit: int = Query(50, ge=1, le=200, description="Max cluster runs to return"),
) -> list[dict[str, Any]]:
    """List cluster execution runs with timestamps and counts."""
    with get_session() as session:
        art_repo = ArticleRepository(session)
        runs = art_repo.list_cluster_runs(limit=limit)
        return [
            {
                "run_id": r["run_id"],
                "cluster_count": r["cluster_count"],
                "article_count": r["article_count"],
                "threshold": r["threshold"],
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            }
            for r in runs
        ]


@app.get("/api/clusters")
def get_clusters(
    response: Response,
    page: int | None = Query(None, ge=1, description="Page number for pagination"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page"),
    limit: int | None = Query(None, ge=1, le=200, description="Legacy limit parameter"),
    status: str | None = Query(None, description="Filter by status (pending, completed)"),
    search: str | None = Query(None, description="Search keyword in title or summary"),
    cluster_run_id: str | None = Query(None, description="Filter by cluster run ID"),
    include_articles: bool = Query(True, description="Whether to include member articles"),
) -> Any:
    """List story clusters with pagination, search, run filtering, and articles."""
    with get_session() as session:
        art_repo = ArticleRepository(session)

        if page is not None:
            clusters, total = art_repo.list_story_clusters_paginated(
                status=status,
                search=search,
                cluster_run_id=cluster_run_id,
                page=page,
                page_size=page_size,
            )
            total_pages = math.ceil(total / page_size) if page_size > 0 else 1
        else:
            effective_limit = limit or 50
            clusters = art_repo.get_recent_clusters(
                limit=effective_limit, cluster_run_id=cluster_run_id
            )
            total = art_repo.count_story_clusters(
                status=status, search=search, cluster_run_id=cluster_run_id
            )
            total_pages = 1

        if response is not None:
            response.headers["X-Total-Count"] = str(total)

        def _get_cluster_art_ids(cluster_obj: Any) -> list[int]:
            raw_ids = getattr(cluster_obj, "article_ids", None)
            if isinstance(raw_ids, str):
                try:
                    raw_ids = json.loads(raw_ids)
                except Exception:
                    raw_ids = []
            if isinstance(raw_ids, list):
                return [int(x) for x in raw_ids if str(x).isdigit()]
            return []

        articles_map: dict[int, dict[str, Any]] = {}
        if include_articles:
            all_art_ids = [aid for c in clusters for aid in _get_cluster_art_ids(c)]
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
            c_aids = _get_cluster_art_ids(c)
            cluster_articles = (
                [articles_map[aid] for aid in c_aids if aid in articles_map]
                if include_articles
                else []
            )
            results.append(
                {
                    "id": c.id,
                    "cluster_hash": c.cluster_hash,
                    "cluster_run_id": getattr(c, "cluster_run_id", "run_default"),
                    "run_cluster_index": getattr(c, "run_cluster_index", 1),
                    "title": c.title,
                    "summary": c.summary,
                    "article_count": c.article_count,
                    "article_ids": c_aids,
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
                "cluster_run_id": getattr(c, "cluster_run_id", "run_default"),
                "run_cluster_index": getattr(c, "run_cluster_index", 1),
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
            "cluster_run_id": getattr(cluster, "cluster_run_id", "run_default"),
            "run_cluster_index": getattr(cluster, "run_cluster_index", 1),
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
                prov: Literal["pexels", "giphy"] = "giphy" if req.provider == "giphy" else "pexels"
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
                    provider=req.provider or "custom",
                )
            else:
                updated = media_svc.update_placement_media(
                    job_id=job.id,
                    sentence_index=sentence_index,
                    new_media_path_or_url=req.url or "",
                    provider=req.provider or "custom",
                )

        return {
            "status": "success",
            "job_id": job.id,
            "placement": updated.model_dump(),
        }


@app.get("/api/media/search")
def search_media_candidates(
    query: str = Query(..., min_length=1, description="Search keywords"),
    provider: str = Query("giphy", description="Media search provider"),
    media_type: Literal["video", "image"] = Query("video", description="Desired media type"),
    limit: int = Query(12, ge=1, le=50, description="Max candidate results"),
    aspect_ratio: str = Query("9:16", description="Target aspect ratio"),
) -> list[dict[str, Any]]:
    """Search provider for media candidates to preview and select in the key materials inspector."""
    storage = get_storage_service()
    with get_session() as session:
        cost_repo = CostRepository(session)
        asset_repo = AssetRepository(session)
        media_svc = MediaService(
            storage_service=storage,
            cost_repo=cost_repo,
            asset_repo=asset_repo,
        )

        if provider == "giphy":
            return media_svc.search_giphy_candidates(query=query, limit=limit)
        elif provider == "pexels":
            return media_svc.search_pexels_candidates(
                query=query,
                media_type=media_type,
                limit=limit,
                aspect_ratio=aspect_ratio,
            )
        elif provider == "pixabay":
            return media_svc.search_pixabay_candidates(
                query=query,
                media_type=media_type,
                limit=limit,
                aspect_ratio=aspect_ratio,
            )
        else:
            return media_svc.search_custom_candidates(
                provider_id=provider,
                query=query,
                limit=limit,
            )


@app.post("/api/jobs/{job_id}/media/{sentence_index}/upload")
async def upload_job_media_file(
    job_id: int,
    sentence_index: int,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Upload custom media file (GIF, image, video) for a specific sentence frame."""
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

        if not file.filename:
            raise HTTPException(status_code=400, detail="Uploaded file missing filename")

        ext = Path(file.filename).suffix.lower()
        allowed_extensions = {".mp4", ".gif", ".jpg", ".jpeg", ".png", ".webp"}
        if ext not in allowed_extensions:
            formats = ", ".join(sorted(allowed_extensions))
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file format '{ext}'. Allowed: {formats}",
            )

        media_svc.media_cache_dir.mkdir(parents=True, exist_ok=True)
        dest_filename = f"job_{job.id}_sent_{sentence_index}_upload_{Path(file.filename).stem}{ext}"
        dest_path = media_svc.media_cache_dir / dest_filename

        content = await file.read()
        dest_path.write_bytes(content)

        with action_repo.track_operation(
            stage="media",
            action="upload_frame_material",
            actor="web",
            job_id=job.id,
            details={"sentence_index": sentence_index, "filename": file.filename},
        ):
            updated = media_svc.update_placement_media(
                job_id=job.id,
                sentence_index=sentence_index,
                new_media_path_or_url=str(dest_path.resolve()),
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
    if not render_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="A render job is already in progress. Only one concurrent render is permitted.",
        )

    pipeline_metrics.set_active_render_jobs(1)
    render_start = time.time()
    try:
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

            pipeline_metrics.record_stage_duration("render", time.time() - render_start)
            return {
                "status": "success",
                "job_id": job.id,
                "output_video_path": str(out_path.resolve()),
            }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        pipeline_metrics.set_active_render_jobs(0)
        render_lock.release()


@app.post("/api/jobs/{job_id}/convert-resolution")
def convert_job_video_resolution(
    job_id: int,
    req: VideoResolutionConvertRequest,
) -> dict[str, Any]:
    """Convert finalized video to different resolution spec (360p, 480p, 720p, 1080p)."""
    storage = get_storage_service()
    with get_session() as session:
        render_repo = RenderRepository(session)
        cost_repo = CostRepository(session)
        action_repo = ActionLogRepository(session)

        job = render_repo.get_job_by_id(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Render job {job_id} not found")
        if not job.output_video_path:
            raise HTTPException(
                status_code=400,
                detail=f"Job {job_id} has no completed video. Render the video first.",
            )

        render_svc = RenderService(render_repo, cost_repo, storage)
        with action_repo.track_operation(
            stage="render",
            action="convert_resolution",
            actor="web",
            job_id=job.id,
            details={"resolution": req.resolution},
        ):
            try:
                out_path = render_svc.convert_resolution(job_id=job.id, resolution=req.resolution)
            except ValueError as ve:
                raise HTTPException(status_code=400, detail=str(ve)) from ve
            except FileNotFoundError as fnf:
                raise HTTPException(status_code=404, detail=str(fnf)) from fnf
            except RuntimeError as re_err:
                raise HTTPException(status_code=500, detail=str(re_err)) from re_err

        return {
            "status": "success",
            "job_id": job.id,
            "resolution": req.resolution,
            "output_video_path": str(out_path.resolve()),
            "video_url": f"/static/videos/{out_path.name}",
        }


@app.get("/api/jobs/{job_id}/video")
def stream_job_video(
    job_id: int,
    resolution: str | None = Query(
        None,
        description="Optional resolution variant e.g. 360p, 480p, 720p, 1080p",
    ),
) -> FileResponse:
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
        if resolution:
            res_key = resolution.strip().lower()
            stem = local_path.stem
            for k in ["360p", "480p", "720p", "1080p"]:
                if stem.endswith(f"_{k}"):
                    stem = stem[: -len(f"_{k}")]
                    break
            variant = local_path.parent / f"{stem}_{res_key}.mp4"
            if variant.exists():
                local_path = variant

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
def download_job_video(
    job_id: int,
    resolution: str | None = Query(
        None,
        description="Optional resolution variant e.g. 360p, 480p, 720p, 1080p",
    ),
) -> FileResponse:
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
        if resolution:
            res_key = resolution.strip().lower()
            stem = local_path.stem
            for k in ["360p", "480p", "720p", "1080p"]:
                if stem.endswith(f"_{k}"):
                    stem = stem[: -len(f"_{k}")]
                    break
            variant = local_path.parent / f"{stem}_{res_key}.mp4"
            if variant.exists():
                local_path = variant

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
    try:
        raw_dict = yaml.safe_load(content)
        if isinstance(raw_dict, dict):
            masked_dict = mask_dict_secrets(raw_dict)
            safe_content = yaml.dump(masked_dict, default_flow_style=False, sort_keys=False)
        else:
            safe_content = content
    except Exception:
        safe_content = content

    return {
        "status": "success",
        "path": str(target_path),
        "exists": True,
        "yaml_content": safe_content,
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


@app.get("/api/config/beat-generator")
def get_beat_generator_config(
    filename: str | None = Query(default=None, description="Optional prompt config filename"),
) -> dict[str, Any]:
    """Fetch beat generator prompt configuration YAML."""
    with get_session() as session:
        art_repo = ArticleRepository(session)
        scr_repo = ScriptRepository(session)
        cost_repo = CostRepository(session)
        script_svc = ScriptService(art_repo, scr_repo, cost_repo)
        try:
            data = script_svc.get_beat_generator_config(filename=filename)
            available = script_svc.list_beat_generator_configs()
            data["available_files"] = available
            return data
        except FileNotFoundError as fnf:
            raise HTTPException(status_code=404, detail=str(fnf)) from fnf
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve)) from ve


@app.post("/api/config/beat-generator")
def update_beat_generator_config(
    req: BeatConfigUpdateRequest,
) -> dict[str, Any]:
    """Update beat generator prompt configuration YAML."""
    with get_session() as session:
        art_repo = ArticleRepository(session)
        scr_repo = ScriptRepository(session)
        cost_repo = CostRepository(session)
        action_repo = ActionLogRepository(session)
        script_svc = ScriptService(art_repo, scr_repo, cost_repo)

        with action_repo.track_operation(
            stage="config",
            action="update_beat_generator_config",
            actor="web",
            details={"filename": req.filename or "beat_sheet.yaml"},
        ):
            try:
                data = script_svc.update_beat_generator_config(
                    content=req.content,
                    filename=req.filename,
                )
                return {
                    "status": "success",
                    **data,
                }
            except ValueError as ve:
                raise HTTPException(status_code=400, detail=str(ve)) from ve


# ---------------------------------------------------------------------------
# System Configuration and Model Registry Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/config/system", response_model=SystemConfigResponse)
def get_system_configuration() -> SystemConfigResponse:
    """Retrieve full system configuration structured per current application architecture."""
    service = SystemConfigService()
    return service.get_system_config()


@app.post("/api/config/system", response_model=SystemConfigResponse)
def update_system_configuration(req: SystemConfigUpdateRequest) -> SystemConfigResponse:
    """Update modular system configuration sections and hot-reload runtime settings."""
    service = SystemConfigService()
    return service.update_system_config(req)


@app.get("/api/config/models", response_model=list[ModelDefinitionResponse])
def get_registered_models() -> list[ModelDefinitionResponse]:
    """List all model definitions in the unified provider-agnostic model registry."""
    service = SystemConfigService()
    return service.list_models()


@app.post("/api/config/models", response_model=ModelDefinitionResponse)
def register_or_update_model(model_def: ModelDefinition) -> ModelDefinitionResponse:
    """Register a new model definition or update existing entry in config.yaml."""
    service = SystemConfigService()
    return service.add_or_update_model(model_def)


@app.delete("/api/config/models/{model_name}")
def delete_registered_model(model_name: str) -> dict[str, Any]:
    """Delete a model definition from the registry and remove from role fallback chains."""
    service = SystemConfigService()
    deleted = service.delete_model(model_name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found in registry")
    return {"status": "success", "message": f"Deleted model '{model_name}' from registry"}


@app.get("/api/config/roles", response_model=RoleMappingsConfig)
def get_role_fallback_chains() -> RoleMappingsConfig:
    """Retrieve ordered model fallback priority lists for all pipeline roles."""
    service = SystemConfigService()
    return service.get_role_mappings()


@app.post("/api/config/roles", response_model=RoleMappingsConfig)
def update_role_fallback_chains(req: RoleFallbacksUpdateRequest) -> RoleMappingsConfig:
    """Update ordered model fallback priority lists for pipeline roles."""
    service = SystemConfigService()
    return service.update_role_mappings(req)


@app.post("/api/config/models/test", response_model=ModelTestResponse)
def test_registered_model(req: ModelTestRequest) -> ModelTestResponse:
    """Execute live latency and capability ping test against a registered model."""
    service = SystemConfigService()
    return service.test_model_connection(req.model_name, req.prompt)


# ---------------------------------------------------------------------------
# Visual Provider Hub and Diagnostics Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/providers", response_model=list[ProviderInfo])
def get_providers_list() -> list[ProviderInfo]:
    """Retrieve full catalog of built-in and custom providers with live status and priority."""
    provider_svc = ProviderService()
    return provider_svc.list_providers()


@app.post("/api/providers/test", response_model=ProviderTestResponse)
def test_provider_connection(req: ProviderTestRequest) -> ProviderTestResponse:
    """Execute live latency and authentication test against a specific media provider."""
    provider_svc = ProviderService()
    return provider_svc.test_provider(
        provider_id=req.provider_id,
        api_key=req.api_key,
        custom_config=req.custom_config,
    )


@app.post("/api/providers/custom", response_model=CustomProviderConfig)
def add_or_update_custom_provider(config: CustomProviderConfig) -> CustomProviderConfig:
    """Register or update a custom HTTP image, GIF, or video provider."""
    provider_svc = ProviderService()
    return provider_svc.add_custom_provider(config)


@app.delete("/api/providers/custom/{provider_id}")
def delete_custom_provider(provider_id: str) -> dict[str, Any]:
    """Delete a custom provider by identifier and remove from active pipeline cascade."""
    provider_svc = ProviderService()
    success = provider_svc.delete_custom_provider(provider_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Custom provider '{provider_id}' not found")
    return {"status": "success", "message": f"Deleted custom provider {provider_id}"}


@app.post("/api/providers/priority")
def update_provider_priority(req: ProviderPriorityRequest) -> dict[str, Any]:
    """Update priority cascade order for visual media selection."""
    provider_svc = ProviderService()
    updated_order = provider_svc.update_priority(req.priority_order)
    return {
        "status": "success",
        "priority_order": updated_order,
    }


@app.post("/api/providers/{provider_id}/toggle")
def toggle_provider_state(provider_id: str, req: ProviderToggleRequest) -> dict[str, Any]:
    """Enable or disable a specific provider in the cascade."""
    provider_svc = ProviderService()
    new_state = provider_svc.toggle_provider(provider_id, req.enabled)
    return {
        "status": "success",
        "provider_id": provider_id,
        "is_enabled": new_state,
    }


@app.post("/api/providers/credentials")
def update_provider_credentials(req: ProviderCredentialsRequest) -> dict[str, Any]:
    """Update and persist API credentials for a built-in or custom provider."""
    provider_svc = ProviderService()
    provider_svc.update_credentials(req.provider_id, req.api_key)
    return {
        "status": "success",
        "provider_id": req.provider_id,
        "message": f"Credentials updated for {req.provider_id}",
    }


@app.post("/api/providers/{provider_id}/move")
def move_provider_priority(
    provider_id: str,
    direction: Literal["up", "down"] = Query(..., description="Direction to shift priority"),
) -> dict[str, Any]:
    """Move a provider up or down in the fallback cascade order."""
    provider_svc = ProviderService()
    new_order = provider_svc.move_priority(provider_id, direction)
    return {"status": "success", "provider_id": provider_id, "priority_order": new_order}


@app.post("/api/providers/{provider_id}/remove")
def remove_provider_from_cascade(provider_id: str) -> dict[str, Any]:
    """Remove a provider from active cascade or delete if custom."""
    provider_svc = ProviderService()
    if any(c.get("id") == provider_id for c in settings.custom_providers):
        provider_svc.delete_custom_provider(provider_id)
        action_type = "deleted_custom"
    else:
        provider_svc.remove_from_cascade(provider_id)
        action_type = "removed_from_cascade"
    return {
        "status": "success",
        "provider_id": provider_id,
        "action": action_type,
        "priority_order": settings.provider_priority,
    }


@app.post("/api/providers/test-all", response_model=list[ProviderTestResponse])
def test_all_providers_connection() -> list[ProviderTestResponse]:
    """Execute live latency and authentication test across all registered providers."""
    provider_svc = ProviderService()
    return provider_svc.test_all_providers()


# ---------------------------------------------------------------------------
# Visual Configuration and Presets Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/config/visual", response_model=VisualConfigSchema)
def get_visual_pipeline_config() -> VisualConfigSchema:
    """Retrieve current visual pipeline configuration state."""
    visual_svc = VisualConfigService()
    return visual_svc.get_visual_config()


@app.get("/api/config/visual/presets", response_model=list[VisualPresetInfo])
def list_visual_presets() -> list[VisualPresetInfo]:
    """Retrieve catalog of one-click pipeline configuration presets."""
    visual_svc = VisualConfigService()
    return visual_svc.list_presets()


@app.post("/api/config/visual", response_model=VisualConfigSchema)
def update_visual_pipeline_config(req: VisualConfigUpdateRequest) -> VisualConfigSchema:
    """Save visual pipeline parameters into config.yaml and hot-reload runtime."""
    visual_svc = VisualConfigService()
    updated = visual_svc.save_visual_config(req)

    with get_session() as session:
        action_repo = ActionLogRepository(session)
        action_repo.record_action(
            stage="pipeline",
            action="update_visual_config",
            actor="web",
            status="success",
            message="Updated visual pipeline parameters and hot-reloaded configuration",
            details=req.model_dump(exclude_none=True),
        )

    return updated


@app.post("/api/config/visual/preset/{preset_id}", response_model=VisualConfigSchema)
def apply_visual_pipeline_preset(preset_id: str) -> VisualConfigSchema:
    """Apply a preset configuration profile and hot-reload pipeline settings."""
    visual_svc = VisualConfigService()
    try:
        updated = visual_svc.apply_preset(preset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    with get_session() as session:
        action_repo = ActionLogRepository(session)
        action_repo.record_action(
            stage="pipeline",
            action="apply_visual_preset",
            actor="web",
            status="success",
            message=f"Applied visual configuration preset {preset_id}",
            details={"preset_id": preset_id},
        )

    return updated


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


@app.get("/metrics")
def get_prometheus_metrics() -> Response:
    """Export platform telemetry in standard Prometheus text format."""
    spend = 0.0
    try:
        with get_session() as session:
            cost_repo = CostRepository(session)
            spend = cost_repo.get_total_spend()
    except Exception:
        spend = 0.0

    daily_budget = settings.cost_daily_budget_usd or 0.0
    active_renders = 1 if render_lock.locked() else pipeline_metrics.active_render_jobs

    content = pipeline_metrics.generate_prometheus_text(
        total_spend=spend,
        daily_budget=daily_budget,
        active_render_jobs=active_renders,
    )
    return Response(
        content=content,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


# ---------------------------------------------------------------------------
# Modern Web UI (Served at /)
# ---------------------------------------------------------------------------

DASHBOARD_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "dashboard.html"
FAVICON_PATH = Path(__file__).resolve().parent / "static" / "favicon.svg"


@app.get("/favicon.ico", include_in_schema=False)
@app.get("/favicon.svg", include_in_schema=False)
def favicon() -> Response:
    """Serve the studio tab icon."""
    if FAVICON_PATH.exists():
        return Response(content=FAVICON_PATH.read_bytes(), media_type="image/svg+xml")
    return Response(status_code=404)


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
