"""Repository for script records and beat sheet storage."""

from typing import Any

from src.models.entities import ScriptRecord
from src.repositories.base import BaseRepository


class ScriptRepository(BaseRepository):
    """Encapsulates data operations for generated video scripts."""

    def create_script(
        self,
        cluster_id: int,
        title: str,
        aspect_ratio: str,
        beats: list[dict[str, Any]],
        full_narration: str,
    ) -> ScriptRecord:
        """Store newly generated script record."""
        script = ScriptRecord(
            cluster_id=cluster_id,
            title=title,
            aspect_ratio=aspect_ratio,
            beats=beats,
            full_narration=full_narration,
        )
        self.session.add(script)
        self.session.flush()
        return script

    def get_script_by_id(self, script_id: int) -> ScriptRecord | None:
        """Fetch script record by primary key."""
        return self.session.get(ScriptRecord, script_id)

    def get_scripts_by_cluster(self, cluster_id: int) -> list[ScriptRecord]:
        """Fetch all scripts associated with a given story cluster."""
        from sqlalchemy import select

        stmt = select(ScriptRecord).where(ScriptRecord.cluster_id == cluster_id)
        return list(self.session.scalars(stmt).all())
