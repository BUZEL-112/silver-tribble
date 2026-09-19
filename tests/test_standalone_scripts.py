"""Integration tests for standalone runner scripts in scripts/ directory."""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from src.core.database import get_session, init_db
from src.models.entities import Article, StoryCluster
from src.repositories.action_log_repository import ActionLogRepository
from src.repositories.script_repository import ScriptRepository


def get_test_env() -> dict[str, str]:
    """Provide environment dictionary with SQLite DATABASE_URL and PYTHONPATH for subprocesses."""
    env = dict(os.environ)
    env["DATABASE_URL"] = env.get("DATABASE_URL", "sqlite:///test.db")
    repo_root = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = f"{repo_root}:{env.get('PYTHONPATH', '')}".rstrip(":")
    return env


def test_run_ingest_json_contract() -> None:
    """Verify run_ingest.py outputs valid JSON and logs to ActionLog."""
    cmd = [sys.executable, "scripts/run_ingest.py", "--json", "--actor", "test_agent"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True, env=get_test_env())

    data = json.loads(proc.stdout)
    assert data["status"] == "success"
    assert "articles_fetched" in data
    assert "new_articles_saved" in data

    # Verify action log
    with get_session() as session:
        repo = ActionLogRepository(session)
        logs = repo.get_recent_logs(stage="ingest", limit=5)
        assert len(logs) > 0
        matching = [log_entry for log_entry in logs if log_entry.actor == "test_agent"]
        assert len(matching) > 0


def test_run_cluster_json_contract() -> None:
    """Verify run_cluster.py outputs valid JSON and logs to ActionLog."""
    cmd = [sys.executable, "scripts/run_cluster.py", "--json", "--actor", "test_agent"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True, env=get_test_env())

    data = json.loads(proc.stdout)
    assert data["status"] == "success"
    assert "clusters_created" in data

    with get_session() as session:
        repo = ActionLogRepository(session)
        logs = repo.get_recent_logs(stage="cluster", limit=5)
        matching = [log_entry for log_entry in logs if log_entry.actor == "test_agent"]
        assert len(matching) > 0


def test_run_script_json_contract() -> None:
    """Verify run_script.py outputs valid JSON when generating script."""
    init_db()
    uid = uuid.uuid4().hex[:8]
    with get_session() as session:
        art = Article(
            title=f"AI Breakthrough {uid}",
            link=f"https://example.com/ai-rev-breakthrough-{uid}",
            source="TechNews",
            summary="New AI model breakthrough announced with great benchmarks.",
        )
        session.add(art)
        session.commit()

        cluster = StoryCluster(
            cluster_hash=f"hash_run_script_{uid}",
            title=f"AI Breakthrough {uid}",
            summary=f"[TechNews] {art.title}: {art.summary}",
            article_ids=[art.id],
            status="pending",
        )
        session.add(cluster)
        session.commit()
        cluster_id = cluster.id

    cmd = [
        sys.executable,
        "scripts/run_script.py",
        "--cluster-id",
        str(cluster_id),
        "--json",
        "--actor",
        "agent_tester",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True, env=get_test_env())

    data = json.loads(proc.stdout)
    assert data["status"] == "success"
    assert int(data["script_id"]) > 0
    assert "title" in data
    assert data["word_count"] > 0

    with get_session() as session:
        repo = ActionLogRepository(session)
        logs = repo.get_recent_logs(stage="script", limit=5)
        matching = [log_entry for log_entry in logs if log_entry.actor == "agent_tester"]
        assert len(matching) > 0


def test_run_voice_media_render_json_contract() -> None:
    """Verify run_voice.py, run_media.py, and run_render.py sequential execution."""
    init_db()
    uid = uuid.uuid4().hex[:8]
    with get_session() as session:
        art = Article(
            title=f"Quantum Computing LLM {uid}",
            link=f"https://example.com/quantum-llm-{uid}",
            source="VentureBeat",
            summary="Quantum LLM architecture advances computational speed.",
        )
        session.add(art)
        session.commit()

        cluster = StoryCluster(
            cluster_hash=f"hash_quantum_{uid}",
            title=f"Quantum Computing LLM {uid}",
            summary=f"[VentureBeat] {art.title}: {art.summary}",
            article_ids=[art.id],
            status="pending",
        )
        session.add(cluster)
        session.commit()

        script_repo = ScriptRepository(session)
        script = script_repo.create_script(
            cluster_id=cluster.id,
            title=f"Quantum Computing Explained {uid}",
            aspect_ratio="9:16",
            beats=[
                {
                    "beat_number": 1,
                    "beat_type": "hook",
                    "on_screen_text": "QUANTUM LEAP",
                    "visual_direction": "Quantum hardware chip",
                    "estimated_duration_seconds": 10.0,
                }
            ],
            full_narration="Scientists have developed a quantum computing processor.",
        )
        script_id = script.id

    # 1. Test run_voice.py
    cmd_voice = [
        sys.executable,
        "scripts/run_voice.py",
        "--script-id",
        str(script_id),
        "--json",
        "--actor",
        "voice_agent",
    ]
    proc_voice = subprocess.run(
        cmd_voice, capture_output=True, text=True, check=True, env=get_test_env()
    )
    voice_data = json.loads(proc_voice.stdout)
    assert voice_data["status"] == "success"
    job_id = voice_data["job_id"]
    assert job_id > 0

    # 2. Test run_media.py
    cmd_media = [
        sys.executable,
        "scripts/run_media.py",
        "--job-id",
        str(job_id),
        "--json",
        "--actor",
        "media_agent",
    ]
    proc_media = subprocess.run(
        cmd_media, capture_output=True, text=True, check=True, env=get_test_env()
    )
    media_data = json.loads(proc_media.stdout)
    assert media_data["status"] == "success"
    assert media_data["media_count"] >= 1

    # 3. Test run_render.py (dry-run)
    cmd_render = [
        sys.executable,
        "scripts/run_render.py",
        "--job-id",
        str(job_id),
        "--dry-run",
        "--json",
        "--actor",
        "render_agent",
    ]
    proc_render = subprocess.run(
        cmd_render, capture_output=True, text=True, check=True, env=get_test_env()
    )
    render_data = json.loads(proc_render.stdout)
    assert render_data["status"] == "success"
    assert "output_video_path" in render_data
