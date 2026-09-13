"""Unit tests for article storage and story clustering."""

from src.models.schemas import FeedItem
from src.repositories.article_repository import ArticleRepository
from src.repositories.cost_repository import CostRepository
from src.services.clustering_service import ClusteringService


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
