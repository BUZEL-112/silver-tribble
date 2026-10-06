"""Tests for redesigned CLI interfaces and presentation commands."""

import json
import uuid
from unittest.mock import patch

from typer.testing import CliRunner

from src.cli import app
from src.core.database import get_session, init_db
from src.models.entities import Article, ScriptRecord, StoryCluster
from src.models.schemas import WordCaption, YouTubeUploadResult
from src.repositories.render_repository import RenderRepository

runner = CliRunner()


def test_cli_banner_command() -> None:
    """Verify studio ASCII banner command outputs stylized header."""
    res = runner.invoke(app, ["banner"])
    assert res.exit_code == 0
    assert "AI VIDEO STUDIO" in res.stdout
    assert "AUTONOMOUS YOUTUBE PRODUCTION" in res.stdout


def test_cli_trending_command_table_and_json() -> None:
    """Verify trending command produces structured table and json output."""
    init_db()
    uid = uuid.uuid4().hex[:8]
    with get_session() as session:
        art = Article(
            title=f"Trending CLI Verification Story {uid}",
            link=f"https://example.com/trending-cli-test-{uid}",
            source="TechBench",
            summary="Testing trending CLI velocity ranking.",
        )
        session.add(art)
        session.flush()

        cluster = StoryCluster(
            cluster_hash=f"hash_trending_cli_test_{uid}",
            title=f"Trending CLI Verification Story {uid}",
            summary="Story summary for trending test.",
            article_ids=[art.id],
            article_count=5,
            status="pending",
        )
        session.add(cluster)
        session.commit()

    # Table output
    res_table = runner.invoke(app, ["trending", "--limit", "5"])
    assert res_table.exit_code == 0
    assert "Trending Story Clusters" in res_table.stdout

    # JSON output
    res_json = runner.invoke(app, ["trending", "--limit", "5", "--json"])
    assert res_json.exit_code == 0
    parsed = json.loads(res_json.stdout)
    assert isinstance(parsed, list)
    assert len(parsed) >= 1
    assert "score" in parsed[0]
    assert "article_count" in parsed[0]


def test_cli_audit_command(tmp_path) -> None:
    """Verify script retention and hook quality audit command."""
    init_db()
    uid = uuid.uuid4().hex[:8]
    with get_session() as session:
        cluster = StoryCluster(
            cluster_hash=f"hash_audit_cli_test_{uid}",
            title="Audit CLI Test Cluster",
            summary="Summary",
            article_ids=[],
            status="pending",
        )
        session.add(cluster)
        session.flush()

        script = ScriptRecord(
            cluster_id=cluster.id,
            title="Breaking: AI Model Beats All Human Benchmarks",
            aspect_ratio="9:16",
            beats=[{"beat_type": "hook", "estimated_duration_seconds": 5.0}],
            full_narration=(
                "Did you hear the breaking announcement? "
                "AI models just shattered all reasoning benchmarks."
            ),
        )
        session.add(script)
        session.commit()
        script_id = script.id

    # Table output
    res_table = runner.invoke(app, ["audit", str(script_id)])
    assert res_table.exit_code == 0
    assert "Retention & Pacing Audit" in res_table.stdout
    assert "Hook Score" in res_table.stdout

    # JSON output
    res_json = runner.invoke(app, ["audit", str(script_id), "--json"])
    assert res_json.exit_code == 0
    data = json.loads(res_json.stdout)
    assert "hook_score" in data
    assert "words_per_minute" in data
    assert "has_question_hook" in data
    assert data["has_question_hook"] is True


