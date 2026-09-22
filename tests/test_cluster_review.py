"""Tests for ClusterReviewService, interactive selection,
timeout fallback, and multi-cluster scripting.
"""

from unittest.mock import patch

from rich.table import Table

from src.flows.video_pipeline_flow import run_video_pipeline
from src.models.entities import Article, StoryCluster
from src.services.cluster_review_service import ClusterReviewService
from src.services.script_service import ScriptService


def create_sample_clusters(session, count: int = 3) -> list[StoryCluster]:
    """Helper to seed sample articles and clusters in test database."""
    clusters = []
    for i in range(1, count + 1):
        art = Article(
            title=f"Breakthrough in AI System Architecture Part {i}",
            link=f"https://example.com/ai-news-story-{i}",
            source="TechCrunch AI",
            summary=f"Technical details and benchmark results regarding architecture update {i}.",
        )
        session.add(art)
        session.flush()

        cluster = StoryCluster(
            cluster_hash=f"hash_sample_cluster_{i}",
            title=f"Major AI Announcement {i}",
            summary=f"Summary of key insights and technical facts for story {i}.",
            article_ids=[art.id],
            article_count=1,
            status="pending",
        )
        session.add(cluster)
        session.flush()
        clusters.append(cluster)
    session.commit()
    return clusters


def test_render_clusters_table(db_session):
    """Test that render_clusters_table generates a formatted table with cluster details."""
    clusters = create_sample_clusters(db_session, count=2)
    service = ClusterReviewService()
    table = service.render_clusters_table(clusters)

    assert isinstance(table, Table)
    assert table.title == "Available AI Story Clusters"
    assert len(table.rows) == 2


def test_non_interactive_fallback(db_session, action_repo):
    """Non-interactive environment should immediately return default top cluster."""
    clusters = create_sample_clusters(db_session, count=3)
    service = ClusterReviewService()

    chosen = service.prompt_cluster_selection(
        clusters=clusters,
        default_id=clusters[0].id,
        is_interactive=False,
        action_repo=action_repo,
    )

    assert chosen == [clusters[0].id]


def test_interactive_user_multi_selection(db_session, action_repo):
    """User entering comma-separated cluster IDs should return parsed IDs."""
    clusters = create_sample_clusters(db_session, count=4)
    service = ClusterReviewService()

    cid1 = clusters[0].id
    cid3 = clusters[2].id

    with patch.object(service, "_read_stdin_with_timeout", return_value=f"{cid1}, {cid3}\n"):
        chosen = service.prompt_cluster_selection(
            clusters=clusters,
            is_interactive=True,
            action_repo=action_repo,
        )

    assert chosen == [cid1, cid3]


def test_interactive_default_on_enter(db_session, action_repo):
    """Pressing Enter without input should select default top cluster."""
    clusters = create_sample_clusters(db_session, count=3)
    service = ClusterReviewService()

    default_id = clusters[0].id
    with patch.object(service, "_read_stdin_with_timeout", return_value="\n"):
        chosen = service.prompt_cluster_selection(
            clusters=clusters,
            default_id=default_id,
            is_interactive=True,
            action_repo=action_repo,
        )

    assert chosen == [default_id]


def test_interactive_timeout_fallback(db_session, action_repo):
    """Timeout expiring with no input (None) should trigger fallback to default cluster."""
    clusters = create_sample_clusters(db_session, count=3)
    service = ClusterReviewService()

    default_id = clusters[0].id
    with patch.object(service, "_read_stdin_with_timeout", return_value=None):
        chosen = service.prompt_cluster_selection(
            clusters=clusters,
            timeout_seconds=5.0,
            default_id=default_id,
            is_interactive=True,
            action_repo=action_repo,
        )

    assert chosen == [default_id]

    logs = action_repo.get_recent_logs(limit=5)
    timeout_logs = [entry for entry in logs if entry.action == "cluster_review_timeout_fallback"]
    assert len(timeout_logs) > 0
    assert timeout_logs[0].status == "fallback"


