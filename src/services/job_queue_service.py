"""Asynchronous job queue and execution manager with FIFO render lock and watchdog."""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from src.core.config import settings
from src.core.database import get_session
from src.flows.video_pipeline_flow import run_video_pipeline
from src.repositories.action_log_repository import ActionLogRepository
from src.repositories.cost_repository import CostRepository
from src.repositories.render_repository import RenderRepository
from src.repositories.script_repository import ScriptRepository
from src.services.caption_service import CaptionService
from src.services.media_service import MediaService
from src.services.render_service import RenderService
from src.services.storage_service import get_storage_service

logger = logging.getLogger(__name__)

# Single-concurrency lock for Remotion video rendering
_render_lock = threading.Lock()

# Worker thread pool for background pipeline execution
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ai-video-worker")

# Live progress tracker for running jobs
_live_progress: dict[int, dict[str, Any]] = {}
_progress_lock = threading.Lock()


class JobQueueService:
    """Coordinates async pipeline runs and serialized Remotion rendering."""

    def __init__(self) -> None:
        self.max_render_timeout_seconds = 300.0

    @staticmethod
    def _update_progress(
        job_id: int,
        stage: str,
        percent: int,
        message: str,
        status: str = "running",
        error: str | None = None,
        output_path: str | None = None,
    ) -> None:
        """Update live progress dictionary and database status."""
        with _progress_lock:
            _live_progress[job_id] = {
                "job_id": job_id,
                "stage": stage,
                "percent": percent,
                "message": message,
                "status": status,
                "error": error,
                "output_video_path": output_path,
                "updated_at": datetime.now(UTC).isoformat(),
            }

        with get_session() as session:
            repo = RenderRepository(session)
            if status in ("completed", "failed"):
                if status == "completed" and output_path:
                    repo.complete_job(job_id, output_path)
                elif status == "failed":
                    repo.fail_job(job_id, error or message)
            else:
                repo.update_job_status(job_id, stage, error)

    @classmethod
    def get_progress(cls, job_id: int) -> dict[str, Any] | None:
        """Retrieve live execution progress or query database status."""
        with _progress_lock:
            if job_id in _live_progress:
                return dict(_live_progress[job_id])

        with get_session() as session:
            repo = RenderRepository(session)
            job = repo.get_job_by_id(job_id)
            if not job:
                return None

            return {
                "job_id": job.id,
                "stage": job.status,
                "percent": 100 if job.status == "completed" else 0,
                "message": f"Job is {job.status}",
                "status": job.status,
                "error": job.error_message,
                "output_video_path": job.output_video_path,
                "updated_at": (job.completed_at or job.created_at).isoformat(),
            }

    def _check_budget_limits(self) -> tuple[bool, str | None]:
        """Verify whether daily or monthly budget limits have been exceeded."""
        daily_cap = settings.cost_daily_budget_usd
        monthly_cap = settings.cost_monthly_budget_usd
        if not daily_cap and not monthly_cap:
            return True, None

        with get_session() as session:
            cost_repo = CostRepository(session)
            total_spend = cost_repo.get_total_spend()

            if daily_cap and total_spend >= daily_cap:
                msg = (
                    f"Daily budget limit exceeded: spend ${total_spend:.2f} >= cap ${daily_cap:.2f}"
                )
                return False, msg
            if monthly_cap and total_spend >= monthly_cap:
                msg = (
                    f"Monthly budget limit exceeded: spend ${total_spend:.2f} "
                    f">= cap ${monthly_cap:.2f}"
                )
                return False, msg
        return True, None

    def submit_pipeline_job(
        self,
        cluster_id: int | None = None,
        cluster_ids: list[int] | None = None,
        aspect_ratio: str = "9:16",
        dry_run: bool = False,
    ) -> int:
        """Queue an end-to-end pipeline run and return the placeholder job ID immediately."""
        # 1. Budget verification
        within_budget, budget_err = self._check_budget_limits()
        if not within_budget:
            raise ValueError(budget_err)

        # 2. Create placeholder script and render job in database
        with get_session() as session:
            render_repo = RenderRepository(session)
            # Create a temporary render job record to assign an ID immediately
            job = render_repo.create_job(script_id=1, aspect_ratio=aspect_ratio)
            job.status = "queued"
            session.commit()
            job_id = job.id

        self._update_progress(
            job_id=job_id,
            stage="queued",
            percent=0,
            message="Pipeline run queued in background",
            status="queued",
        )

        # 3. Dispatch to worker pool
        _executor.submit(
            self._execute_pipeline_task,
            job_id=job_id,
            cluster_id=cluster_id,
            cluster_ids=cluster_ids,
            aspect_ratio=aspect_ratio,
            dry_run=dry_run,
        )
        return job_id

    def _execute_pipeline_task(
        self,
        job_id: int,
        cluster_id: int | None,
        cluster_ids: list[int] | None,
        aspect_ratio: str,
        dry_run: bool,
    ) -> None:
        """Worker task executing pipeline stages sequentially."""
        try:
            self._update_progress(
                job_id=job_id,
                stage="running",
                percent=10,
                message="Starting ingestion and clustering",
            )

            # Video pipeline flow coordinates the entire flow
            result = run_video_pipeline(
                cluster_id=cluster_id,
                cluster_ids=cluster_ids,
                aspect_ratio=aspect_ratio,
                dry_run=dry_run,
            )

            actual_job_id = result.get("job_id", job_id)
            output_path = result.get("output_video_path")

            self._update_progress(
                job_id=job_id,
                stage="completed",
                percent=100,
                message="Pipeline completed successfully",
                status="completed",
                output_path=output_path,
            )
            if actual_job_id != job_id:
                self._update_progress(
                    job_id=actual_job_id,
                    stage="completed",
                    percent=100,
                    message="Pipeline completed successfully",
                    status="completed",
                    output_path=output_path,
                )

        except Exception as exc:
            logger.exception("Pipeline run failed for job %d", job_id)
            self._update_progress(
                job_id=job_id,
                stage="failed",
                percent=100,
                message=str(exc),
                status="failed",
                error=str(exc),
            )

    def submit_render_job(self, job_id: int, dry_run: bool = False) -> None:
        """Queue a render job to execute Remotion under the serialized render lock."""
        self._update_progress(
            job_id=job_id,
            stage="queued",
            percent=0,
            message="Video render queued",
            status="queued",
        )

        _executor.submit(self._execute_render_task, job_id=job_id, dry_run=dry_run)

    def _execute_render_task(self, job_id: int, dry_run: bool) -> None:
        """Worker task that acquires the FIFO render lock and compiles the MP4."""
        self._update_progress(
            job_id=job_id,
            stage="waiting_lock",
            percent=10,
            message="Waiting for active render queue lock",
        )

        start_time = time.time()
        # Acquire serialized render lock
        with _render_lock:
            try:
                self._update_progress(
                    job_id=job_id,
                    stage="rendering",
                    percent=25,
                    message="Rendering video frames with Remotion",
                )

                storage = get_storage_service()
                with get_session() as session:
                    render_repo = RenderRepository(session)
                    cost_repo = CostRepository(session)
                    script_repo = ScriptRepository(session)
                    action_repo = ActionLogRepository(session)

                    job = render_repo.get_job_by_id(job_id)
                    if not job:
                        raise ValueError(f"RenderJob with id {job_id} not found")

                    script = script_repo.get_script_by_id(job.script_id)
                    if not script:
                        raise ValueError(f"Script with id {job.script_id} not found")

                    # Load or generate captions
                    captions = []
                    if job.captions_path:
                        cap_local = storage.get_local_path(job.captions_path)
                        if cap_local.exists():
                            import json

                            from src.models.schemas import WordCaption

                            data = json.loads(cap_local.read_text(encoding="utf-8"))
                            captions = [WordCaption(**item) for item in data]

                    if not captions:
                        caption_svc = CaptionService(storage, cost_repo)
                        _, captions = caption_svc.generate_captions(
                            audio_path_or_url=job.audio_path or "",
                            job_id=job.id,
                            reference_text=script.full_narration,
                            total_duration=job.duration_seconds or 30.0,
                        )

                    # Load placements
                    from src.models.schemas import SentenceMediaPlacement
                    from src.repositories.asset_repository import AssetRepository

                    placements = []
                    placements_path = settings.media_cache_dir / f"placements_job_{job.id}.json"
                    if placements_path.exists():
                        try:
                            import json

                            raw_p = json.loads(placements_path.read_text(encoding="utf-8"))
                            placements = [SentenceMediaPlacement(**item) for item in raw_p]
                        except Exception:
                            placements = []

                    if not placements:
                        asset_repo = AssetRepository(session)
                        media_svc = MediaService(storage, cost_repo, asset_repo)
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
                        actor="job_queue",
                        job_id=job.id,
                        details={"dry_run": dry_run},
                    ):
                        output_path = render_svc.execute_render(job_id=job.id, dry_run=dry_run)

                elapsed = time.time() - start_time
                logger.info("Render job %d completed in %.2fs", job_id, elapsed)

                self._update_progress(
                    job_id=job_id,
                    stage="completed",
                    percent=100,
                    message="Video rendered successfully",
                    status="completed",
                    output_path=str(output_path.resolve()),
                )

            except Exception as exc:
                logger.exception("Render job %d failed", job_id)
                self._update_progress(
                    job_id=job_id,
                    stage="failed",
                    percent=100,
                    message=str(exc),
                    status="failed",
                    error=str(exc),
                )
