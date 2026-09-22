"""Repository for article ingestion, embeddings, and story clustering."""

from sqlalchemy import func, or_, select

from src.models.entities import Article, StoryCluster
from src.models.schemas import FeedItem
from src.repositories.base import BaseRepository


class ArticleRepository(BaseRepository):
    """Encapsulates data operations for raw articles and story clusters."""

    def save_feed_items(self, items: list[FeedItem]) -> list[Article]:
        """Insert new articles ignoring duplicate URLs."""
        saved_articles: list[Article] = []
        seen_links: set[str] = set()
        for item in items:
            if not item.link or item.link in seen_links:
                continue
            existing = self.session.scalar(select(Article).where(Article.link == item.link))
            if existing:
                seen_links.add(item.link)
                continue

            seen_links.add(item.link)
            article = Article(
                title=item.title,
                link=item.link,
                summary=item.summary,
                source=item.source,
                published_at=item.published_at,
            )
            self.session.add(article)
            saved_articles.append(article)

        self.session.flush()
        return saved_articles

    def get_articles_without_embeddings(self, limit: int = 50) -> list[Article]:
        """Fetch articles that lack vector embeddings."""
        stmt = (
            select(Article)
            .where(Article.embedding.is_(None))
            .order_by(Article.created_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def update_article_embedding(self, article_id: int, embedding: list[float]) -> None:
        """Assign vector embedding coordinates to an article."""
        article = self.session.get(Article, article_id)
        if article:
            article.embedding = embedding
            self.session.flush()

    def get_all_embedded_articles(self, limit: int = 200) -> list[Article]:
        """Retrieve recent articles that possess embeddings for clustering."""
        stmt = (
            select(Article)
            .where(Article.embedding.is_not(None))
            .order_by(Article.created_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def save_story_cluster(
        self,
        cluster_hash: str,
        title: str,
        summary: str,
        article_ids: list[int],
    ) -> StoryCluster:
        """Create or update a story cluster by unique cluster hash."""
        existing = self.session.scalar(
            select(StoryCluster).where(StoryCluster.cluster_hash == cluster_hash)
        )
        if existing:
            existing.title = title
            existing.summary = summary
            existing.article_ids = article_ids
            existing.article_count = len(article_ids)
            self.session.flush()
            return existing

        cluster = StoryCluster(
            cluster_hash=cluster_hash,
            title=title,
            summary=summary,
            article_ids=article_ids,
            article_count=len(article_ids),
            status="pending",
        )
        self.session.add(cluster)
        self.session.flush()
        return cluster

    def count_articles(self) -> int:
        """Count total stored articles in repository."""
        stmt = select(func.count(Article.id))
        return self.session.scalar(stmt) or 0

    def count_story_clusters(
        self,
        status: str | None = None,
        search: str | None = None,
    ) -> int:
        """Count total story clusters matching status and search filter."""
        stmt = select(func.count(StoryCluster.id))
        if status:
            stmt = stmt.where(StoryCluster.status == status)
        if search:
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    StoryCluster.title.ilike(pattern),
                    StoryCluster.summary.ilike(pattern),
                )
            )
        return self.session.scalar(stmt) or 0

    def list_story_clusters_paginated(
        self,
        status: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[list[StoryCluster], int]:
        """Return paginated story clusters and total matching count."""
        total = self.count_story_clusters(status=status, search=search)
        stmt = select(StoryCluster)
        if status:
            stmt = stmt.where(StoryCluster.status == status)
        if search:
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    StoryCluster.title.ilike(pattern),
                    StoryCluster.summary.ilike(pattern),
                )
            )
        offset_val = max(0, (page - 1) * page_size)
        stmt = (
            stmt.order_by(
                StoryCluster.article_count.desc(),
                StoryCluster.created_at.desc(),
            )
            .offset(offset_val)
            .limit(page_size)
        )
        items = list(self.session.scalars(stmt).all())
        return items, total

    def list_story_clusters(
        self,
        status: str | None = None,
        limit: int = 20,
    ) -> list[StoryCluster]:
        """Return story clusters ordered by article count and creation date."""
        stmt = select(StoryCluster)
        if status:
            stmt = stmt.where(StoryCluster.status == status)
        stmt = stmt.order_by(
            StoryCluster.article_count.desc(),
            StoryCluster.created_at.desc(),
        ).limit(limit)
        return list(self.session.scalars(stmt).all())

    def get_recent_clusters(self, limit: int = 20) -> list[StoryCluster]:
        """Alias to list_story_clusters for retrieving recent story clusters."""
        return self.list_story_clusters(limit=limit)

    def get_cluster_by_id(self, cluster_id: int) -> StoryCluster | None:
        """Find a single story cluster by primary key."""
        return self.session.get(StoryCluster, cluster_id)

    def get_articles_by_ids(self, article_ids: list[int]) -> list[Article]:
        """Retrieve full article records matching a list of IDs."""
        if not article_ids:
            return []
        stmt = select(Article).where(Article.id.in_(article_ids))
        return list(self.session.scalars(stmt).all())

    def update_cluster_status(self, cluster_id: int, status: str) -> None:
        """Update cluster lifecycle state."""
        cluster = self.session.get(StoryCluster, cluster_id)
        if cluster:
            cluster.status = status
            self.session.flush()

    def get_trending_clusters(
        self,
        limit: int = 10,
        status: str | None = "pending",
        hours_back: int | None = 72,
    ) -> list[tuple[StoryCluster, float]]:
        """Rank clusters by trending velocity based on volume, sources, and recency."""
        from datetime import UTC, datetime

        clusters = self.list_story_clusters(status=status, limit=limit * 3)
        if not clusters:
            return []

        now = datetime.now(UTC)
        scored_clusters: list[tuple[StoryCluster, float]] = []

        for c in clusters:
            created = c.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            age_hours = max((now - created).total_seconds() / 3600.0, 0.1)

            if hours_back is not None and age_hours > hours_back:
                continue

            articles = self.get_articles_by_ids(c.article_ids)
            distinct_sources = len({a.source for a in articles if a.source})
            article_count = len(articles)

            recency_multiplier = 1.0 / (1.0 + (age_hours / 12.0))

            velocity_score = (article_count * 2.0 + distinct_sources * 3.0) * recency_multiplier
            scored_clusters.append((c, round(velocity_score, 2)))

        scored_clusters.sort(key=lambda x: x[1], reverse=True)
        return scored_clusters[:limit]
