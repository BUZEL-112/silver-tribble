"""Tests for redesigned CLI interfaces and presentation commands."""

import json
import uuid

from typer.testing import CliRunner

from src.cli import app
from src.core.database import get_session, init_db
from src.models.entities import Article, ScriptRecord, StoryCluster
from src.models.schemas import WordCaption
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
