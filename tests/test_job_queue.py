"""Tests for JobQueueService: progress tracking, budget enforcement, and job queuing."""

from unittest.mock import patch

import pytest

from src.core.config import settings
from src.core.database import get_session
from src.models.entities import ScriptRecord, StoryCluster
from src.repositories.render_repository import RenderRepository
from src.services.job_queue_service import JobQueueService


@pytest.fixture
def queue_service() -> JobQueueService:
    return JobQueueService()


def test_get_progress_from_database(queue_service: JobQueueService) -> None:
    """Verify progress lookup falls back to database record for stored jobs."""
    import uuid

    with get_session() as session:
        cluster = StoryCluster(
            cluster_hash=f"q_test_{uuid.uuid4().hex[:8]}",
            title="Queue Test Cluster",
            summary="Testing queue service",
            article_ids=[],
            article_count=1,
        )
        session.add(cluster)
        session.flush()

        script = ScriptRecord(
            cluster_id=cluster.id,
            title="Queue Test Script",
            full_narration="Testing narration",
            beats=[],
        )
        session.add(script)
        session.flush()

        render_repo = RenderRepository(session)
        job = render_repo.create_job(script_id=script.id, aspect_ratio="9:16")
        job.status = "completed"
        job.output_video_path = "/tmp/test.mp4"
        session.commit()
        job_id = job.id

    progress = queue_service.get_progress(job_id)
    assert progress is not None
    assert progress["job_id"] == job_id
    assert progress["status"] == "completed"
    assert progress["percent"] == 100
    assert progress["output_video_path"] == "/tmp/test.mp4"


def test_budget_limits_enforced(queue_service: JobQueueService) -> None:
    """Verify that exceeding configured cost budget blocks job execution."""
    orig_daily = settings.cost_daily_budget_usd
    try:
        settings.cost_daily_budget_usd = 0.01

        with patch(
            "src.repositories.cost_repository.CostRepository.get_total_spend",
            return_value=1.50,
        ):
            within_budget, err = queue_service._check_budget_limits()
            assert within_budget is False
            assert err is not None
            assert "Daily budget limit exceeded" in err

            with pytest.raises(ValueError, match="Daily budget limit exceeded"):
                queue_service.submit_pipeline_job(cluster_id=1)
    finally:
        settings.cost_daily_budget_usd = orig_daily


def test_update_progress(queue_service: JobQueueService) -> None:
    """Verify in-memory and database progress updates."""
    import uuid

    with get_session() as session:
        cluster = StoryCluster(
            cluster_hash=f"q_prog_{uuid.uuid4().hex[:8]}",
            title="Progress Cluster",
            summary="Progress",
            article_ids=[],
            article_count=1,
        )
        session.add(cluster)
        session.flush()

        script = ScriptRecord(
            cluster_id=cluster.id,
            title="Script",
            full_narration="Narration",
            beats=[],
        )
        session.add(script)
        session.flush()

        render_repo = RenderRepository(session)
        job = render_repo.create_job(script_id=script.id, aspect_ratio="9:16")
        session.commit()
        job_id = job.id

    queue_service._update_progress(
        job_id=job_id,
        stage="tts",
        percent=45,
        message="Synthesizing speech",
        status="running",
    )

    prog = queue_service.get_progress(job_id)
    assert prog is not None
    assert prog["stage"] == "tts"
    assert prog["percent"] == 45
    assert prog["status"] == "running"
