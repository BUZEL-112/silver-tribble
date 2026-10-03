"""
Integration tests for the FastAPI REST endpoints defined in src/web.py.

Scope: POST /api/pipeline/ingest, /cluster, /script, /voice, /render, /run,
       /roundup, /roundup-script; GET /api/jobs/{job_id}/progress, /api/budget.

Strategy
--------
- All service and repository calls are mocked via pytest-mock so no real DB or
  external API is touched.
- Authentication scenarios (no-auth bypass, valid Bearer, invalid Bearer, valid
  session cookie) are exercised for auth-protected endpoints.
- The Starlette TestClient is used synchronously; async helpers are not needed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from src.web import app

# ---------------------------------------------------------------------------
# Shared client fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    """Return a Starlette TestClient wrapping the FastAPI app."""
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_script_record(
    script_id: int = 1,
    title: str = "AI Report",
    narration: str = "word " * 50,
) -> MagicMock:
    """Return a minimal mock that looks like a ScriptRecord ORM row."""
    record = MagicMock()
    record.id = script_id
    record.title = title
    record.full_narration = narration
    record.beats = []
    record.script_id = script_id
    return record


def _make_job_record(
    job_id: int = 10,
    script_id: int = 1,
    audio_path: str = "audio/job_10.mp3",
    captions_path: str | None = None,
    duration_seconds: float = 30.0,
) -> MagicMock:
    """Return a minimal mock that looks like a RenderJob ORM row."""
    job = MagicMock()
    job.id = job_id
    job.script_id = script_id
    job.audio_path = audio_path
    job.captions_path = captions_path
    job.duration_seconds = duration_seconds
    return job


def _make_cluster(cluster_id: int = 1) -> MagicMock:
    """Return a minimal mock that looks like a StoryCluster ORM row."""
    c = MagicMock()
    c.id = cluster_id
    c.status = "pending"
    return c


# ---------------------------------------------------------------------------
# POST /api/pipeline/ingest
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_ingest_happy_path_returns_fetched_and_saved_counts(
    client: TestClient,
    mocker: Any,
) -> None:
    """Happy path: 3 articles fetched, 2 saved -> response reflects both counts."""
    fake_items = [MagicMock(), MagicMock(), MagicMock()]
    fake_saved = [MagicMock(), MagicMock()]

    mocker.patch("src.web.RssService.fetch_all_feeds", return_value=fake_items)
    mocker.patch("src.web.get_session", return_value=_make_ctx_session_manager(mocker))
    mocker.patch("src.web.ArticleRepository.save_feed_items", return_value=fake_saved)
    _patch_action_log(mocker)

    response = client.post("/api/pipeline/ingest")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["articles_fetched"] == 3
    assert body["new_articles_saved"] == 2


@pytest.mark.integration
def test_ingest_service_exception_returns_500(
    client: TestClient,
    mocker: Any,
) -> None:
    """When RssService raises, the endpoint returns 500."""
    mocker.patch(
        "src.web.RssService.fetch_all_feeds",
        side_effect=RuntimeError("feed timeout"),
    )

    response = client.post("/api/pipeline/ingest")

    assert response.status_code == 500
    assert "feed timeout" in response.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/pipeline/cluster
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cluster_happy_path_returns_embedded_and_cluster_counts(
    client: TestClient,
    mocker: Any,
) -> None:
    """Happy path: 5 embedded articles, 2 clusters -> response is correct."""
    clusters = [_make_cluster(1), _make_cluster(2)]

    mocker.patch("src.web.get_session", return_value=_make_ctx_session_manager(mocker))
    mocker.patch(
        "src.web.ClusteringService.generate_embeddings_for_new_articles",
        return_value=5,
    )
    mocker.patch(
        "src.web.ClusteringService.cluster_recent_articles",
        return_value=clusters,
    )
    _patch_action_log(mocker)

    response = client.post("/api/pipeline/cluster")

    assert response.status_code == 200
    body = response.json()
    assert body["articles_embedded"] == 5
    assert body["clusters_created"] == 2
    assert body["top_cluster_id"] == 1


@pytest.mark.integration
def test_cluster_with_custom_threshold_is_forwarded(
    client: TestClient,
    mocker: Any,
) -> None:
    """Query param threshold is passed through to the clustering service."""
    mock_cluster = mocker.patch(
        "src.web.ClusteringService.cluster_recent_articles",
        return_value=[],
    )
    mocker.patch(
        "src.web.ClusteringService.generate_embeddings_for_new_articles",
        return_value=0,
    )
    mocker.patch("src.web.get_session", return_value=_make_ctx_session_manager(mocker))
    _patch_action_log(mocker)

    response = client.post("/api/pipeline/cluster?threshold=0.90")

    assert response.status_code == 200
    mock_cluster.assert_called_once_with(threshold=0.90)


@pytest.mark.integration
def test_cluster_service_exception_returns_500(
    client: TestClient,
    mocker: Any,
) -> None:
    """When ClusteringService raises, the endpoint returns 500."""
    mocker.patch("src.web.get_session", return_value=_make_ctx_session_manager(mocker))
    mocker.patch(
        "src.web.ClusteringService.generate_embeddings_for_new_articles",
        side_effect=RuntimeError("embedding model unavailable"),
    )
    _patch_action_log(mocker)

    response = client.post("/api/pipeline/cluster")

    assert response.status_code == 500
    assert "embedding model unavailable" in response.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/pipeline/script
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_script_happy_path_returns_script_id_title_word_count(
    client: TestClient,
    mocker: Any,
) -> None:
    """Happy path: generated script has id, title, and correct word count."""
    narration = "hello " * 10  # 10 words
    record = _make_script_record(script_id=7, title="Breaking AI News", narration=narration)

    mocker.patch("src.web.get_session", return_value=_make_ctx_session_manager(mocker))
    mocker.patch("src.web.ScriptService.generate_full_script", return_value=record)
    _patch_action_log(mocker)

    response = client.post(
        "/api/pipeline/script",
        json={"cluster_id": 3, "aspect_ratio": "9:16"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["script_id"] == 7
    assert body["title"] == "Breaking AI News"
    assert body["word_count"] == 10


@pytest.mark.integration
def test_script_cluster_not_found_returns_500(
    client: TestClient,
    mocker: Any,
) -> None:
    """When ScriptService raises (e.g. cluster missing), endpoint returns 500."""
    mocker.patch("src.web.get_session", return_value=_make_ctx_session_manager(mocker))
    mocker.patch(
        "src.web.ScriptService.generate_full_script",
        side_effect=ValueError("Cluster 99 not found"),
    )
    _patch_action_log(mocker)

    response = client.post(
        "/api/pipeline/script",
        json={"cluster_id": 99, "aspect_ratio": "9:16"},
    )

    assert response.status_code == 500
    assert "Cluster 99 not found" in response.json()["detail"]


@pytest.mark.integration
def test_script_unexpected_exception_returns_500(
    client: TestClient,
    mocker: Any,
) -> None:
    """Unexpected exceptions from ScriptService map to HTTP 500."""
    mocker.patch("src.web.get_session", return_value=_make_ctx_session_manager(mocker))
    mocker.patch(
        "src.web.ScriptService.generate_full_script",
        side_effect=Exception("LLM quota exceeded"),
    )
    _patch_action_log(mocker)

    response = client.post(
        "/api/pipeline/script",
        json={"cluster_id": 1, "aspect_ratio": "9:16"},
    )

    assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /api/pipeline/voice
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_voice_happy_path_returns_job_id_audio_path_duration(
    client: TestClient,
    mocker: Any,
) -> None:
    """Happy path: TTS and captions succeed -> job_id, audio_path, duration returned."""
    script = _make_script_record(script_id=5, narration="hello world")
    job = _make_job_record(job_id=20, script_id=5)

    mocker.patch("src.web.get_storage_service", return_value=MagicMock())
    mocker.patch("src.web.get_session", return_value=_make_ctx_session_manager(mocker))
    mocker.patch("src.web.ScriptRepository.get_script_by_id", return_value=script)
    mocker.patch("src.web.RenderRepository.create_job", return_value=job)
    mocker.patch(
        "src.web.TtsService.synthesize_speech",
        return_value=("audio/job_20.mp3", 12.5),
    )
    mocker.patch("src.web.RenderRepository.update_job_audio")
    mocker.patch(
        "src.web.CaptionService.generate_captions",
        return_value=("captions/job_20.json", []),
    )
    mocker.patch("src.web.RenderRepository.update_job_captions")
    _patch_action_log(mocker)

    response = client.post(
        "/api/pipeline/voice",
        json={"script_id": 5, "aspect_ratio": "9:16"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == 20
    assert body["audio_path"] == "audio/job_20.mp3"
    assert body["duration"] == 12.5


@pytest.mark.integration
def test_voice_script_not_found_returns_404(
    client: TestClient,
    mocker: Any,
) -> None:
    """When script_repo.get_script_by_id returns None, endpoint returns 404."""
    mocker.patch("src.web.get_storage_service", return_value=MagicMock())
    mocker.patch("src.web.get_session", return_value=_make_ctx_session_manager(mocker))
    mocker.patch("src.web.ScriptRepository.get_script_by_id", return_value=None)
    _patch_action_log(mocker)

    response = client.post(
        "/api/pipeline/voice",
        json={"script_id": 999, "aspect_ratio": "9:16"},
    )

    assert response.status_code == 404
    assert "999" in response.json()["detail"]


@pytest.mark.integration
def test_voice_tts_exception_returns_500(
    client: TestClient,
    mocker: Any,
) -> None:
    """When TtsService raises, endpoint returns 500."""
    script = _make_script_record(script_id=5)
    job = _make_job_record(job_id=21, script_id=5)

    mocker.patch("src.web.get_storage_service", return_value=MagicMock())
    mocker.patch("src.web.get_session", return_value=_make_ctx_session_manager(mocker))
    mocker.patch("src.web.ScriptRepository.get_script_by_id", return_value=script)
    mocker.patch("src.web.RenderRepository.create_job", return_value=job)
    mocker.patch(
        "src.web.TtsService.synthesize_speech",
        side_effect=RuntimeError("TTS service unreachable"),
    )
    _patch_action_log(mocker)

    response = client.post(
        "/api/pipeline/voice",
        json={"script_id": 5, "aspect_ratio": "9:16"},
    )

    assert response.status_code == 500
    assert "TTS service unreachable" in response.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/pipeline/render
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_render_sync_happy_path_returns_output_video_path(
    client: TestClient,
    mocker: Any,
) -> None:
    """Sync render (async_mode=False) returns output_video_path on success."""
    job = _make_job_record(job_id=30, script_id=2, captions_path=None)
    script = _make_script_record(script_id=2)
    fake_output = Path("/tmp/out/video.mp4")

    mocker.patch("src.web.get_storage_service", return_value=_make_storage(mocker))
    mocker.patch("src.web.get_session", return_value=_make_ctx_session_manager(mocker))
    mocker.patch("src.web.RenderRepository.get_job_by_id", return_value=job)
    mocker.patch("src.web.ScriptRepository.get_script_by_id", return_value=script)
    mocker.patch("src.web.CaptionService.generate_captions", return_value=("c.json", []))
    mocker.patch("src.web.MediaService.process_media_for_job", return_value=[])
    mocker.patch("src.web.RenderService.prepare_render_props")
    mocker.patch("src.web.RenderService.execute_render", return_value=fake_output)
    _patch_action_log(mocker)

    response = client.post(
        "/api/pipeline/render",
        json={"job_id": 30, "dry_run": False, "async_mode": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["job_id"] == 30
    assert "video.mp4" in body["output_video_path"]


@pytest.mark.integration
def test_render_async_mode_returns_202_queued(
    client: TestClient,
    mocker: Any,
) -> None:
    """async_mode=True dispatches to queue and returns HTTP 202 with status=queued."""
    mocker.patch("src.web.JobQueueService.submit_render_job")

    response = client.post(
        "/api/pipeline/render",
        json={"job_id": 5, "dry_run": False, "async_mode": True},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["job_id"] == 5


@pytest.mark.integration
def test_render_job_not_found_returns_404(
    client: TestClient,
    mocker: Any,
) -> None:
    """When render job is not found, endpoint returns 404."""
    mocker.patch("src.web.get_storage_service", return_value=_make_storage(mocker))
    mocker.patch("src.web.get_session", return_value=_make_ctx_session_manager(mocker))
    mocker.patch("src.web.RenderRepository.get_job_by_id", return_value=None)
    _patch_action_log(mocker)

    response = client.post(
        "/api/pipeline/render",
        json={"job_id": 999, "dry_run": False, "async_mode": False},
    )

    assert response.status_code == 404
    assert "999" in response.json()["detail"]


@pytest.mark.integration
def test_render_script_not_found_for_job_returns_404(
    client: TestClient,
    mocker: Any,
) -> None:
    """When script is missing for an existing job, endpoint returns 404."""
    job = _make_job_record(job_id=31, script_id=77)

    mocker.patch("src.web.get_storage_service", return_value=_make_storage(mocker))
    mocker.patch("src.web.get_session", return_value=_make_ctx_session_manager(mocker))
    mocker.patch("src.web.RenderRepository.get_job_by_id", return_value=job)
    mocker.patch("src.web.ScriptRepository.get_script_by_id", return_value=None)
    _patch_action_log(mocker)

    response = client.post(
        "/api/pipeline/render",
        json={"job_id": 31, "dry_run": False, "async_mode": False},
    )

    assert response.status_code == 404
    assert "77" in response.json()["detail"]


@pytest.mark.integration
def test_render_service_exception_returns_500(
    client: TestClient,
    mocker: Any,
) -> None:
    """When RenderService.execute_render raises, endpoint returns 500."""
    job = _make_job_record(job_id=32, script_id=2, captions_path=None)
    script = _make_script_record(script_id=2)

    mocker.patch("src.web.get_storage_service", return_value=_make_storage(mocker))
    mocker.patch("src.web.get_session", return_value=_make_ctx_session_manager(mocker))
    mocker.patch("src.web.RenderRepository.get_job_by_id", return_value=job)
    mocker.patch("src.web.ScriptRepository.get_script_by_id", return_value=script)
    mocker.patch("src.web.CaptionService.generate_captions", return_value=("c.json", []))
    mocker.patch("src.web.MediaService.process_media_for_job", return_value=[])
    mocker.patch("src.web.RenderService.prepare_render_props")
    mocker.patch(
        "src.web.RenderService.execute_render",
        side_effect=RuntimeError("ffmpeg not found"),
    )
    _patch_action_log(mocker)

    response = client.post(
        "/api/pipeline/render",
        json={"job_id": 32, "dry_run": False, "async_mode": False},
    )

    assert response.status_code == 500
    assert "ffmpeg not found" in response.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/pipeline/render -- auth scenarios
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_render_no_auth_configured_allows_request(
    client: TestClient,
    mocker: Any,
) -> None:
    """When no auth token is configured, the render endpoint passes through."""
    mocker.patch("src.web.settings.api_auth_token", new="")
    mocker.patch("src.web.settings.admin_password", new="")
    mocker.patch("src.web.JobQueueService.submit_render_job")

    response = client.post(
        "/api/pipeline/render",
        json={"job_id": 1, "async_mode": True},
    )

    assert response.status_code == 202


@pytest.mark.integration
def test_render_valid_bearer_token_allows_request(
    client: TestClient,
    mocker: Any,
) -> None:
    """A correct Bearer token grants access to the render endpoint."""
    secret = "my-secret-token"
    mocker.patch("src.core.security.settings.api_auth_token", new=secret)
    mocker.patch("src.core.security.settings.admin_password", new="")
    mocker.patch("src.web.JobQueueService.submit_render_job")

    response = client.post(
        "/api/pipeline/render",
        json={"job_id": 1, "async_mode": True},
        headers={"Authorization": f"Bearer {secret}"},
    )

    assert response.status_code == 202


@pytest.mark.integration
def test_render_invalid_bearer_token_returns_401(
    client: TestClient,
    mocker: Any,
) -> None:
    """An incorrect Bearer token is rejected with 401 when auth is configured."""
    mocker.patch("src.core.security.settings.api_auth_token", new="correct-token")
    mocker.patch("src.core.security.settings.admin_password", new="")

    response = client.post(
        "/api/pipeline/render",
        json={"job_id": 1, "async_mode": True},
        headers={"Authorization": "Bearer wrong-token"},
    )

    assert response.status_code == 401


@pytest.mark.integration
def test_render_valid_session_cookie_allows_request(
    client: TestClient,
    mocker: Any,
) -> None:
    """A valid dashboard session cookie grants access to the render endpoint."""
    from src.core.security import generate_session_token

    session_token = generate_session_token()
    mocker.patch("src.core.security.settings.api_auth_token", new="")
    mocker.patch("src.core.security.settings.admin_password", new="secret")
    mocker.patch("src.web.JobQueueService.submit_render_job")

    response = client.post(
        "/api/pipeline/render",
        json={"job_id": 1, "async_mode": True},
        cookies={"ai_video_session": session_token},
    )

    assert response.status_code == 202

    # Clean up session token
    from src.core.security import invalidate_session_token

    invalidate_session_token(session_token)


# ---------------------------------------------------------------------------
# POST /api/pipeline/run
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_run_async_mode_returns_202_queued(
    client: TestClient,
    mocker: Any,
) -> None:
    """async_mode=True dispatches pipeline to queue and returns 202."""
    mocker.patch("src.web.JobQueueService.submit_pipeline_job", return_value=55)

    response = client.post(
        "/api/pipeline/run",
        json={"cluster_id": 1, "async_mode": True},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["job_id"] == 55


@pytest.mark.integration
def test_run_requires_auth_token_returns_401_when_configured(
    client: TestClient,
    mocker: Any,
) -> None:
    """Without a token, /api/pipeline/run returns 401 when auth is configured."""
    mocker.patch("src.core.security.settings.api_auth_token", new="prod-token")
    mocker.patch("src.core.security.settings.admin_password", new="")

    response = client.post(
        "/api/pipeline/run",
        json={"cluster_id": 1, "async_mode": False},
    )

    assert response.status_code == 401


@pytest.mark.integration
def test_run_sync_pipeline_exception_returns_500(
    client: TestClient,
    mocker: Any,
) -> None:
    """When run_video_pipeline raises, /api/pipeline/run returns 500."""
    mocker.patch("src.core.security.settings.api_auth_token", new="")
    mocker.patch("src.core.security.settings.admin_password", new="")
    mocker.patch(
        "src.web.run_video_pipeline",
        side_effect=RuntimeError("pipeline blew up"),
    )

    response = client.post(
        "/api/pipeline/run",
        json={"cluster_id": 1, "async_mode": False},
    )

    assert response.status_code == 500
    assert "pipeline blew up" in response.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/progress
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_job_progress_returns_200_with_progress_dict(
    client: TestClient,
    mocker: Any,
) -> None:
    """When job exists, progress dict is returned with 200."""
    progress_data = {"stage": "render", "pct": 72, "status": "running"}
    mocker.patch("src.web.JobQueueService.get_progress", return_value=progress_data)

    response = client.get("/api/jobs/42/progress")

    assert response.status_code == 200
    assert response.json() == progress_data


@pytest.mark.integration
def test_job_progress_unknown_job_returns_404(
    client: TestClient,
    mocker: Any,
) -> None:
    """When JobQueueService.get_progress returns None, endpoint returns 404."""
    mocker.patch("src.web.JobQueueService.get_progress", return_value=None)

    response = client.get("/api/jobs/9999/progress")

    assert response.status_code == 404
    assert "9999" in response.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/budget
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_budget_returns_spend_and_cap_fields(
    client: TestClient,
    mocker: Any,
) -> None:
    """Budget endpoint returns total_spend_usd, caps, and exceeded flags."""
    mocker.patch("src.web.get_session", return_value=_make_ctx_session_manager(mocker))
    mocker.patch("src.web.CostRepository.get_total_spend", return_value=3.1416)
    mocker.patch("src.web.settings.cost_daily_budget_usd", new=10.0)
    mocker.patch("src.web.settings.cost_monthly_budget_usd", new=100.0)

    response = client.get("/api/budget")

    assert response.status_code == 200
    body = response.json()
    assert "total_spend_usd" in body
    assert "daily_budget_usd" in body
    assert "monthly_budget_usd" in body
    assert "daily_budget_exceeded" in body
    assert "monthly_budget_exceeded" in body


@pytest.mark.integration
def test_budget_exceeded_flags_set_correctly_when_over_cap(
    client: TestClient,
    mocker: Any,
) -> None:
    """daily_budget_exceeded is True when total spend meets or exceeds cap."""
    mocker.patch("src.web.get_session", return_value=_make_ctx_session_manager(mocker))
    mocker.patch("src.web.CostRepository.get_total_spend", return_value=15.0)
    mocker.patch("src.web.settings.cost_daily_budget_usd", new=10.0)
    mocker.patch("src.web.settings.cost_monthly_budget_usd", new=200.0)

    response = client.get("/api/budget")

    body = response.json()
    assert body["daily_budget_exceeded"] is True
    assert body["monthly_budget_exceeded"] is False


# ---------------------------------------------------------------------------
# POST /api/pipeline/roundup
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_roundup_happy_path_with_cluster_ids(
    client: TestClient,
    mocker: Any,
) -> None:
    """Happy path: run_roundup_pipeline is called and result is returned."""
    pipeline_result = {"job_id": 77, "output_video_path": "/out/roundup.mp4"}
    mock_pipeline = mocker.patch(
        "src.web.run_roundup_pipeline",
        return_value=pipeline_result,
    )

    response = client.post(
        "/api/pipeline/roundup",
        json={"cluster_ids": [3, 1, 2], "top_n": 3, "aspect_ratio": "9:16"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["job_id"] == 77
    # Cluster IDs are deduplicated and sorted before forwarding
    call_kwargs = mock_pipeline.call_args.kwargs
    assert call_kwargs["cluster_ids"] == [1, 2, 3]


@pytest.mark.integration
def test_roundup_deduplicates_and_sorts_cluster_ids(
    client: TestClient,
    mocker: Any,
) -> None:
    """Duplicate cluster_ids are removed and the sorted list is passed downstream."""
    mock_pipeline = mocker.patch(
        "src.web.run_roundup_pipeline",
        return_value={"output": "done"},
    )

    client.post(
        "/api/pipeline/roundup",
        json={"cluster_ids": [5, 2, 5, 1, 2], "top_n": 3},
    )

    call_kwargs = mock_pipeline.call_args.kwargs
    assert call_kwargs["cluster_ids"] == [1, 2, 5]


@pytest.mark.integration
def test_roundup_pipeline_exception_returns_500(
    client: TestClient,
    mocker: Any,
) -> None:
    """When run_roundup_pipeline raises, endpoint returns 500."""
    mocker.patch(
        "src.web.run_roundup_pipeline",
        side_effect=RuntimeError("roundup failed"),
    )

    response = client.post(
        "/api/pipeline/roundup",
        json={"cluster_ids": [1, 2, 3]},
    )

    assert response.status_code == 500
    assert "roundup failed" in response.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/pipeline/roundup-script
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_roundup_script_happy_path_with_cluster_ids(
    client: TestClient,
    mocker: Any,
) -> None:
    """Happy path: roundup script is generated and key fields are returned."""
    script = _make_script_record(script_id=9, title="Weekly Roundup", narration="word " * 20)
    script.beats = [MagicMock(), MagicMock(), MagicMock()]

    mocker.patch("src.web.get_session", return_value=_make_ctx_session_manager(mocker))
    mocker.patch("src.web.ScriptService.generate_roundup_script", return_value=script)
    _patch_action_log(mocker)

    response = client.post(
        "/api/pipeline/roundup-script",
        json={"cluster_ids": [1, 2, 3], "aspect_ratio": "9:16"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["script_id"] == 9
    assert body["title"] == "Weekly Roundup"
    assert body["word_count"] == 20
    assert body["beats_count"] == 3


@pytest.mark.integration
def test_roundup_script_no_clusters_found_returns_404(
    client: TestClient,
    mocker: Any,
) -> None:
    """When no clusters are available and none are specified, returns 404."""
    mock_art_repo = MagicMock()
    mock_art_repo.get_recent_clusters.return_value = []

    mocker.patch("src.web.get_session", return_value=_make_ctx_session_manager(mocker))
    mocker.patch("src.web.ArticleRepository.get_recent_clusters", return_value=[])
    _patch_action_log(mocker)

    response = client.post(
        "/api/pipeline/roundup-script",
        json={"cluster_ids": None, "top_n": 3},
    )

    assert response.status_code == 404
    assert "No story clusters" in response.json()["detail"]


@pytest.mark.integration
def test_roundup_script_deduplicates_and_sorts_cluster_ids(
    client: TestClient,
    mocker: Any,
) -> None:
    """Explicit cluster_ids are deduplicated and sorted before script generation."""
    script = _make_script_record(script_id=11, narration="a " * 5)
    script.beats = []
    mock_generate = mocker.patch(
        "src.web.ScriptService.generate_roundup_script",
        return_value=script,
    )
    mocker.patch("src.web.get_session", return_value=_make_ctx_session_manager(mocker))
    _patch_action_log(mocker)

    client.post(
        "/api/pipeline/roundup-script",
        json={"cluster_ids": [4, 1, 4, 2], "aspect_ratio": "9:16"},
    )

    call_args = mock_generate.call_args
    assert call_args.kwargs["cluster_ids"] == [1, 2, 4]


# ---------------------------------------------------------------------------
# auth scenarios for POST /api/pipeline/run
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_run_no_auth_configured_allows_request(
    client: TestClient,
    mocker: Any,
) -> None:
    """No auth configured -> /api/pipeline/run is accessible."""
    mocker.patch("src.core.security.settings.api_auth_token", new="")
    mocker.patch("src.core.security.settings.admin_password", new="")
    mocker.patch("src.web.JobQueueService.submit_pipeline_job", return_value=1)

    response = client.post(
        "/api/pipeline/run",
        json={"cluster_id": 1, "async_mode": True},
    )

    assert response.status_code == 202


@pytest.mark.integration
def test_run_valid_bearer_token_allows_request(
    client: TestClient,
    mocker: Any,
) -> None:
    """Correct Bearer token grants access to /api/pipeline/run."""
    secret = "run-secret"
    mocker.patch("src.core.security.settings.api_auth_token", new=secret)
    mocker.patch("src.core.security.settings.admin_password", new="")
    mocker.patch("src.web.JobQueueService.submit_pipeline_job", return_value=2)

    response = client.post(
        "/api/pipeline/run",
        json={"cluster_id": 1, "async_mode": True},
        headers={"Authorization": f"Bearer {secret}"},
    )

    assert response.status_code == 202


@pytest.mark.integration
def test_run_valid_session_cookie_allows_request(
    client: TestClient,
    mocker: Any,
) -> None:
    """A valid session cookie grants access to /api/pipeline/run."""
    from src.core.security import generate_session_token, invalidate_session_token

    session_token = generate_session_token()
    mocker.patch("src.core.security.settings.api_auth_token", new="")
    mocker.patch("src.core.security.settings.admin_password", new="admin-pw")
    mocker.patch("src.web.JobQueueService.submit_pipeline_job", return_value=3)

    try:
        response = client.post(
            "/api/pipeline/run",
            json={"cluster_id": 1, "async_mode": True},
            cookies={"ai_video_session": session_token},
        )
        assert response.status_code == 202
    finally:
        invalidate_session_token(session_token)


# ---------------------------------------------------------------------------
# Internal test helpers (not test functions)
# ---------------------------------------------------------------------------


def _make_ctx_session_manager(mocker: Any) -> Any:
    """Return a context manager mock that yields a MagicMock session."""
    ctx = MagicMock()
    session = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _make_storage(mocker: Any) -> MagicMock:
    """Return a storage service mock with a get_local_path stub."""
    storage = MagicMock()
    storage.get_local_path.return_value = Path("/tmp/nonexistent_path")
    return storage


def _patch_action_log(mocker: Any) -> None:
    """Patch ActionLogRepository.track_operation as a no-op context manager."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=None)
    ctx.__exit__ = MagicMock(return_value=False)
    mocker.patch("src.web.ActionLogRepository.track_operation", return_value=ctx)