def test_interactive_invalid_input_fallback(db_session, action_repo):
    """Invalid or nonexistent cluster IDs should fallback to default cluster."""
    clusters = create_sample_clusters(db_session, count=3)
    service = ClusterReviewService()

    default_id = clusters[0].id
    with patch.object(service, "_read_stdin_with_timeout", return_value="99999, invalid\n"):
        chosen = service.prompt_cluster_selection(
            clusters=clusters,
            default_id=default_id,
            is_interactive=True,
            action_repo=action_repo,
        )

    assert chosen == [default_id]


def test_script_service_multi_cluster_roundup(db_session, article_repo, script_repo, cost_repo):
    """Test ScriptService.generate_roundup_script sorts cluster IDs numerically."""
    clusters = create_sample_clusters(db_session, count=3)
    # Pass IDs intentionally in reverse order
    target_ids = [clusters[2].id, clusters[0].id]
    sorted_expected = sorted(target_ids)

    service = ScriptService(
        article_repo=article_repo,
        script_repo=script_repo,
        cost_repo=cost_repo,
    )

    record = service.generate_roundup_script(
        cluster_ids=target_ids,
        aspect_ratio="9:16",
    )

    assert record.id is not None
    # Verifies strict numerical ascending order of cluster IDs
    assert record.cluster_id == sorted_expected[0]
    assert record.cluster_ids == sorted_expected

    # Verifies sequential beats structure: Hook + 2 Stories + Outro = 4 beats
    assert len(record.beats) == len(target_ids) + 2
    assert record.beats[0]["beat_type"] == "hook"
    assert f"#{sorted_expected[0]}" in record.beats[1]["on_screen_text"]
    assert f"#{sorted_expected[1]}" in record.beats[2]["on_screen_text"]
    assert record.beats[3]["beat_type"] == "outro"

    # Verifies dedicated uncompressed timing per story (at least 18s each)
    assert record.beats[1]["target_duration_seconds"] >= 18.0
    assert record.beats[2]["target_duration_seconds"] >= 18.0
    assert len(record.full_narration) > 40


def test_run_video_pipeline_multi_cluster_dry_run():
    """Test run_video_pipeline with multiple cluster IDs in dry-run mode."""
    import uuid

    from src.core.database import get_session, init_db

    init_db()
    uid = uuid.uuid4().hex[:6]
    with get_session() as session:
        art1 = Article(
            title=f"Breakthrough in AI System Architecture {uid}",
            link=f"https://example.com/ai-news-story-1-{uid}",
            source="TechCrunch AI",
            summary="Technical details and benchmark results.",
        )
        art2 = Article(
            title=f"Next Gen AI System Architecture {uid}",
            link=f"https://example.com/ai-news-story-2-{uid}",
            source="VentureBeat",
            summary="Next-generation benchmarks.",
        )
        session.add_all([art1, art2])
        session.flush()

        cluster1 = StoryCluster(
            cluster_hash=f"hash_sample_c1_{uid}",
            title=f"Major AI Announcement 1 {uid}",
            summary="Summary of key insights and technical facts 1.",
            article_ids=[art1.id],
            article_count=1,
            status="pending",
        )
        cluster2 = StoryCluster(
            cluster_hash=f"hash_sample_c2_{uid}",
            title=f"Major AI Announcement 2 {uid}",
            summary="Summary of key insights and technical facts 2.",
            article_ids=[art2.id],
            article_count=1,
            status="pending",
        )
        session.add_all([cluster1, cluster2])
        session.commit()
        target_ids = [cluster1.id, cluster2.id]

    result = run_video_pipeline(
        cluster_ids=target_ids,
        aspect_ratio="9:16",
        dry_run=True,
    )

    assert "cluster_ids" in result
    assert result["cluster_ids"] == [str(cid) for cid in target_ids]
    assert int(result["script_id"]) > 0
    assert int(result["job_id"]) > 0
    assert "video_job_" in result["video_path"]
