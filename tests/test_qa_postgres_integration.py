"""PostgreSQL-only integration tests for the ai-news-video-pipeline repositories.

These tests run ONLY when the DATABASE_URL environment variable is set to a
PostgreSQL connection string (one that does NOT start with 'sqlite').  When no
PostgreSQL URL is detected every test in this module is automatically skipped
so the default SQLite-backed CI run is never broken.

Covered scenarios
-----------------
ArticleRepository
    - save_feed_items persists rows to PostgreSQL
    - duplicate URL detection relies on PostgreSQL unique constraints
    - update_article_embedding stores a vector value and can be read back
    - get_all_embedded_articles returns only articles that have an embedding
    - list_story_clusters_paginated respects page/page_size and PG ordering

RenderRepository
    - create_job and get_job_by_id survive a full round-trip in PostgreSQL

ScriptRepository
    - create_script and get_script_by_id survive a full round-trip in PostgreSQL

Transaction integrity
    - A session whose commit is interrupted leaves no data behind

Concurrency / constraint enforcement
    - Two sessions writing the same URL result in exactly one row being saved
"""

from __future__ import annotations

import os
import threading
from collections.abc import Generator
from typing import Any

import pytest
from sqlalchemy import create_engine, delete, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from src.core.database import Base
from src.models.schemas import FeedItem
from src.repositories.article_repository import ArticleRepository
from src.repositories.render_repository import RenderRepository
from src.repositories.script_repository import ScriptRepository

# ---------------------------------------------------------------------------
# Module-level skip guard
# ---------------------------------------------------------------------------

_DATABASE_URL: str = os.environ.get("DATABASE_URL", "")
_IS_POSTGRES: bool = bool(_DATABASE_URL and not _DATABASE_URL.startswith("sqlite"))

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.skipif(
        not _IS_POSTGRES,
        reason="PostgreSQL tests skipped: DATABASE_URL is not set to a PostgreSQL URL.",
    ),
]


# ---------------------------------------------------------------------------
# Helper: normalise bare postgresql:// to psycopg2 dialect
# ---------------------------------------------------------------------------


def _pg_url(raw: str) -> str:
    """Return a psycopg2-pinned URL to avoid SQLAlchemy 2.x defaulting to psycopg3."""
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+psycopg2://", 1)
    return raw


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_engine():
    """Create a real PostgreSQL engine, install pgvector, create tables.

    Drops all tables after the module finishes to leave the database clean.
    """
    url = _pg_url(_DATABASE_URL)
    engine = create_engine(url, pool_pre_ping=True, echo=False)

    # Install pgvector extension if available; non-fatal if it is missing.
    with engine.connect() as conn:
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        except Exception:
            conn.rollback()

    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def pg_session(pg_engine) -> Generator[Session, None, None]:
    """Provide an isolated session per test.

    Each test runs inside a savepoint that is rolled back on teardown so that
    tests are hermetically isolated without needing to truncate tables.
    """
    connection = pg_engine.connect()
    transaction = connection.begin()

    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=connection,
    )
    session = session_factory()

    # Nested savepoint so that test-level rollback does not close the outer
    # transaction that owns the schema.
    session.begin_nested()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# ---------------------------------------------------------------------------
# Convenience builders
# ---------------------------------------------------------------------------


def _make_feed_item(
    *,
    title: str = "Test Article",
    link: str = "https://example.com/article-1",
    summary: str = "A test summary.",
    source: str = "test-source",
) -> FeedItem:
    """Return a minimal valid FeedItem."""
    return FeedItem(title=title, link=link, summary=summary, source=source)


def _seed_cluster(session: Session) -> Any:
    """Insert a minimal StoryCluster and flush it; returns the ORM object."""
    from src.models.entities import StoryCluster

    cluster = StoryCluster(
        cluster_hash="deadbeef" + "0" * 56,
        title="Seed Cluster",
        summary="Seed summary.",
        article_ids=[],
        article_count=0,
        status="pending",
    )
    session.add(cluster)
    session.flush()
    return cluster


def _seed_script(session: Session, cluster_id: int) -> Any:
    """Insert a minimal ScriptRecord and flush it; returns the ORM object."""
    from src.models.entities import ScriptRecord

    script = ScriptRecord(
        cluster_id=cluster_id,
        cluster_ids=[cluster_id],
        title="Seed Script",
        aspect_ratio="9:16",
        beats=[],
        full_narration="Full narration text.",
    )
    session.add(script)
    session.flush()
    return script


# ---------------------------------------------------------------------------
# ArticleRepository tests
# ---------------------------------------------------------------------------


