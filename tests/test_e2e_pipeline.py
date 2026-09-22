"""End-to-end integration tests for the AI News to YouTube Video Pipeline.

Tests the entire lifecycle from article clustering, script generation,
voice synthesis, caption extraction, to Remotion props rendering.
"""

from pathlib import Path

from typer.testing import CliRunner

from src.cli import app
from src.core.database import get_session, init_db
from src.flows.video_pipeline_flow import run_video_pipeline
from src.models.entities import Article, StoryCluster
from src.repositories.article_repository import ArticleRepository
from src.repositories.cost_repository import CostRepository
from src.repositories.render_repository import RenderRepository
from src.repositories.script_repository import ScriptRepository


def seed_sample_story(session) -> StoryCluster:
    """Helper to seed sample articles and a story cluster."""
    import uuid

    uid = uuid.uuid4().hex[:8]
    article1 = Article(
        title="OpenAI Unveils GPT-5 Architecture Details with Reasoning Improvements",
        link=f"https://example.com/openai-gpt5-architecture-{uid}",
        source="TechCrunch AI",
        published_at=None,
        summary=(
            "OpenAI announced structural upgrades to its reasoning model family today. "
            "The release promises lower inference latency and improved coding benchmarks."
        ),
    )
    article2 = Article(
        title="Industry Reacts to OpenAI New Reasoning Benchmarks",
        link=f"https://example.com/industry-reacts-openai-reasoning-{uid}",
        source="VentureBeat",
        published_at=None,
        summary=(
            "Engineers and researchers debate whether the new reasoning benchmarks "
            "represent genuine breakthroughs or synthetic dataset overfitting."
        ),
    )
    session.add_all([article1, article2])
    session.commit()

    cluster = StoryCluster(
        cluster_hash=f"hash_e2e_gpt5_{uid}",
        title="OpenAI Unveils GPT-5 Architecture Details",
        summary=(
            f"[{article1.source}] {article1.title}: {article1.summary}\n"
            f"[{article2.source}] {article2.title}: {article2.summary}"
        ),
        article_ids=[article1.id, article2.id],
        status="pending",
    )
    session.add(cluster)
    session.commit()
    return cluster


def test_e2e_run_video_pipeline_vertical_9_16(tmp_path: Path):
    """E2E Test 1: Full pipeline execution for 9:16 Shorts with dry-run render."""
    init_db()
    with get_session() as session:
        cluster = seed_sample_story(session)
        target_cluster_id = cluster.id

    result = run_video_pipeline(
        cluster_id=target_cluster_id,
        aspect_ratio="9:16",
        dry_run=True,
    )

    assert result["cluster_id"] == str(target_cluster_id)
    assert int(result["script_id"]) > 0
    assert int(result["job_id"]) > 0
    assert "video_job_" in result["video_path"]
    assert "AiNewsVideoVertical" in result["video_path"]

    # Verify database state after run
    with get_session() as session:
        art_repo = ArticleRepository(session)
        updated_cluster = art_repo.get_cluster_by_id(target_cluster_id)
        assert updated_cluster is not None
        assert updated_cluster.status == "completed"

        script_repo = ScriptRepository(session)
        script = script_repo.get_script_by_id(int(result["script_id"]))
        assert script is not None
        assert len(script.full_narration) > 50
        assert script.cluster_id == target_cluster_id

        render_repo = RenderRepository(session)
        job = render_repo.get_job_by_id(int(result["job_id"]))
        assert job is not None
        assert job.aspect_ratio == "9:16"
        assert job.audio_path is not None
        assert job.captions_path is not None
        assert job.duration_seconds is not None
        assert job.duration_seconds > 0

        cost_repo = CostRepository(session)
        total_spend = cost_repo.get_total_spend()
        assert total_spend >= 0.0


def test_e2e_run_video_pipeline_horizontal_16_9():
    """E2E Test 2: Full pipeline execution for 16:9 Widescreen video."""
    init_db()
    with get_session() as session:
        cluster = seed_sample_story(session)
        target_cluster_id = cluster.id

    result = run_video_pipeline(
        cluster_id=target_cluster_id,
        aspect_ratio="16:9",
        dry_run=True,
    )

    assert result["cluster_id"] == str(target_cluster_id)
    assert "AiNewsVideoHorizontal" in result["video_path"]

    with get_session() as session:
        render_repo = RenderRepository(session)
        job = render_repo.get_job_by_id(int(result["job_id"]))
        assert job is not None
        assert job.aspect_ratio == "16:9"


