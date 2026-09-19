"""Repository for pipeline cost logging and budget analytics."""

from typing import Any

from sqlalchemy import func, select

from src.models.entities import CostLogEntry
from src.models.schemas import CostLogCreate
from src.repositories.base import BaseRepository


class CostRepository(BaseRepository):
    """Encapsulates cost logging operations across all pipeline stages."""

    def log_cost(self, entry: CostLogCreate) -> CostLogEntry:
        """Insert a cost transaction record into the cost_log table."""
        record = CostLogEntry(
            job_id=entry.job_id,
            stage=entry.stage,
            provider=entry.provider,
            model=entry.model,
            units=entry.units,
            unit_type=entry.unit_type,
            cost_usd=entry.cost_usd,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def get_job_costs(self, job_id: int) -> list[CostLogEntry]:
        """Fetch all cost logs associated with a specific render job."""
        stmt = (
            select(CostLogEntry)
            .where(CostLogEntry.job_id == job_id)
            .order_by(CostLogEntry.created_at.asc())
        )
        return list(self.session.scalars(stmt).all())

    def get_total_spend(self) -> float:
        """Calculate aggregate spend across all pipeline operations."""
        stmt = select(func.coalesce(func.sum(CostLogEntry.cost_usd), 0.0))
        return float(self.session.scalar(stmt) or 0.0)

    def get_spend_by_stage(self) -> list[dict[str, Any]]:
        """Group and sum costs by pipeline execution stage."""
        stmt = (
            select(
                CostLogEntry.stage,
                func.count(CostLogEntry.id).label("call_count"),
                func.sum(CostLogEntry.cost_usd).label("total_usd"),
            )
            .group_by(CostLogEntry.stage)
            .order_by(func.sum(CostLogEntry.cost_usd).desc())
        )
        results = self.session.execute(stmt).all()
        return [
            {"stage": row[0], "call_count": row[1], "total_usd": float(row[2])}
            for row in results
        ]

    def get_per_video_costs(self, limit: int = 10) -> list[dict[str, Any]]:
        """Compute aggregated cost grouped by video job ID."""
        stmt = (
            select(
                CostLogEntry.job_id,
                func.sum(CostLogEntry.cost_usd).label("total_usd"),
                func.count(CostLogEntry.id).label("records_count"),
            )
            .where(CostLogEntry.job_id.is_not(None))
            .group_by(CostLogEntry.job_id)
            .order_by(func.sum(CostLogEntry.cost_usd).desc())
            .limit(limit)
        )
        results = self.session.execute(stmt).all()
        return [
            {"job_id": row[0], "total_usd": float(row[1]), "records_count": row[2]}
            for row in results
        ]
