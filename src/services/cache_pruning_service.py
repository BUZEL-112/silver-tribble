"""Housekeeping and cache maintenance service for pruning stale temporary media."""

import time
from pathlib import Path

from src.core.config import settings
from src.models.schemas import PruneResult
from src.repositories.asset_repository import AssetRepository


class CachePruningService:
    """Safely cleans unindexed temporary media downloads while protecting the visual asset library.
    """

    def __init__(self, asset_repo: AssetRepository | None = None) -> None:
        self.asset_repo = asset_repo

    def prune_cache(
        self,
        retention_hours: float | None = None,
        target_dir: Path | None = None,
        dry_run: bool = False,
    ) -> PruneResult:
        """Scan directory and delete unindexed temporary files exceeding retention window."""
        max_age_seconds = (
            retention_hours if retention_hours is not None else settings.cache_retention_hours
        ) * 3600.0
        now = time.time()
        dir_to_scan = target_dir or settings.media_cache_dir

        if not dir_to_scan.exists():
            return PruneResult(files_scanned=0, files_deleted=0, bytes_freed=0)

        # Build protected paths set from asset library
        protected_paths: set[str] = set()
        if self.asset_repo:
            try:
                indexed_assets = self.asset_repo.list_assets(limit=1000)
                protected_paths = {
                    str(Path(a.local_path).resolve()) for a in indexed_assets if a.local_path
                }
            except Exception:
                protected_paths = set()

        files_scanned = 0
        files_deleted = 0
        bytes_freed = 0

        for item in dir_to_scan.iterdir():
            if not item.is_file():
                continue

            files_scanned += 1
            resolved_str = str(item.resolve())

            # Never delete indexed library assets
            if resolved_str in protected_paths:
                continue

            # Always clean temporary download chunks
            is_temp_artifact = item.name.endswith((".tmp", ".tmp.mp3", ".part"))

            try:
                file_age = now - item.stat().st_mtime
                file_size = item.stat().st_size

                if is_temp_artifact or file_age >= max_age_seconds:
                    if not dry_run:
                        item.unlink(missing_ok=True)
                    files_deleted += 1
                    bytes_freed += file_size
            except Exception:
                pass

        return PruneResult(
            files_scanned=files_scanned,
            files_deleted=files_deleted,
            bytes_freed=bytes_freed,
        )
