"""Tests for ArticleRepository in src/repositories/article_repository.py.

Covers:
- save_feed_items: new article creation, intra-call deduplication (seen_links),
  DB-level duplicate skipping, empty list, items with no link.
- get_articles_without_embeddings: filters to embedding=None only.
- update_article_embedding: assigns embedding, handles missing id gracefully.
- get_all_embedded_articles: filters to non-None embeddings only.
- save_story_cluster: create path, upsert path (existing cluster_hash).
- count_articles: accurate total.
- count_story_clusters: total, status filter, search filter.
- list_story_clusters_paginated: page 1, page 2, status filter.
- list_story_clusters: status filter.
- get_cluster_by_id: found, not found.
- get_articles_by_ids: subset retrieval, empty list input.
- update_cluster_status: mutates status, handles missing id gracefully.
- get_trending_clusters: sorted by velocity, hours_back exclusion.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

from src.models.entities import Article, StoryCluster
from src.models.schemas import FeedItem
from src.repositories.article_repository import ArticleRepository

# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------


def _feed_item(
    title: str = "Test Article",
    link: str = "https://example.com/article",
    summary: str = "A summary.",
    source: str = "TestSource",
    published_at: datetime | None = None,
) -> FeedItem:
    """Build a FeedItem for use in save_feed_items calls."""
    return FeedItem(
        title=title,
        link=link,
        summary=summary,
        source=source,
        published_at=published_at,
    )


def _article(
    db_session: Session,
    title: str = "DB Article",
    link: str = "https://example.com/db-article",
    summary: str = "Summary.",
    source: str = "DBSource",
    embedding: list[float] | None = None,
    created_at: datetime | None = None,
) -> Article:
    kwargs: dict[str, Any] = {
        "title": title,
        "link": link,
        "summary": summary,
        "source": source,
        "created_at": created_at or datetime.now(UTC),
    }
    if embedding is not None:
        kwargs["embedding"] = embedding
    article = Article(**kwargs)
    db_session.add(article)
    db_session.flush()
    return article


def _cluster(
    db_session: Session,
    cluster_hash: str = "abc123",
    title: str = "Cluster Title",
    summary: str = "Cluster summary.",
    article_ids: list[int] | None = None,
    status: str = "pending",
    created_at: datetime | None = None,
) -> StoryCluster:
    """Insert and flush a StoryCluster entity directly into the test DB."""
    ids = article_ids or []
    sc = StoryCluster(
        cluster_hash=cluster_hash,
        title=title,
        summary=summary,
        article_ids=ids,
        article_count=len(ids),
        status=status,
        created_at=created_at or datetime.now(UTC),
    )
    db_session.add(sc)
    db_session.flush()
    return sc


# ---------------------------------------------------------------------------
# save_feed_items
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_save_feed_items_saves_new_articles_returns_them(
    article_repo: ArticleRepository,
) -> None:
    items = [
        _feed_item(title="Article One", link="https://example.com/one"),
        _feed_item(title="Article Two", link="https://example.com/two"),
    ]

    result = article_repo.save_feed_items(items)

    assert len(result) == 2
    assert {a.title for a in result} == {"Article One", "Article Two"}


@pytest.mark.unit
def test_save_feed_items_skips_duplicate_links_within_same_call(
    article_repo: ArticleRepository,
) -> None:
    items = [
        _feed_item(title="Article A", link="https://example.com/dup"),
        _feed_item(title="Article A copy", link="https://example.com/dup"),
    ]

    result = article_repo.save_feed_items(items)

    assert len(result) == 1
    assert result[0].title == "Article A"


@pytest.mark.unit
def test_save_feed_items_skips_url_already_in_db(
    article_repo: ArticleRepository,
    db_session: Session,
) -> None:
    existing_link = "https://example.com/existing"
    _article(db_session, link=existing_link)
    item = _feed_item(title="Duplicate", link=existing_link)

    result = article_repo.save_feed_items([item])

    assert result == []


@pytest.mark.unit
def test_save_feed_items_with_empty_list_returns_empty(
    article_repo: ArticleRepository,
) -> None:
    result = article_repo.save_feed_items([])

    assert result == []


@pytest.mark.unit
def test_save_feed_items_with_no_link_skips_item(
    article_repo: ArticleRepository,
) -> None:
    # FeedItem enforces min_length=5, so we bypass with a direct object
    # and rely on the repository's own guard (item.link falsy).
    # We construct a FeedItem-like object that has an empty link.
    class _Bare:
        title = "No Link"
        link = ""
        summary = ""
        source = "S"
        published_at = None

    result = article_repo.save_feed_items([_Bare()])  # type: ignore[list-item]

    assert result == []


# ---------------------------------------------------------------------------
# get_articles_without_embeddings
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_articles_without_embeddings_returns_only_null_embedding_articles(
    article_repo: ArticleRepository,
    db_session: Session,
) -> None:
    _article(db_session, link="https://example.com/no-emb", embedding=None)
    _article(db_session, link="https://example.com/has-emb", embedding=[0.1, 0.2])

    result = article_repo.get_articles_without_embeddings()

    assert all(a.embedding is None for a in result)
    assert any(a.link == "https://example.com/no-emb" for a in result)


@pytest.mark.unit
def test_get_articles_without_embeddings_excludes_embedded_articles(
    article_repo: ArticleRepository,
    db_session: Session,
) -> None:
    _article(db_session, link="https://example.com/emb-only", embedding=[0.5])

    result = article_repo.get_articles_without_embeddings()

    assert result == []


# ---------------------------------------------------------------------------
# update_article_embedding
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_update_article_embedding_assigns_embedding_to_article(
    article_repo: ArticleRepository,
    db_session: Session,
) -> None:
    a = _article(db_session, link="https://example.com/to-embed", embedding=None)
    vec = [0.1, 0.2, 0.3]

    article_repo.update_article_embedding(a.id, vec)

    db_session.refresh(a)
    assert a.embedding == vec


@pytest.mark.unit
def test_update_article_embedding_with_non_existent_id_does_not_raise(
    article_repo: ArticleRepository,
) -> None:
    article_repo.update_article_embedding(999_999, [0.1, 0.2])


# ---------------------------------------------------------------------------
# get_all_embedded_articles
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_all_embedded_articles_returns_only_articles_with_embeddings(
    article_repo: ArticleRepository,
    db_session: Session,
) -> None:
    _article(db_session, link="https://example.com/no-vec", embedding=None)
    _article(db_session, link="https://example.com/has-vec", embedding=[1.0, 2.0])

    result = article_repo.get_all_embedded_articles()

    assert all(a.embedding is not None for a in result)
    assert any(a.link == "https://example.com/has-vec" for a in result)


# ---------------------------------------------------------------------------
# save_story_cluster
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_save_story_cluster_creates_new_cluster(
    article_repo: ArticleRepository,
    db_session: Session,
) -> None:
    result = article_repo.save_story_cluster(
        cluster_hash="hash001",
        title="AI Boom",
        summary="Summary of AI boom.",
        article_ids=[1, 2, 3],
    )

    assert result.id is not None
    assert result.cluster_hash == "hash001"
    assert result.article_count == 3
    assert result.status == "pending"


@pytest.mark.unit
def test_save_story_cluster_upserts_existing_cluster_by_hash(
    article_repo: ArticleRepository,
    db_session: Session,
) -> None:
    first = article_repo.save_story_cluster(
        cluster_hash="upsert-hash",
        title="Old Title",
        summary="Old summary.",
        article_ids=[1],
    )
    first_id = first.id

    updated = article_repo.save_story_cluster(
        cluster_hash="upsert-hash",
        title="New Title",
        summary="New summary.",
        article_ids=[1, 2, 3, 4],
    )

    assert updated.id == first_id
    assert updated.title == "New Title"
    assert updated.article_count == 4


# ---------------------------------------------------------------------------
# count_articles
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_count_articles_returns_correct_total(
    article_repo: ArticleRepository,
    db_session: Session,
) -> None:
    _article(db_session, link="https://example.com/c1")
    _article(db_session, link="https://example.com/c2")

    count = article_repo.count_articles()

    assert count == 2


# ---------------------------------------------------------------------------
# count_story_clusters
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_count_story_clusters_returns_correct_total(
    article_repo: ArticleRepository,
    db_session: Session,
) -> None:
    _cluster(db_session, cluster_hash="cnt1")
    _cluster(db_session, cluster_hash="cnt2")

    count = article_repo.count_story_clusters()

    assert count == 2


@pytest.mark.unit
def test_count_story_clusters_with_status_filter(
    article_repo: ArticleRepository,
    db_session: Session,
) -> None:
    _cluster(db_session, cluster_hash="done1", status="done")
    _cluster(db_session, cluster_hash="pend1", status="pending")
    _cluster(db_session, cluster_hash="pend2", status="pending")

    count = article_repo.count_story_clusters(status="pending")

    assert count == 2


@pytest.mark.unit
def test_count_story_clusters_with_search_filter(
    article_repo: ArticleRepository,
    db_session: Session,
) -> None:
    _cluster(db_session, cluster_hash="srch1", title="OpenAI GPT-5 Released")
    _cluster(db_session, cluster_hash="srch2", title="Google DeepMind Wins Award")

    count = article_repo.count_story_clusters(search="GPT")

    assert count == 1


# ---------------------------------------------------------------------------
# list_story_clusters_paginated
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_list_story_clusters_paginated_returns_correct_page_and_total(
    article_repo: ArticleRepository,
    db_session: Session,
) -> None:
    for i in range(5):
        _cluster(db_session, cluster_hash=f"pg-{i}", title=f"Cluster {i}")

    items, total = article_repo.list_story_clusters_paginated(page=1, page_size=3)

    assert total == 5
    assert len(items) == 3


@pytest.mark.unit
def test_list_story_clusters_paginated_page_2_returns_remaining_items(
    article_repo: ArticleRepository,
    db_session: Session,
) -> None:
    for i in range(5):
        _cluster(db_session, cluster_hash=f"pg2-{i}", title=f"Cluster {i}")

    items, total = article_repo.list_story_clusters_paginated(page=2, page_size=3)

    assert total == 5
    assert len(items) == 2


@pytest.mark.unit
def test_list_story_clusters_paginated_with_status_filter(
    article_repo: ArticleRepository,
    db_session: Session,
) -> None:
    _cluster(db_session, cluster_hash="pf1", status="pending")
    _cluster(db_session, cluster_hash="pf2", status="done")
    _cluster(db_session, cluster_hash="pf3", status="done")

    items, total = article_repo.list_story_clusters_paginated(status="done", page=1, page_size=10)

    assert total == 2
    assert all(c.status == "done" for c in items)


# ---------------------------------------------------------------------------
# list_story_clusters
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_list_story_clusters_with_status_filter_returns_matching_clusters(
    article_repo: ArticleRepository,
    db_session: Session,
) -> None:
    _cluster(db_session, cluster_hash="lst1", status="pending")
    _cluster(db_session, cluster_hash="lst2", status="done")

    result = article_repo.list_story_clusters(status="pending")

    assert len(result) == 1
    assert result[0].status == "pending"


# ---------------------------------------------------------------------------
# get_cluster_by_id
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_cluster_by_id_returns_correct_cluster(
    article_repo: ArticleRepository,
    db_session: Session,
) -> None:
    sc = _cluster(db_session, cluster_hash="byid1", title="Find Me")

    result = article_repo.get_cluster_by_id(sc.id)

    assert result is not None
    assert result.title == "Find Me"


@pytest.mark.unit
def test_get_cluster_by_id_returns_none_for_missing_id(
    article_repo: ArticleRepository,
) -> None:
    result = article_repo.get_cluster_by_id(999_999)

    assert result is None


# ---------------------------------------------------------------------------
# get_articles_by_ids
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_articles_by_ids_returns_correct_articles(
    article_repo: ArticleRepository,
    db_session: Session,
) -> None:
    a1 = _article(db_session, link="https://example.com/ids-1")
    a2 = _article(db_session, link="https://example.com/ids-2")
    _article(db_session, link="https://example.com/ids-3")

    result = article_repo.get_articles_by_ids([a1.id, a2.id])

    assert len(result) == 2
    assert {a.id for a in result} == {a1.id, a2.id}


@pytest.mark.unit
def test_get_articles_by_ids_with_empty_list_returns_empty(
    article_repo: ArticleRepository,
) -> None:
    result = article_repo.get_articles_by_ids([])

    assert result == []


# ---------------------------------------------------------------------------
# update_cluster_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_update_cluster_status_updates_status_correctly(
    article_repo: ArticleRepository,
    db_session: Session,
) -> None:
    sc = _cluster(db_session, cluster_hash="upd-status", status="pending")

    article_repo.update_cluster_status(sc.id, "done")

    db_session.refresh(sc)
    assert sc.status == "done"


@pytest.mark.unit
def test_update_cluster_status_with_non_existent_id_does_not_raise(
    article_repo: ArticleRepository,
) -> None:
    article_repo.update_cluster_status(999_999, "done")


# ---------------------------------------------------------------------------
# get_trending_clusters
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_trending_clusters_returns_sorted_by_velocity_score(
    article_repo: ArticleRepository,
    db_session: Session,
) -> None:
    now = datetime.now(UTC)

    a_small = _article(db_session, link="https://example.com/sm", source="S1")
    a_big1 = _article(db_session, link="https://example.com/bg1", source="S1")
    a_big2 = _article(db_session, link="https://example.com/bg2", source="S2")
    a_big3 = _article(db_session, link="https://example.com/bg3", source="S3")

    _cluster(
        db_session,
        cluster_hash="small-cluster",
        article_ids=[a_small.id],
        status="pending",
        created_at=now - timedelta(hours=1),
    )
    _cluster(
        db_session,
        cluster_hash="big-cluster",
        article_ids=[a_big1.id, a_big2.id, a_big3.id],
        status="pending",
        created_at=now - timedelta(hours=1),
    )

    result = article_repo.get_trending_clusters(limit=10, hours_back=72)

    assert len(result) >= 1
    scores = [score for _, score in result]
    assert scores == sorted(scores, reverse=True), "Clusters must be sorted descending by score"


@pytest.mark.unit
def test_get_trending_clusters_excludes_clusters_older_than_hours_back(
    article_repo: ArticleRepository,
    db_session: Session,
) -> None:
    now = datetime.now(UTC)

    old_article = _article(db_session, link="https://example.com/old-art")
    recent_article = _article(db_session, link="https://example.com/recent-art")

    _cluster(
        db_session,
        cluster_hash="old-cluster",
        title="Old News",
        article_ids=[old_article.id],
        status="pending",
        created_at=now - timedelta(hours=100),
    )
    _cluster(
        db_session,
        cluster_hash="recent-cluster",
        title="Fresh News",
        article_ids=[recent_article.id],
        status="pending",
        created_at=now - timedelta(hours=1),
    )

    result = article_repo.get_trending_clusters(limit=10, hours_back=48)

    titles = [c.title for c, _ in result]
    assert "Old News" not in titles
    assert "Fresh News" in titles


@pytest.mark.unit
def test_update_article_embeddings_batch_empty(
    article_repo: ArticleRepository,
) -> None:
    """Batch update with empty input returns 0 and does not error."""
    assert article_repo.update_article_embeddings_batch({}) == 0
    assert article_repo.update_article_embeddings_batch([]) == 0


@pytest.mark.unit
def test_update_article_embeddings_batch_multiple(
    article_repo: ArticleRepository,
    db_session: Session,
) -> None:
    """Batch update correctly sets embeddings across multiple chunks."""
    art1 = _article(db_session, link="https://example.com/batch-1")
    art2 = _article(db_session, link="https://example.com/batch-2")
    art3 = _article(db_session, link="https://example.com/batch-3")

    updates = {
        art1.id: [0.1, 0.2, 0.3],
        art2.id: [0.4, 0.5, 0.6],
        art3.id: [0.7, 0.8, 0.9],
    }

    count = article_repo.update_article_embeddings_batch(
        updates,
        batch_size=2,
        commit_batches=False,
    )
    assert count == 3

    assert art1.embedding == [0.1, 0.2, 0.3]
    assert art2.embedding == [0.4, 0.5, 0.6]
    assert art3.embedding == [0.7, 0.8, 0.9]
