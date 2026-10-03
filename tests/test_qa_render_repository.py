"""QA tests for RenderRepository.

Covers:
- create_job: field defaults and stored values
- get_job_by_id: hit and miss paths
- update_job_audio: sets audio_path and duration_seconds, tolerates missing id
- update_job_captions: sets captions_path
- list_jobs (get_recent_jobs): ordering and limit
- idempotency: successive audio updates overwrite correctly
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy.orm import Session

from src.models.entities import ScriptRecord, StoryCluster
from src.repositories.article_repository import ArticleRepository
from src.repositories.render_repository import RenderRepository
from src.repositories.script_repository import ScriptRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cluster(article_repo: ArticleRepository, suffix: str = "a") -> StoryCluster:
    """Insert a minimal StoryCluster and return the persisted instance."""
    return article_repo.save_story_cluster(
        cluster_hash=f"hash-{suffix}",
        title=f"Test Cluster {suffix}",
        summary="A test cluster summary.",
        article_ids=[1, 2],
    )


def _make_script(
    script_repo: ScriptRepository,
    cluster_id: int,
    aspect_ratio: str = "9:16",
) -> ScriptRecord:
    """Insert a minimal ScriptRecord and return the persisted instance."""
    return script_repo.create_script(
        cluster_id=cluster_id,
        title="Test Script",
        aspect_ratio=aspect_ratio,
        beats=[{"beat": 1, "text": "Intro"}],
        full_narration="Full narration text here.",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_create_job_stores_script_id_and_aspect_ratio(
    db_session: Session,
    render_repo: RenderRepository,
    script_repo: ScriptRepository,
    article_repo: ArticleRepository,
) -> None:
    """create_job persists the correct script_id and aspect_ratio on the record."""
    cluster = _make_cluster(article_repo, suffix="b1")
    script = _make_script(script_repo, cluster.id, aspect_ratio="16:9")

    job = render_repo.create_job(script_id=script.id, aspect_ratio="16:9")

    assert job.script_id == script.id
    assert job.aspect_ratio == "16:9"


@pytest.mark.unit
def test_create_job_defaults_status_to_pending(
    db_session: Session,
    render_repo: RenderRepository,
    script_repo: ScriptRepository,
    article_repo: ArticleRepository,
) -> None:
    """create_job always sets status='pending' without requiring caller input."""
    cluster = _make_cluster(article_repo, suffix="b2")
    script = _make_script(script_repo, cluster.id)

    job = render_repo.create_job(script_id=script.id, aspect_ratio="9:16")

    assert job.status == "pending"


@pytest.mark.unit
def test_get_job_by_id_returns_existing_job(
    db_session: Session,
    render_repo: RenderRepository,
    script_repo: ScriptRepository,
    article_repo: ArticleRepository,
) -> None:
    """get_job_by_id fetches the correct job when given a valid primary key."""
    cluster = _make_cluster(article_repo, suffix="b3")
    script = _make_script(script_repo, cluster.id)
    created = render_repo.create_job(script_id=script.id, aspect_ratio="9:16")

    fetched = render_repo.get_job_by_id(created.id)

    assert fetched is not None
    assert fetched.id == created.id


@pytest.mark.unit
def test_get_job_by_id_returns_none_for_missing_id(
    db_session: Session,
    render_repo: RenderRepository,
) -> None:
    """get_job_by_id returns None when the requested id does not exist."""
    result = render_repo.get_job_by_id(job_id=999_999)

    assert result is None


@pytest.mark.unit
def test_update_job_audio_sets_audio_path_and_duration(
    db_session: Session,
    render_repo: RenderRepository,
    script_repo: ScriptRepository,
    article_repo: ArticleRepository,
) -> None:
    """update_job_audio persists audio_path and duration_seconds on the job."""
    cluster = _make_cluster(article_repo, suffix="b4")
    script = _make_script(script_repo, cluster.id)
    job = render_repo.create_job(script_id=script.id, aspect_ratio="9:16")

    render_repo.update_job_audio(
        job_id=job.id,
        audio_path="/audio/test.mp3",
        duration_seconds=45.5,
    )

    updated = render_repo.get_job_by_id(job.id)
    assert updated is not None
    assert updated.audio_path == "/audio/test.mp3"
    assert updated.duration_seconds == pytest.approx(45.5)


@pytest.mark.unit
def test_update_job_audio_with_nonexistent_id_does_not_raise(
    db_session: Session,
    render_repo: RenderRepository,
) -> None:
    """update_job_audio silently no-ops when job_id refers to a missing record."""
    render_repo.update_job_audio(
        job_id=999_999,
        audio_path="/audio/ghost.mp3",
        duration_seconds=10.0,
    )


@pytest.mark.unit
def test_update_job_captions_sets_captions_path(
    db_session: Session,
    render_repo: RenderRepository,
    script_repo: ScriptRepository,
    article_repo: ArticleRepository,
) -> None:
    """update_job_captions persists the captions_path on the job record."""
    cluster = _make_cluster(article_repo, suffix="b5")
    script = _make_script(script_repo, cluster.id)
    job = render_repo.create_job(script_id=script.id, aspect_ratio="9:16")

    render_repo.update_job_captions(job_id=job.id, captions_path="/captions/test.json")

    updated = render_repo.get_job_by_id(job.id)
    assert updated is not None
    assert updated.captions_path == "/captions/test.json"


@pytest.mark.unit
def test_list_jobs_returns_jobs_ordered_by_created_at_desc(
    db_session: Session,
    render_repo: RenderRepository,
    script_repo: ScriptRepository,
    article_repo: ArticleRepository,
) -> None:
    """get_recent_jobs returns all jobs with the most recently created job first."""
    cluster = _make_cluster(article_repo, suffix="b6")
    script = _make_script(script_repo, cluster.id)

    job_first = render_repo.create_job(script_id=script.id, aspect_ratio="9:16")
    time.sleep(0.01)
    job_second = render_repo.create_job(script_id=script.id, aspect_ratio="16:9")

    jobs = render_repo.get_recent_jobs()

    ids = [j.id for j in jobs]
    assert ids.index(job_second.id) < ids.index(job_first.id)


@pytest.mark.unit
def test_list_jobs_with_limit_respects_limit(
    db_session: Session,
    render_repo: RenderRepository,
    script_repo: ScriptRepository,
    article_repo: ArticleRepository,
) -> None:
    """get_recent_jobs with limit=1 returns exactly one job even when more exist."""
    cluster = _make_cluster(article_repo, suffix="b7")
    script = _make_script(script_repo, cluster.id)

    render_repo.create_job(script_id=script.id, aspect_ratio="9:16")
    render_repo.create_job(script_id=script.id, aspect_ratio="9:16")
    render_repo.create_job(script_id=script.id, aspect_ratio="9:16")

    jobs = render_repo.get_recent_jobs(limit=1)

    assert len(jobs) == 1


@pytest.mark.unit
def test_update_job_audio_twice_overwrites_previous_values(
    db_session: Session,
    render_repo: RenderRepository,
    script_repo: ScriptRepository,
    article_repo: ArticleRepository,
) -> None:
    """Calling update_job_audio twice leaves only the second call's values on the job."""
    cluster = _make_cluster(article_repo, suffix="b8")
    script = _make_script(script_repo, cluster.id)
    job = render_repo.create_job(script_id=script.id, aspect_ratio="9:16")

    render_repo.update_job_audio(
        job_id=job.id,
        audio_path="/audio/first.mp3",
        duration_seconds=30.0,
    )
    render_repo.update_job_audio(
        job_id=job.id,
        audio_path="/audio/second.mp3",
        duration_seconds=60.0,
    )

    final = render_repo.get_job_by_id(job.id)
    assert final is not None
    assert final.audio_path == "/audio/second.mp3"
    assert final.duration_seconds == pytest.approx(60.0)