class TestArticleRepositoryPostgres:
    """ArticleRepository behaviour when backed by a live PostgreSQL database."""

    def test_save_feed_items_persists_articles_to_postgres(self, pg_session: Session) -> None:
        """save_feed_items inserts new rows and returns the saved Article objects."""
        # Arrange
        repo = ArticleRepository(pg_session)
        items = [
            _make_feed_item(link="https://pg.test/art-1", title="Article One"),
            _make_feed_item(link="https://pg.test/art-2", title="Article Two"),
        ]

        # Act
        saved = repo.save_feed_items(items)

        # Assert
        assert len(saved) == 2
        assert {a.link for a in saved} == {"https://pg.test/art-1", "https://pg.test/art-2"}
        assert all(a.id is not None for a in saved)

    def test_save_feed_items_skips_duplicate_url(self, pg_session: Session) -> None:
        """save_feed_items returns only novel articles when the URL already exists."""
        # Arrange
        repo = ArticleRepository(pg_session)
        item = _make_feed_item(link="https://pg.test/dup-art", title="Original Article")
        repo.save_feed_items([item])

        duplicate_item = _make_feed_item(link="https://pg.test/dup-art", title="Duplicate Title")

        # Act
        second_batch = repo.save_feed_items([duplicate_item])

        # Assert
        assert second_batch == []
        assert repo.count_articles() == 1

    def test_update_article_embedding_stores_vector_in_postgres(self, pg_session: Session) -> None:
        """update_article_embedding writes a float list that can be retrieved."""
        # Arrange
        repo = ArticleRepository(pg_session)
        (article,) = repo.save_feed_items(
            [_make_feed_item(link="https://pg.test/embed-art", title="Embed Article")]
        )
        embedding = [0.1 * i for i in range(8)]

        # Act
        repo.update_article_embedding(article.id, embedding)

        # Assert
        pg_session.expire(article)
        refreshed = pg_session.get(type(article), article.id)
        assert refreshed is not None
        assert refreshed.embedding is not None
        assert len(refreshed.embedding) == 8
        assert abs(refreshed.embedding[3] - 0.3) < 1e-6

    def test_get_all_embedded_articles_excludes_articles_without_embeddings(
        self, pg_session: Session
    ) -> None:
        """get_all_embedded_articles returns only rows whose embedding is not NULL."""
        # Arrange
        repo = ArticleRepository(pg_session)
        (with_embed,) = repo.save_feed_items(
            [_make_feed_item(link="https://pg.test/has-embed", title="Has Embedding")]
        )
        repo.save_feed_items(
            [_make_feed_item(link="https://pg.test/no-embed", title="No Embedding")]
        )
        repo.update_article_embedding(with_embed.id, [0.5, 0.5])

        # Act
        results = repo.get_all_embedded_articles()

        # Assert
        result_ids = [a.id for a in results]
        assert with_embed.id in result_ids
        assert all(a.embedding is not None for a in results)

    def test_list_story_clusters_paginated_respects_page_and_page_size(
        self, pg_session: Session
    ) -> None:
        """Pagination returns the correct slice and accurate total count."""
        # Arrange
        repo = ArticleRepository(pg_session)
        hashes = [f"cluster{i:060d}" for i in range(5)]
        for i, h in enumerate(hashes):
            repo.save_story_cluster(
                cluster_hash=h,
                title=f"Cluster {i}",
                summary="Summary.",
                article_ids=[],
            )

        # Act
        page1, total = repo.list_story_clusters_paginated(page=1, page_size=3)
        page2, total2 = repo.list_story_clusters_paginated(page=2, page_size=3)

        # Assert
        assert total == 5
        assert total2 == 5
        assert len(page1) == 3
        assert len(page2) == 2
        # Pages must not overlap
        page1_ids = {c.id for c in page1}
        page2_ids = {c.id for c in page2}
        assert page1_ids.isdisjoint(page2_ids)


# ---------------------------------------------------------------------------
# RenderRepository tests
# ---------------------------------------------------------------------------


class TestRenderRepositoryPostgres:
    """RenderRepository behaviour when backed by a live PostgreSQL database."""

    def test_create_job_and_get_job_by_id_round_trip(self, pg_session: Session) -> None:
        """create_job persists a RenderJob row that get_job_by_id can retrieve."""
        # Arrange
        cluster = _seed_cluster(pg_session)
        script = _seed_script(pg_session, cluster.id)
        render_repo = RenderRepository(pg_session)

        # Act
        job = render_repo.create_job(script_id=script.id, aspect_ratio="16:9")
        pg_session.flush()
        retrieved = render_repo.get_job_by_id(job.id)

        # Assert
        assert retrieved is not None
        assert retrieved.id == job.id
        assert retrieved.script_id == script.id
        assert retrieved.aspect_ratio == "16:9"
        assert retrieved.status == "pending"


