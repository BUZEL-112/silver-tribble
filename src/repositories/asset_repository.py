"""Repository for managing the reusable, metadata-rich visual asset library."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import desc, select

from src.models.entities import VisualAsset
from src.models.schemas import VisualAssetCreate
from src.repositories.base import BaseRepository


class AssetRepository(BaseRepository):
    """Encapsulates data operations for visual assets in the reusable asset library."""

    @staticmethod
    def generate_asset_hash(source_url: str | None, local_path: str) -> str:
        """Create a deterministic SHA-256 hash representing the asset identity."""
        identity = (source_url or local_path).strip()
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def find_matching_asset(
        self,
        query: str,
        emotion: str | None = None,
        media_type: str | None = None,
        aspect_ratio: str = "9:16",
        excluded_paths: set[str] | None = None,
        min_vlm_score: float = 6.0,
    ) -> VisualAsset | None:
        """Search library for an existing verified asset matching query, emotion, or tags."""
        stmt = select(VisualAsset).where(VisualAsset.aspect_ratio == aspect_ratio)

        if media_type:
            stmt = stmt.where(VisualAsset.media_type == media_type)

        stmt = stmt.order_by(
            VisualAsset.vlm_score.desc().nulls_last(),
            VisualAsset.usage_count.asc(),
        )

        candidates = list(self.session.scalars(stmt).all())
        clean_q = query.strip().lower()
        clean_words = set(clean_q.split())
        scored_candidates: list[tuple[VisualAsset, float]] = []
        excluded = excluded_paths or set()

        for asset in candidates:
            if asset.local_path in excluded:
                continue

            # Verify file actually exists on disk
            if not Path(asset.local_path).exists():
                continue

            # Filter by VLM score if set
            if asset.vlm_score is not None and asset.vlm_score < min_vlm_score:
                continue

            score = 0.0
            asset_q = (asset.query or "").lower()

            # Exact or substring query match
            if clean_q and (clean_q in asset_q or asset_q in clean_q):
                score += 5.0

            # Tags match
            asset_tags = set(t.lower() for t in (asset.tags or []))
            overlap = len(clean_words.intersection(asset_tags))
            score += overlap * 3.0

            # Emotion match
            if emotion and emotion != "neutral":
                asset_emotions = set(e.lower() for e in (asset.emotion_tags or []))
                if emotion.lower() in asset_emotions:
                    score += 2.5

            # VLM quality weight
            if asset.vlm_score is not None:
                score += (asset.vlm_score / 10.0) * 2.0

            # Usage frequency penalty to encourage diversity
            score -= min(asset.usage_count * 0.5, 3.0)

            if score > 0.0:
                scored_candidates.append((asset, score))

        if not scored_candidates:
            return None

        scored_candidates.sort(key=lambda x: x[1], reverse=True)
        return scored_candidates[0][0]

    def record_asset(self, item: VisualAssetCreate) -> VisualAsset:
        """Insert or update a visual asset record with metadata."""
        existing = self.session.scalar(
            select(VisualAsset).where(VisualAsset.asset_hash == item.asset_hash)
        )
        now = datetime.now(UTC)

        if existing:
            existing.usage_count += 1
            existing.last_used_at = now
            if item.vlm_score is not None:
                existing.vlm_score = item.vlm_score
            if item.vlm_reason:
                existing.vlm_reason = item.vlm_reason
            if item.tags:
                merged_tags = list(set(existing.tags + item.tags))
                existing.tags = merged_tags
            if item.emotion_tags:
                merged_emotions = list(set(existing.emotion_tags + item.emotion_tags))
                existing.emotion_tags = merged_emotions
            self.session.flush()
            return existing

        asset = VisualAsset(
            asset_hash=item.asset_hash,
            source_url=item.source_url,
            local_path=item.local_path,
            media_type=item.media_type,
            provider=item.provider,
            query=item.query,
            tags=item.tags,
            emotion_tags=item.emotion_tags,
            shot_type=item.shot_type,
            aspect_ratio=item.aspect_ratio,
            vlm_score=item.vlm_score,
            vlm_reason=item.vlm_reason,
            usage_count=1,
            created_at=now,
            last_used_at=now,
        )
        self.session.add(asset)
        self.session.flush()
        return asset

    def increment_usage(self, asset_id: int) -> None:
        """Increment usage count for an asset upon reuse."""
        asset = self.session.get(VisualAsset, asset_id)
        if asset:
            asset.usage_count += 1
            asset.last_used_at = datetime.now(UTC)
            self.session.flush()

    def list_assets(
        self,
        limit: int = 100,
        provider: str | None = None,
        emotion: str | None = None,
    ) -> list[VisualAsset]:
        """Fetch indexed visual assets ordered by recency."""
        stmt = select(VisualAsset)
        if provider:
            stmt = stmt.where(VisualAsset.provider == provider)
        if emotion:
            # Query in-memory filtering for JSON list in SQLite/Postgres compatibility
            pass
        stmt = stmt.order_by(desc(VisualAsset.last_used_at)).limit(limit)
        results = list(self.session.scalars(stmt).all())
        if emotion:
            results = [r for r in results if emotion.lower() in [e.lower() for e in r.emotion_tags]]
        return results