def test_cli_publish_command(tmp_path) -> None:
    """Verify YouTube publishing package generator command."""
    init_db()
    uid = uuid.uuid4().hex[:8]

    with get_session() as session:
        cluster = StoryCluster(
            cluster_hash=f"hash_publish_cli_test_{uid}",
            title="Publish CLI Test Cluster",
            summary="Summary",
            article_ids=[],
            status="pending",
        )
        session.add(cluster)
        session.flush()

        script = ScriptRecord(
            cluster_id=cluster.id,
            title="Publishing Package Test",
            aspect_ratio="9:16",
            beats=[{"beat_type": "hook", "target_duration_seconds": 15.0}],
            full_narration="Here is a high retention narration for publishing package test.",
        )
        session.add(script)
        session.flush()

        render_repo = RenderRepository(session)
        job = render_repo.create_job(script_id=script.id, aspect_ratio="9:16")

        captions = [
            WordCaption(word="Here", start=0.0, end=0.4),
            WordCaption(word="is", start=0.4, end=0.8),
            WordCaption(word="test", start=0.8, end=1.5),
        ]
        cap_file = tmp_path / f"captions_job_{job.id}.json"
        cap_file.write_text(json.dumps([c.model_dump() for c in captions]), encoding="utf-8")
        render_repo.update_job_captions(job.id, str(cap_file))
        session.commit()
        job_id = job.id

    # Table/Panel output
    res_cli = runner.invoke(app, ["publish", str(job_id), "--save-dir", str(tmp_path / "out")])
    assert res_cli.exit_code == 0
    assert "YouTube Publishing Package" in res_cli.stdout
    assert "Primary Title" in res_cli.stdout

    # Verify saved files
    assert (tmp_path / "out" / f"youtube_metadata_job_{job_id}.json").exists()
    assert (tmp_path / "out" / f"job_{job_id}.srt").exists()
    assert (tmp_path / "out" / f"job_{job_id}.vtt").exists()

    # JSON output
    res_json = runner.invoke(app, ["publish", str(job_id), "--json"])
    assert res_json.exit_code == 0
    data = json.loads(res_json.stdout)
    assert data["job_id"] == job_id
    assert "metadata" in data
    assert "srt_subtitles" in data
    assert "vtt_subtitles" in data


def test_cli_status_command() -> None:
    """Verify status command retrieves job progress in text and json modes."""
    init_db()
    uid = uuid.uuid4().hex[:8]
    with get_session() as session:
        cluster = StoryCluster(
            cluster_hash=f"hash_status_cli_test_{uid}",
            title=f"Status CLI Test {uid}",
            summary="Summary",
            article_ids=[],
            status="pending",
        )
        session.add(cluster)
        session.flush()

        script = ScriptRecord(
            cluster_id=cluster.id,
            title="Status Script",
            aspect_ratio="9:16",
            beats=[],
            full_narration="Narration text",
        )
        session.add(script)
        session.flush()

        render_repo = RenderRepository(session)
        job = render_repo.create_job(script_id=script.id, aspect_ratio="9:16")
        job_id = job.id
        session.commit()

    # Text mode
    res_text = runner.invoke(app, ["status", "--job-id", str(job_id)])
    assert res_text.exit_code == 0
    assert "Pipeline Execution Status" in res_text.stdout

    # JSON mode
    res_json = runner.invoke(app, ["status", "--job-id", str(job_id), "--json"])
    assert res_json.exit_code == 0
    data = json.loads(res_json.stdout)
    assert data["job_id"] == job_id
    assert "status" in data

    # Not found case
    res_err = runner.invoke(app, ["status", "--job-id", "99999", "--json"])
    assert res_err.exit_code == 1
    err_data = json.loads(res_err.stdout)
    assert err_data["status"] == "not_found"


