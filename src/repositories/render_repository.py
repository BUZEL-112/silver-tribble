"""Repository for managing video render jobs and artifacts."""

from datetime import UTC, datetime

from src.models.entities import RenderJob
from src.repositories.base import BaseRepository


class RenderRepository(BaseRepository):
    """Encapsulates data operations for video rendering pipelines."""

    def create_job(self, script_id: int, aspect_ratio: str) -> RenderJob:
        """Create a new pending render job record."""
        job = RenderJob(
            script_id=script_id,
            aspect_ratio=aspect_ratio,
            status="pending",
        )
        self.session.add(job)
        self.session.flush()
        return job

    def get_job_by_id(self, job_id: int) -> RenderJob | None:
        """Fetch render job by primary key."""
        return self.session.get(RenderJob, job_id)

    def get_jobs_by_script(self, script_id: int) -> list[RenderJob]:
        """Fetch all render jobs associated with a given script ID."""
        from sqlalchemy import select

        stmt = select(RenderJob).where(RenderJob.script_id == script_id)
        return list(self.session.scalars(stmt).all())

    def update_job_audio(
        self,
        job_id: int,
        audio_path: str,
        duration_seconds: float,
    ) -> None:
        """Update job with synthesized audio path and duration."""
        job = self.get_job_by_id(job_id)
        if job:
            job.audio_path = audio_path
            job.duration_seconds = duration_seconds
            self.session.flush()

    def update_job_captions(self, job_id: int, captions_path: str) -> None:
        """Update job with generated Whisper captions JSON path."""
        job = self.get_job_by_id(job_id)
        if job:
            job.captions_path = captions_path
            self.session.flush()

    def update_job_render_props(self, job_id: int, render_props_path: str) -> None:
        """Update job with Remotion props JSON file path."""
        job = self.get_job_by_id(job_id)
        if job:
            job.render_props_path = render_props_path
            self.session.flush()

    def complete_job(self, job_id: int, output_video_path: str) -> None:
        """Mark job as successfully rendered."""
        job = self.get_job_by_id(job_id)
        if job:
            job.output_video_path = output_video_path
            job.status = "completed"
            job.completed_at = datetime.now(UTC)
            self.session.flush()

    def fail_job(self, job_id: int, error_message: str) -> None:
        """Mark job as failed with diagnostics."""
        job = self.get_job_by_id(job_id)
        if job:
            job.status = "failed"
            job.error_message = error_message
            job.completed_at = datetime.now(UTC)
            self.session.flush()
