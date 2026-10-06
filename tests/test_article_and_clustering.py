"""Unit tests for article storage and story clustering."""

from src.models.schemas import FeedItem
from src.repositories.article_repository import ArticleRepository
from src.repositories.cost_repository import CostRepository
from src.repositories.script_repository import ScriptRepository
from src.services.clustering_service import ClusteringService
from src.services.script_service import ScriptService


def test_save_feed_items_deduplication(article_repo: ArticleRepository):
    items = [
        FeedItem(
            title="Claude 3.5 Sonnet Released",
            link="https://news.com/claude",
            summary="New reasoning benchmark leader.",
            source="TechCrunch",
        ),
        FeedItem(
            title="Claude 3.5 Sonnet Released",
            link="https://news.com/claude",  # Duplicate link
            summary="Duplicate summary.",
            source="TechCrunch",
        ),
        FeedItem(
            title="Llama 3 405B Available",
            link="https://news.com/llama3",
            summary="Meta open weights flagship.",
            source="VentureBeat",
        ),
    ]

    saved = article_repo.save_feed_items(items)
    assert len(saved) == 2

    # Verify querying unembedded articles
    unembedded = article_repo.get_articles_without_embeddings()
    assert len(unembedded) == 2


def test_clustering_similar_articles(
    article_repo: ArticleRepository,
    cost_repo: CostRepository,
):
    items = [
        FeedItem(
            title="DeepSeek V3 Released",
            link="https://news.com/deepseek-1",
            summary="DeepSeek releases open source MoE architecture.",
            source="SourceA",
        ),
        FeedItem(
            title="DeepSeek V3 Architecture Deep Dive",
            link="https://news.com/deepseek-2",
            summary="Analyzing the MoE design of DeepSeek V3.",
            source="SourceB",
        ),
        FeedItem(
            title="Quantum Computing Quantum Supremacy Claim",
            link="https://news.com/quantum",
            summary="Physicists claim quantum milestone.",
            source="SourceC",
        ),
    ]
    saved = article_repo.save_feed_items(items)

    # Assign synthetic embeddings where DeepSeek articles are close and quantum is orthogonal
    vec_deepseek_1 = [0.9, 0.1, 0.0] + [0.0] * 1533
    vec_deepseek_2 = [0.88, 0.12, 0.0] + [0.0] * 1533
    vec_quantum = [0.0, 0.0, 1.0] + [0.0] * 1533

    article_repo.update_article_embedding(saved[0].id, vec_deepseek_1)
    article_repo.update_article_embedding(saved[1].id, vec_deepseek_2)
    article_repo.update_article_embedding(saved[2].id, vec_quantum)

    clustering_service = ClusteringService(article_repo, cost_repo)
    clusters = clustering_service.cluster_recent_articles(threshold=0.85)

    assert len(clusters) == 2
    # The largest cluster should contain the 2 DeepSeek articles
    assert clusters[0].article_count == 2
    assert clusters[1].article_count == 1


def test_generate_roundup_script(
    article_repo: ArticleRepository,
    script_repo: ScriptRepository,
    cost_repo: CostRepository,
):
    """Verify multi-cluster roundup script generation gathers top stories and formats beats."""
    items = [
        FeedItem(
            title="OpenAI Releases O3 Model",
            link="https://news.com/o3",
            summary="OpenAI launches new reasoning model O3 with benchmark wins.",
            source="TechCrunch",
        ),
        FeedItem(
            title="Anthropic Launches Claude 3.7",
            link="https://news.com/claude37",
            summary="Anthropic announces hybrid reasoning architecture Claude 3.7 Sonnet.",
            source="VentureBeat",
        ),
    ]
    saved = article_repo.save_feed_items(items)

    cluster1 = article_repo.save_story_cluster(
        cluster_hash="hash_o3_story",
        title="OpenAI Releases O3 Model",
        summary="O3 reasoning release details.",
        article_ids=[saved[0].id],
    )
    cluster2 = article_repo.save_story_cluster(
        cluster_hash="hash_claude_story",
        title="Anthropic Launches Claude 3.7",
        summary="Claude 3.7 hybrid reasoning details.",
        article_ids=[saved[1].id],
    )

    script_service = ScriptService(
        article_repo=article_repo,
        script_repo=script_repo,
        cost_repo=cost_repo,
    )

    roundup_script = script_service.generate_roundup_script(
        cluster_ids=[cluster1.id, cluster2.id],
        aspect_ratio="9:16",
    )

    assert roundup_script is not None
    assert "Roundup" in roundup_script.title
    assert len(roundup_script.beats) >= 4
    assert len(roundup_script.full_narration) > 50
    assert "shot_type" in roundup_script.beats[0]


def test_cluster_run_id_and_index_assignment(
    article_repo: ArticleRepository,
    cost_repo: CostRepository,
):
    """Verify cluster_run_id and 1-indexed run_cluster_index are recorded on clusters."""
    items = [
        FeedItem(
            title="AI Model A Released",
            link="https://news.com/model-a",
            summary="Summary A",
            source="SourceA",
        ),
        FeedItem(
            title="AI Model B Released",
            link="https://news.com/model-b",
            summary="Summary B",
            source="SourceB",
        ),
    ]
    saved = article_repo.save_feed_items(items)

    vec_a = [0.9, 0.1, 0.0] + [0.0] * 1533
    vec_b = [0.0, 0.0, 1.0] + [0.0] * 1533
    article_repo.update_article_embedding(saved[0].id, vec_a)
    article_repo.update_article_embedding(saved[1].id, vec_b)

    service = ClusteringService(article_repo, cost_repo)
    custom_run = "run_20261006_custom_test"
    clusters = service.cluster_recent_articles(threshold=0.85, cluster_run_id=custom_run)

    assert service.last_run_id == custom_run
    assert len(clusters) == 2
    for idx, c in enumerate(clusters, start=1):
        assert c.cluster_run_id == custom_run
        assert c.run_cluster_index == idx

    # Verify cluster run metadata
    run_record = article_repo.get_cluster_run(custom_run)
    assert run_record is not None
    assert run_record.run_id == custom_run
    assert run_record.cluster_count == 2
    assert run_record.article_count == 2

    runs_list = article_repo.list_cluster_runs()
    assert any(r["run_id"] == custom_run for r in runs_list)