def test_cli_publish_youtube_command() -> None:
    """Verify publish-youtube command validation, config check, and upload execution."""
    init_db()

    # Invalid privacy
    res_invalid = runner.invoke(
        app,
        ["publish-youtube", "--job-id", "1", "--privacy", "invalid_status", "--json"],
    )
    assert res_invalid.exit_code == 1
    assert "Invalid privacy status" in res_invalid.stdout

    # OAuth unconfigured
    with patch(
        "src.services.youtube_upload_service.YouTubeUploadService.is_configured",
        return_value=False,
    ):
        res_unconf = runner.invoke(app, ["publish-youtube", "--job-id", "1", "--json"])
        assert res_unconf.exit_code == 1
        assert "YouTube OAuth is not configured" in res_unconf.stdout

    # Successful upload mocked
    mock_result = YouTubeUploadResult(
        video_id="yt_test_vid_123",
        video_url="https://youtu.be/yt_test_vid_123",
        title="Test Published Video",
        privacy_status="unlisted",
        uploaded_at="2026-09-30T12:00:00Z",
    )
    with (
        patch(
            "src.services.youtube_upload_service.YouTubeUploadService.is_configured",
            return_value=True,
        ),
        patch(
            "src.services.youtube_upload_service.YouTubeUploadService.upload_video_for_job",
            return_value=mock_result,
        ),
    ):
        res_success = runner.invoke(
            app,
            ["publish-youtube", "--job-id", "1", "--privacy", "unlisted", "--json"],
        )
        assert res_success.exit_code == 0
        data = json.loads(res_success.stdout)
        assert data["status"] == "success"
        assert data["video_id"] == "yt_test_vid_123"

        # Text mode
        res_text = runner.invoke(app, ["publish-youtube", "--job-id", "1", "--privacy", "unlisted"])
        assert res_text.exit_code == 0
        assert "YouTube Video Published Successfully" in res_text.stdout


def test_cli_render_async_option() -> None:
    """Verify render command supports --async flag for queued execution."""
    with patch("src.services.job_queue_service.JobQueueService.submit_render_job") as mock_submit:
        res = runner.invoke(app, ["render", "--job-id", "10", "--async", "--json"])
        assert res.exit_code == 0
        data = json.loads(res.stdout)
        assert data["status"] == "queued"
        assert data["job_id"] == 10
        mock_submit.assert_called_once_with(job_id=10, dry_run=False)


def test_cli_cluster_command_options() -> None:
    """Verify cluster command supports --hours, --article-ids, and --run-id options."""
    from unittest.mock import MagicMock

    mock_cluster = MagicMock()
    mock_cluster.id = 101
    mock_cluster.title = "CLI Clustered Story"
    mock_cluster.article_count = 3
    mock_cluster.cluster_run_id = "run_cli_test"
    mock_cluster.run_cluster_index = 1
    mock_cluster.status = "pending"

    with patch(
        "src.services.clustering_service.ClusteringService.cluster_recent_articles",
        return_value=[mock_cluster],
    ) as mock_run:
        res = runner.invoke(
            app,
            [
                "cluster",
                "--threshold",
                "0.85",
                "--hours",
                "24",
                "--article-ids",
                "1,2,3",
                "--run-id",
                "run_cli_test",
            ],
        )
        assert res.exit_code == 0
        assert "run_cli_test" in res.stdout
        mock_run.assert_called_once_with(
            threshold=0.85,
            article_ids=[1, 2, 3],
            hours_back=24.0,
            cluster_run_id="run_cli_test",
        )


def test_cli_clusters_command_run_id_filter() -> None:
    """Verify clusters listing command filters by --run-id."""
    init_db()
    uid = uuid.uuid4().hex[:8]
    run_a = f"run_{uid}_a"
    run_b = f"run_{uid}_b"

    with get_session() as session:
        c_a = StoryCluster(
            cluster_hash=f"{run_a}:1",
            title=f"AlphaStory{uid}",
            summary="Summary A",
            article_ids=[1],
            article_count=1,
            cluster_run_id=run_a,
            run_cluster_index=1,
        )
        c_b = StoryCluster(
            cluster_hash=f"{run_b}:1",
            title=f"BetaStory{uid}",
            summary="Summary B",
            article_ids=[2],
            article_count=1,
            cluster_run_id=run_b,
            run_cluster_index=1,
        )
        session.add_all([c_a, c_b])
        session.commit()

    res = runner.invoke(app, ["clusters", "--run-id", run_a])
    assert res.exit_code == 0
    assert run_a in res.stdout
    assert "Alpha" in res.stdout
    assert "Beta" not in res.stdout
