"""Tests for rate limiting, budget guardrail enforcement, render concurrency locking, and metrics.

Covers:
- In-memory sliding window IP rate limiting on heavy execution and read endpoints.
- CostGuardrailService pre-execution budget validation and HTTP 429 abortion.
- Single-worker Remotion render concurrency lock and HTTP 409 Conflict rejection.
- Prometheus /metrics endpoint format and telemetry indicators.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from src.core.config import settings
from src.web import app, cost_guardrail, pipeline_metrics, rate_limiter, render_lock


@pytest.fixture()
def client() -> TestClient:
    """Return a Starlette TestClient wrapping the FastAPI app."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _reset_test_state() -> None:
    """Ensure clean state for rate limiter, metrics, and locks before and after each test."""
    rate_limiter.reset()
    pipeline_metrics.reset()
    if render_lock.locked():
        try:
            render_lock.release()
        except RuntimeError:
            pass


def _patch_action_log(mocker: Any) -> None:
    """Mock ActionLogRepository.track_operation context manager."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=MagicMock())
    ctx.__exit__ = MagicMock(return_value=False)
    mocker.patch(
        "src.web.ActionLogRepository.track_operation",
        return_value=ctx,
    )


# ---------------------------------------------------------------------------
# Rate Limiting Tests
# ---------------------------------------------------------------------------


def test_heavy_rate_limit_exceeded_on_pipeline_run(client: TestClient, mocker: Any) -> None:
    """POST /api/pipeline/run limits to 5 runs per hour and rejects subsequent requests with 429."""
    mocker.patch(
        "src.web.run_video_pipeline",
        return_value={"video_path": "/fake/video.mp4"},
    )
    headers = {"X-Forwarded-For": "198.51.100.1"}

    for _ in range(5):
        resp = client.post("/api/pipeline/run", json={}, headers=headers)
        assert resp.status_code == 200

    resp_exceeded = client.post("/api/pipeline/run", json={}, headers=headers)
    assert resp_exceeded.status_code == 429
    assert "Rate limit exceeded for heavy execution endpoints" in resp_exceeded.json()["detail"]
    assert "Retry-After" in resp_exceeded.headers


def test_heavy_rate_limit_exceeded_on_cluster_run(client: TestClient, mocker: Any) -> None:
    """POST /api/pipeline/cluster/run enforces 5 runs per hour limit and returns 429."""
    mocker.patch("src.web.ClusteringService.generate_embeddings_for_new_articles", return_value=3)
    mocker.patch("src.web.ClusteringService.cluster_recent_articles", return_value=[])
    _patch_action_log(mocker)
    headers = {"X-Forwarded-For": "198.51.100.2"}

    for _ in range(5):
        resp = client.post("/api/pipeline/cluster/run", json={}, headers=headers)
        assert resp.status_code == 200

    resp_exceeded = client.post("/api/pipeline/cluster/run", json={}, headers=headers)
    assert resp_exceeded.status_code == 429
    assert "Rate limit exceeded" in resp_exceeded.json()["detail"]


def test_heavy_rate_limit_exceeded_on_pipeline_render(client: TestClient, mocker: Any) -> None:
    """POST /api/pipeline/render enforces 5 runs per hour limit and returns 429."""
    mocker.patch("src.web.JobQueueService.submit_render_job")
    headers = {"X-Forwarded-For": "198.51.100.3"}

    for _ in range(5):
        resp = client.post(
            "/api/pipeline/render",
            json={"job_id": 1, "async_mode": True},
            headers=headers,
        )
        assert resp.status_code == 202

    resp_exceeded = client.post(
        "/api/pipeline/render",
        json={"job_id": 1, "async_mode": True},
        headers=headers,
    )
    assert resp_exceeded.status_code == 429
    assert "Rate limit exceeded" in resp_exceeded.json()["detail"]


def test_heavy_rate_limit_distinct_client_ips(client: TestClient, mocker: Any) -> None:
    """Different client IPs maintain separate heavy rate limit buckets."""
    mocker.patch(
        "src.web.run_video_pipeline",
        return_value={"video_path": "/fake/video.mp4"},
    )
    headers_a = {"X-Forwarded-For": "198.51.100.4"}
    headers_b = {"X-Forwarded-For": "198.51.100.5"}

    for _ in range(5):
        resp = client.post("/api/pipeline/run", json={}, headers=headers_a)
        assert resp.status_code == 200

    resp_a_blocked = client.post("/api/pipeline/run", json={}, headers=headers_a)
    assert resp_a_blocked.status_code == 429

    resp_b_allowed = client.post("/api/pipeline/run", json={}, headers=headers_b)
    assert resp_b_allowed.status_code == 200


def test_read_rate_limit_exceeded(client: TestClient, mocker: Any) -> None:
    """Read endpoints return 429 when client IP exceeds rate limit."""
    mocker.patch.object(settings, "rate_limit_read_req_per_minute", 5)
    headers = {"X-Forwarded-For": "198.51.100.6"}

    for _ in range(5):
        resp = client.get("/api/budget", headers=headers)
        assert resp.status_code == 200

    resp_exceeded = client.get("/api/budget", headers=headers)
    assert resp_exceeded.status_code == 429
    assert "Rate limit exceeded for read endpoints" in resp_exceeded.json()["detail"]
    assert "Retry-After" in resp_exceeded.headers


def test_read_rate_limit_distinct_client_ips(client: TestClient, mocker: Any) -> None:
    """Different client IPs maintain separate read rate limit buckets."""
    mocker.patch.object(settings, "rate_limit_read_req_per_minute", 3)
    headers_a = {"X-Forwarded-For": "198.51.100.7"}
    headers_b = {"X-Forwarded-For": "198.51.100.8"}

    for _ in range(3):
        resp = client.get("/api/budget", headers=headers_a)
        assert resp.status_code == 200

    assert client.get("/api/budget", headers=headers_a).status_code == 429
    assert client.get("/api/budget", headers=headers_b).status_code == 200


def test_rate_limit_disabled_flag(client: TestClient, mocker: Any) -> None:
    """When rate_limit_enabled is False, requests beyond limit are allowed."""
    mocker.patch.object(settings, "rate_limit_enabled", False)
    mocker.patch(
        "src.web.run_video_pipeline",
        return_value={"video_path": "/fake/video.mp4"},
    )
    headers = {"X-Forwarded-For": "198.51.100.9"}

    for _ in range(7):
        resp = client.post("/api/pipeline/run", json={}, headers=headers)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Cost Guardrail Enforcement Tests
# ---------------------------------------------------------------------------


def test_cost_guardrail_blocks_pipeline_run(client: TestClient, mocker: Any) -> None:
    """POST /api/pipeline/run aborts with 429 when budget cap is exceeded."""
    mocker.patch.object(
        cost_guardrail,
        "can_proceed",
        return_value=(False, "Daily spend cap reached: $10.50 >= $10.00"),
    )
    mock_run = mocker.patch("src.web.run_video_pipeline")

    resp = client.post("/api/pipeline/run", json={})
    assert resp.status_code == 429
    assert "Daily spend cap reached: $10.50 >= $10.00" in resp.json()["detail"]
    mock_run.assert_not_called()


def test_cost_guardrail_blocks_cluster_run(client: TestClient, mocker: Any) -> None:
    """POST /api/pipeline/cluster/run aborts with 429 when budget cap is reached."""
    mocker.patch.object(
        cost_guardrail,
        "can_proceed",
        return_value=(False, "Monthly spend cap reached: $55.00 >= $50.00"),
    )
    mock_service = mocker.patch("src.web.ClusteringService")

    resp = client.post("/api/pipeline/cluster/run", json={})
    assert resp.status_code == 429
    assert "Monthly spend cap reached: $55.00 >= $50.00" in resp.json()["detail"]
    mock_service.assert_not_called()


def test_cost_guardrail_blocks_pipeline_render(client: TestClient, mocker: Any) -> None:
    """POST /api/pipeline/render aborts with 429 when budget cap is exceeded."""
    mocker.patch.object(
        cost_guardrail,
        "can_proceed",
        return_value=(False, "Daily spend cap reached: $12.00 >= $10.00"),
    )
    mock_render_svc = mocker.patch("src.web.RenderService")

    resp = client.post("/api/pipeline/render", json={"job_id": 1, "async_mode": False})
    assert resp.status_code == 429
    assert "Daily spend cap reached: $12.00 >= $10.00" in resp.json()["detail"]
    mock_render_svc.assert_not_called()


def test_cost_guardrail_allows_execution_when_within_budget(
    client: TestClient, mocker: Any
) -> None:
    """Execution proceeds normally when budget is within limits."""
    mocker.patch.object(cost_guardrail, "can_proceed", return_value=(True, None))
    mocker.patch(
        "src.web.run_video_pipeline",
        return_value={"video_path": "/fake/video.mp4"},
    )

    resp = client.post("/api/pipeline/run", json={})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"


# ---------------------------------------------------------------------------
# Render Concurrency Lock Tests
# ---------------------------------------------------------------------------


def test_render_concurrency_lock_rejects_second_render(client: TestClient) -> None:
    """POST /api/pipeline/render returns 409 Conflict when a render is in progress."""
    acquired = render_lock.acquire(blocking=False)
    assert acquired is True

    try:
        resp = client.post(
            "/api/pipeline/render",
            json={"job_id": 1, "async_mode": False},
        )
        assert resp.status_code == 409
        assert "already in progress" in resp.json()["detail"].lower()
    finally:
        render_lock.release()


def test_re_render_concurrency_lock_rejects_concurrent_run(client: TestClient) -> None:
    """POST /api/jobs/{id}/re-render returns 409 Conflict when render is in progress."""
    acquired = render_lock.acquire(blocking=False)
    assert acquired is True

    try:
        resp = client.post(
            "/api/jobs/1/re-render",
            json={"dry_run": False},
        )
        assert resp.status_code == 409
        assert "already in progress" in resp.json()["detail"].lower()
    finally:
        render_lock.release()


def test_render_lock_released_on_render_failure(client: TestClient, mocker: Any) -> None:
    """Render lock is released even if render execution fails with an error."""
    mock_job = MagicMock(
        id=1, script_id=1, audio_path="", duration_seconds=30.0, captions_path=None
    )
    mock_script = MagicMock(id=1, full_narration="Sample narration", beats=[])
    mocker.patch("src.web.RenderRepository.get_job_by_id", return_value=mock_job)
    mocker.patch("src.web.ScriptRepository.get_script_by_id", return_value=mock_script)
    mocker.patch("src.web.CaptionService.generate_captions", return_value=(None, []))
    mocker.patch("src.web.MediaService.process_media_for_job", return_value=[])
    mocker.patch("src.web.RenderService.prepare_render_props")
    mocker.patch(
        "src.web.RenderService.execute_render",
        side_effect=RuntimeError("Remotion binary crashed"),
    )
    _patch_action_log(mocker)

    resp = client.post(
        "/api/pipeline/render",
        json={"job_id": 1, "async_mode": False},
    )
    assert resp.status_code == 500
    assert render_lock.locked() is False


# ---------------------------------------------------------------------------
# Prometheus Metrics Tests
# ---------------------------------------------------------------------------


def test_prometheus_metrics_endpoint_headers_and_types(client: TestClient) -> None:
    """GET /metrics returns 200 with Prometheus text/plain format and all required metrics."""
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    body = resp.text

    assert "# HELP ai_video_pipeline_runs_total" in body
    assert "# TYPE ai_video_pipeline_runs_total counter" in body
    assert 'ai_video_pipeline_runs_total{status="success"}' in body
    assert 'ai_video_pipeline_runs_total{status="failure"}' in body

    assert "# HELP ai_video_pipeline_duration_seconds" in body
    assert "# TYPE ai_video_pipeline_duration_seconds gauge" in body
    for stage in ["ingestion", "clustering", "script", "tts", "caption", "render"]:
        assert f'ai_video_pipeline_duration_seconds{{stage="{stage}"}}' in body

    assert "# HELP ai_video_total_spend_usd" in body
    assert "# TYPE ai_video_total_spend_usd gauge" in body
    assert "ai_video_total_spend_usd" in body

    assert "# HELP ai_video_daily_budget_usd" in body
    assert "# TYPE ai_video_daily_budget_usd gauge" in body
    assert "ai_video_daily_budget_usd" in body

    assert "# HELP ai_video_active_render_jobs" in body
    assert "# TYPE ai_video_active_render_jobs gauge" in body
    assert "ai_video_active_render_jobs" in body


def test_prometheus_metrics_pipeline_run_counters(client: TestClient, mocker: Any) -> None:
    """Pipeline run success and failure increment respective Prometheus counters."""
    mocker.patch(
        "src.web.run_video_pipeline",
        return_value={"video_path": "/fake/video.mp4"},
    )
    client.post("/api/pipeline/run", json={})
    metrics_text = client.get("/metrics").text
    assert 'ai_video_pipeline_runs_total{status="success"} 1' in metrics_text
    assert 'ai_video_pipeline_runs_total{status="failure"} 0' in metrics_text

    mocker.patch(
        "src.web.run_video_pipeline",
        side_effect=RuntimeError("Pipeline execution failed"),
    )
    client.post("/api/pipeline/run", json={})
    metrics_text2 = client.get("/metrics").text
    assert 'ai_video_pipeline_runs_total{status="success"} 1' in metrics_text2
    assert 'ai_video_pipeline_runs_total{status="failure"} 1' in metrics_text2


def test_prometheus_metrics_active_render_jobs_reflects_lock(client: TestClient) -> None:
    """ai_video_active_render_jobs gauge is 1 while render lock is held and 0 when released."""
    metrics_idle = client.get("/metrics").text
    assert "ai_video_active_render_jobs 0" in metrics_idle

    acquired = render_lock.acquire(blocking=False)
    assert acquired is True
    try:
        metrics_busy = client.get("/metrics").text
        assert "ai_video_active_render_jobs 1" in metrics_busy
    finally:
        render_lock.release()

    metrics_released = client.get("/metrics").text
    assert "ai_video_active_render_jobs 0" in metrics_released


def test_prometheus_metrics_stage_duration_recording(client: TestClient) -> None:
    """Stage durations recorded by collector are reflected in Prometheus output."""
    pipeline_metrics.record_stage_duration("render", 12.345)
    pipeline_metrics.record_stage_duration("clustering", 3.21)

    body = client.get("/metrics").text
    assert 'ai_video_pipeline_duration_seconds{stage="render"} 12.3450' in body
    assert 'ai_video_pipeline_duration_seconds{stage="clustering"} 3.2100' in body


def test_prometheus_metrics_budget_and_spend_values(client: TestClient, mocker: Any) -> None:
    """GET /metrics accurately reports configured daily budget and total spend."""
    mocker.patch.object(settings, "cost_daily_budget_usd", 25.50)
    mocker.patch("src.web.CostRepository.get_total_spend", return_value=7.89)

    body = client.get("/metrics").text
    assert "ai_video_daily_budget_usd 25.5000" in body
    assert "ai_video_total_spend_usd 7.8900" in body
