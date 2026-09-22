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
    # Beats should have emotion and shot_type
    assert "emotion" in roundup_script.beats[0]
    assert "shot_type" in roundup_script.beats[0]

