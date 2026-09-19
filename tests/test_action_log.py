"""Unit tests for ActionLog entity and ActionLogRepository."""

import pytest
from sqlalchemy.orm import Session

from src.repositories.action_log_repository import ActionLogRepository


def test_record_action(action_repo: ActionLogRepository, db_session: Session) -> None:
    """Test recording a single action log entry."""
    entry = action_repo.record_action(
        stage="ingest",
        action="fetch_rss_feeds",
        actor="cli",
        status="success",
        message="Fetched 10 items",
        details={"count": 10},
        job_id=1,
        duration_seconds=1.23,
    )
    db_session.commit()

    assert entry.id is not None
    assert entry.stage == "ingest"
    assert entry.action == "fetch_rss_feeds"
    assert entry.actor == "cli"
    assert entry.status == "success"
    assert entry.message == "Fetched 10 items"
    assert entry.details == {"count": 10}
    assert entry.job_id == 1
    assert entry.duration_seconds == 1.23
    assert entry.created_at is not None


def test_get_recent_logs(action_repo: ActionLogRepository, db_session: Session) -> None:
    """Test filtering and limiting recent action logs."""
    action_repo.record_action(stage="ingest", action="fetch", actor="cli", status="success")
    action_repo.record_action(stage="cluster", action="cluster", actor="agent", status="failed")
    action_repo.record_action(stage="script", action="generate", actor="web", status="success")
    db_session.commit()

    all_logs = action_repo.get_recent_logs(limit=10)
    assert len(all_logs) >= 3

    ingest_logs = action_repo.get_recent_logs(stage="ingest")
    assert len(ingest_logs) == 1
    assert ingest_logs[0].stage == "ingest"

    failed_logs = action_repo.get_recent_logs(status="failed")
    assert len(failed_logs) == 1
    assert failed_logs[0].status == "failed"


def test_track_operation_success(action_repo: ActionLogRepository, db_session: Session) -> None:
    """Test track_operation context manager on successful completion."""
    with action_repo.track_operation(
        stage="voice",
        action="synthesize_speech",
        actor="cli",
        job_id=42,
    ):
        # Simulate quick operation
        pass
    db_session.commit()

    logs = action_repo.get_recent_logs(stage="voice", limit=5)
    assert len(logs) == 2

    # Most recent first: success then started
    success_log = logs[0]
    started_log = logs[1]

    assert started_log.status == "started"
    assert started_log.job_id == 42
    assert success_log.status == "success"
    assert success_log.duration_seconds is not None
    assert success_log.duration_seconds >= 0.0


def test_track_operation_failure(action_repo: ActionLogRepository, db_session: Session) -> None:
    """Test track_operation context manager on raised exception."""
    with pytest.raises(RuntimeError, match="Simulated crash"):
        with action_repo.track_operation(
            stage="render",
            action="render_video",
            actor="agent",
            job_id=99,
        ):
            raise RuntimeError("Simulated crash")
    db_session.commit()

    logs = action_repo.get_recent_logs(stage="render", limit=5)
    assert len(logs) == 2

    failed_log = logs[0]
    started_log = logs[1]

    assert started_log.status == "started"
    assert failed_log.status == "failed"
    assert "Simulated crash" in failed_log.message
    assert failed_log.duration_seconds is not None