# ---------------------------------------------------------------------------
# ScriptRepository tests
# ---------------------------------------------------------------------------


class TestScriptRepositoryPostgres:
    """ScriptRepository behaviour when backed by a live PostgreSQL database."""

    def test_create_script_and_get_script_by_id_round_trip(self, pg_session: Session) -> None:
        """create_script persists a ScriptRecord that get_script_by_id can retrieve."""
        # Arrange
        cluster = _seed_cluster(pg_session)
        script_repo = ScriptRepository(pg_session)
        beats: list[dict[str, Any]] = [
            {"beat_number": 1, "core_point": "Opening hook."},
        ]

        # Act
        created = script_repo.create_script(
            cluster_id=cluster.id,
            title="PG Script Title",
            aspect_ratio="9:16",
            beats=beats,
            full_narration="This is the full narration.",
            cluster_ids=[cluster.id],
        )
        pg_session.flush()
        retrieved = script_repo.get_script_by_id(created.id)

        # Assert
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.title == "PG Script Title"
        assert retrieved.beats == beats
        assert retrieved.full_narration == "This is the full narration."
        assert retrieved.cluster_ids == [cluster.id]


# ---------------------------------------------------------------------------
# Transaction rollback test
# ---------------------------------------------------------------------------


class TestTransactionRollbackPostgres:
    """Verify that data written before a failed commit does not reach the database."""

    def test_failed_commit_leaves_no_data_in_postgres(self, pg_engine) -> None:
        """Data added inside a session that is rolled back must not be queryable afterward."""
        from sqlalchemy import select

        from src.models.entities import Article

        unique_link = "https://pg.test/rollback-article"

        # Arrange: open a session, add a row, then roll back without committing.
        rollback_factory = sessionmaker(autocommit=False, autoflush=False, bind=pg_engine)
        session = rollback_factory()
        try:
            article = Article(
                title="Will Be Rolled Back",
                link=unique_link,
                summary="",
                source="rollback-source",
            )
            session.add(article)
            session.flush()
            # Simulate an error before commit
            raise RuntimeError("Simulated pre-commit failure")
        except RuntimeError:
            session.rollback()
        finally:
            session.close()

        # Act: open a fresh session and query for the article.
        verify_session = rollback_factory()
        try:
            result = verify_session.scalar(select(Article).where(Article.link == unique_link))
        finally:
            verify_session.close()

        # Assert: the article must not exist.
        assert result is None


# ---------------------------------------------------------------------------
# Concurrent writes / constraint enforcement test
# ---------------------------------------------------------------------------


class TestConcurrentWritesPostgres:
    """Concurrent inserts with the same unique URL must not corrupt the database."""

    def test_two_sessions_same_url_only_one_row_saved(self, pg_engine) -> None:
        """When two sessions race to insert the same URL, exactly one row is committed.

        The losing session receives an IntegrityError from the PostgreSQL unique
        constraint and must be rolled back.  The winner commits normally.  The
        final row count for that URL must be exactly one.
        """
        from sqlalchemy import select

        from src.models.entities import Article

        race_link = "https://pg.test/concurrent-race"
        factory = sessionmaker(autocommit=False, autoflush=False, bind=pg_engine)

        errors: list[Exception] = []
        commit_results: list[str] = []

        def _insert_and_commit(label: str) -> None:
            session = factory()
            try:
                article = Article(
                    title=f"Race Contestant {label}",
                    link=race_link,
                    summary="",
                    source="race-source",
                )
                session.add(article)
                session.commit()
                commit_results.append(label)
            except IntegrityError:
                session.rollback()
            except Exception as exc:
                errors.append(exc)
                session.rollback()
            finally:
                session.close()

        # Act: run two threads simultaneously.
        t1 = threading.Thread(target=_insert_and_commit, args=("A",))
        t2 = threading.Thread(target=_insert_and_commit, args=("B",))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        # Assert: no unexpected errors occurred.
        assert errors == [], f"Unexpected errors during concurrent insert: {errors}"

        # Assert: exactly one row with the race URL exists.
        verify_session = factory()
        try:
            rows = list(
                verify_session.scalars(select(Article).where(Article.link == race_link)).all()
            )
        finally:
            verify_session.close()

        assert len(rows) == 1, (
            f"Expected exactly 1 row for URL '{race_link}', found {len(rows)}. "
            f"Committed sessions: {commit_results}"
        )

        # Cleanup
        cleanup_session = factory()
        try:
            cleanup_session.execute(delete(Article).where(Article.link == race_link))
            cleanup_session.commit()
        finally:
            cleanup_session.close()
