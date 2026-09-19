"""Repository for operational action logging and audit trail."""

import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import select

from src.models.entities import ActionLog
from src.repositories.base import BaseRepository


class ActionLogRepository(BaseRepository):
    """Encapsulates data operations for audit action logs."""

    def record_action(
        self,
        stage: str,
        action: str,
        actor: str = "cli",
        status: str = "started",
        message: str = "",
        details: dict[str, Any] | None = None,
        job_id: int | None = None,
        duration_seconds: float | None = None,
    ) -> ActionLog:
        """Insert and persist an operational action log entry."""
        log_entry = ActionLog(
            stage=stage,
            action=action,
            actor=actor,
            status=status,
            message=message,
            details=details,
            job_id=job_id,
            duration_seconds=duration_seconds,
        )
        self.session.add(log_entry)
        self.session.flush()
        return log_entry

    def get_recent_logs(
        self,
        limit: int = 100,
        stage: str | None = None,
        status: str | None = None,
    ) -> list[ActionLog]:
        """Query recent action logs with optional stage and status filters."""
        stmt = select(ActionLog).order_by(ActionLog.created_at.desc(), ActionLog.id.desc())
        if stage:
            stmt = stmt.where(ActionLog.stage == stage)
        if status:
            stmt = stmt.where(ActionLog.status == status)
        stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt).all())

    @contextmanager
    def track_operation(
        self,
        stage: str,
        action: str,
        actor: str = "cli",
        job_id: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> Generator[ActionLog, None, None]:
        """Context manager to record started, success, or failed execution of operations."""
        start_time = time.time()
        start_log = self.record_action(
            stage=stage,
            action=action,
            actor=actor,
            status="started",
            message=f"Started {action}",
            details=details,
            job_id=job_id,
            duration_seconds=None,
        )

        try:
            yield start_log
            duration = round(time.time() - start_time, 3)
            self.record_action(
                stage=stage,
                action=action,
                actor=actor,
                status="success",
                message=f"Completed {action} successfully",
                details=details,
                job_id=job_id,
                duration_seconds=duration,
            )
        except Exception as exc:
            duration = round(time.time() - start_time, 3)
            self.record_action(
                stage=stage,
                action=action,
                actor=actor,
                status="failed",
                message=str(exc),
                details=details,
                job_id=job_id,
                duration_seconds=duration,
            )
            raise