def test_clustering_with_specific_article_ids(
    article_repo: ArticleRepository,
    cost_repo: CostRepository,
):
    """Verify clustering only clusters the requested article_ids when provided."""
    items = [
        FeedItem(
            title="Selected Article 1",
            link="https://news.com/sel-1",
            summary="Summary 1",
            source="Source1",
        ),
        FeedItem(
            title="Selected Article 2",
            link="https://news.com/sel-2",
            summary="Summary 2",
            source="Source2",
        ),
        FeedItem(
            title="Unselected Article 3",
            link="https://news.com/unsel-3",
            summary="Summary 3",
            source="Source3",
        ),
    ]
    saved = article_repo.save_feed_items(items)

    vec_same = [0.95, 0.05, 0.0] + [0.0] * 1533
    for art in saved:
        article_repo.update_article_embedding(art.id, vec_same)

    service = ClusteringService(article_repo, cost_repo)
    target_ids = [saved[0].id, saved[1].id]
    clusters = service.cluster_recent_articles(article_ids=target_ids, threshold=0.85)

    assert len(clusters) == 1
    assert clusters[0].article_count == 2
    cluster_obj = article_repo.get_cluster_by_id(clusters[0].id)
    assert cluster_obj is not None
    cluster_art_ids = cluster_obj.article_ids
    assert saved[0].id in cluster_art_ids
    assert saved[1].id in cluster_art_ids
    assert saved[2].id not in cluster_art_ids


def test_get_articles_and_cluster_run_filtering(
    article_repo: ArticleRepository,
):
    """Verify article_repo.get_articles filtering and paginated cluster filtering by run_id."""
    items = [
        FeedItem(
            title="Searchable Keyword Robotics",
            link="https://news.com/robotics",
            summary="Robots in AI",
            source="TechSpecial",
        ),
        FeedItem(
            title="Standard AI News",
            link="https://news.com/standard",
            summary="Standard news",
            source="OtherSource",
        ),
    ]
    saved = article_repo.save_feed_items(items)

    # Search filter
    searched = article_repo.get_articles(search="Robotics")
    assert any(a.id == saved[0].id for a in searched)
    assert not any(a.id == saved[1].id for a in searched)

    # Source filter
    by_source = article_repo.get_articles(source="TechSpecial")
    assert any(a.id == saved[0].id for a in by_source)
    assert not any(a.id == saved[1].id for a in by_source)

    # Cluster run filtering
    cluster_a = article_repo.save_story_cluster(
        cluster_hash="run_test_a:1",
        title="Cluster in Run A",
        summary="Summary A",
        article_ids=[saved[0].id],
        cluster_run_id="run_filter_a",
        run_cluster_index=1,
    )
    cluster_b = article_repo.save_story_cluster(
        cluster_hash="run_test_b:2",
        title="Cluster in Run B",
        summary="Summary B",
        article_ids=[saved[1].id],
        cluster_run_id="run_filter_b",
        run_cluster_index=1,
    )

    clusters_a, _ = article_repo.list_story_clusters_paginated(cluster_run_id="run_filter_a")
    assert any(c.id == cluster_a.id for c in clusters_a)
    assert not any(c.id == cluster_b.id for c in clusters_a)

    clusters_b, _ = article_repo.list_story_clusters_paginated(cluster_run_id="run_filter_b")
    assert any(c.id == cluster_b.id for c in clusters_b)
    assert not any(c.id == cluster_a.id for c in clusters_b)


def test_article_repository_uncapped_limits(article_repo: ArticleRepository) -> None:
    """Verify that get_articles, get_articles_without_embeddings,
    and get_all_embedded_articles return all items when limit is None.
    """
    items = [
        FeedItem(
            title=f"Bulk Article {i}",
            link=f"https://news.com/bulk/{i}",
            summary=f"Bulk article summary {i}",
            source="BulkSource",
        )
        for i in range(10)
    ]
    saved = article_repo.save_feed_items(items)
    assert len(saved) == 10

    # Test get_articles with limit=None
    all_articles = article_repo.get_articles(limit=None, source="BulkSource")
    assert len(all_articles) == 10

    # Test get_articles with limit=3
    limited_articles = article_repo.get_articles(limit=3, source="BulkSource")
    assert len(limited_articles) == 3

    # Test get_articles_without_embeddings with limit=None
    all_unembedded = article_repo.get_articles_without_embeddings(limit=None)
    bulk_unembedded = [a for a in all_unembedded if a.source == "BulkSource"]
    assert len(bulk_unembedded) == 10

    # Test get_articles_without_embeddings with limit=2
    limited_unembedded = article_repo.get_articles_without_embeddings(limit=2)
    assert len(limited_unembedded) == 2

    # Embed 5 articles
    for a in saved[:5]:
        article_repo.update_article_embedding(a.id, [0.1] * 10)

    # Test get_all_embedded_articles with limit=None
    embedded_all = article_repo.get_all_embedded_articles(limit=None)
    bulk_embedded = [a for a in embedded_all if a.source == "BulkSource"]
    assert len(bulk_embedded) == 5

    # Test get_all_embedded_articles with limit=2
    embedded_limited = article_repo.get_all_embedded_articles(limit=2)
    assert len(embedded_limited) == 2