def test_e2e_cli_stage_by_stage_execution():
    """E2E Test 3: CLI stage-by-stage command execution via CliRunner."""
    runner = CliRunner()
    init_db()

    with get_session() as session:
        cluster = seed_sample_story(session)
        cluster_id = cluster.id

    # Stage A: Script generation
    res_script = runner.invoke(app, ["script", "--cluster-id", str(cluster_id)])
    assert res_script.exit_code == 0
    assert "Spoken Narration Script" in res_script.output

    with get_session() as session:
        scripts = ScriptRepository(session).get_scripts_by_cluster(cluster_id)
        assert len(scripts) > 0
        latest_script_id = scripts[0].id

    # Stage B: Voice synthesis & word-level captions
    res_voice = runner.invoke(app, ["voice", "--script-id", str(latest_script_id)])
    assert res_voice.exit_code == 0
    assert "Audio generated" in res_voice.output
    assert "Captions extracted" in res_voice.output

    with get_session() as session:
        jobs = RenderRepository(session).get_jobs_by_script(latest_script_id)
        assert len(jobs) > 0
        job_id = jobs[0].id

    # Stage C: Video rendering (dry-run mode)
    res_render = runner.invoke(app, ["render", "--job-id", str(job_id), "--dry-run"])
    assert res_render.exit_code == 0
    assert "Render completed" in res_render.output

    # Stage D: Costs audit
    res_costs = runner.invoke(app, ["costs"])
    assert res_costs.exit_code == 0
    assert "Pipeline Spend by Stage" in res_costs.output


def test_e2e_local_fastembed_clustering_flow():
    """E2E Test 4: Local fastembed in-process embedding and clustering."""
    init_db()
    with get_session() as session:
        import uuid

        uid = uuid.uuid4().hex[:8]
        a1 = Article(
            title="Local AI Models Achieve Higher Quantization Accuracy",
            link=f"https://example.com/local-ai-quantization-{uid}",
            source="LocalAI Journal",
            published_at=None,
            summary=("New 4-bit and 2-bit quantization techniques retain 98 percent of accuracy."),
        )
        session.add(a1)
        session.commit()
        art_id = a1.id

    runner = CliRunner()
    res_cluster = runner.invoke(app, ["cluster", "--model", "local"])
    assert res_cluster.exit_code == 0
    assert "Generating embeddings using 'local'" in res_cluster.output

    with get_session() as session:
        arts = ArticleRepository(session).get_articles_by_ids([art_id])
        assert len(arts) > 0
        saved_art = arts[0]
        assert saved_art.embedding is not None
        assert len(saved_art.embedding) == 384


def test_e2e_full_pipeline_cli_dry_run():
    """E2E Test 5: End-to-end 'pipeline run' CLI command."""
    init_db()
    with get_session() as session:
        cluster = seed_sample_story(session)
        cluster_id = cluster.id

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--cluster-id",
            str(cluster_id),
            "--dry-run",
            "--aspect-ratio",
            "9:16",
        ],
    )
    assert result.exit_code == 0
    assert "Pipeline Run Completed Successfully" in result.output
    assert f"Cluster ID: {cluster_id}" in result.output


def test_e2e_roundup_and_assets_cli():
    """E2E Test 6: News roundup pipeline and visual asset library CLI commands."""
    import json
    import uuid

    init_db()
    uid = uuid.uuid4().hex[:8]

    with get_session() as session:
        art1 = Article(
            title=f"Roundup Test Story 1 {uid}",
            link=f"https://example.com/roundup-story-1-{uid}",
            source="ArsTechnica",
            summary="Story 1 on frontier AI advancements.",
        )
        art2 = Article(
            title=f"Roundup Test Story 2 {uid}",
            link=f"https://example.com/roundup-story-2-{uid}",
            source="TechCrunch",
            summary="Story 2 on high efficiency neural hardware.",
        )
        session.add_all([art1, art2])
        session.commit()

        c1 = StoryCluster(
            cluster_hash=f"hash_roundup_1_{uid}",
            title=f"Roundup Test Story 1 {uid}",
            summary="Story 1 summary",
            article_ids=[art1.id],
            status="pending",
        )
        c2 = StoryCluster(
            cluster_hash=f"hash_roundup_2_{uid}",
            title=f"Roundup Test Story 2 {uid}",
            summary="Story 2 summary",
            article_ids=[art2.id],
            status="pending",
        )
        session.add_all([c1, c2])
        session.commit()
        c1_id = c1.id
        c2_id = c2.id

    runner = CliRunner()

    # Test 1: Roundup script generation JSON output
    res_script = runner.invoke(
        app,
        ["roundup", "--cluster-ids", f"{c1_id},{c2_id}", "--json"],
    )
    assert res_script.exit_code == 0
    data = json.loads(res_script.output)
    assert data["status"] == "success"
    assert "script_id" in data
    assert data["beats_count"] > 0

    # Test 2: Full roundup pipeline dry-run
    res_pipeline = runner.invoke(
        app,
        [
            "roundup",
            "--cluster-ids",
            f"{c1_id},{c2_id}",
            "--run",
            "--dry-run",
            "--json",
        ],
    )
    assert res_pipeline.exit_code == 0
    pipe_data = json.loads(res_pipeline.output)
    assert pipe_data["status"] == "success"
    assert "video_path" in pipe_data

    # Test 3: Assets CLI command
    res_assets = runner.invoke(app, ["assets"])
    assert res_assets.exit_code == 0
