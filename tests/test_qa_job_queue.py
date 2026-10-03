"""QA tests for JobQueueService and CachePruningService.

JobQueueService coverage:
- submit_render_job() registers the job and sets initial state to 'queued'
- submit_pipeline_job() creates a DB record and returns an integer job_id
- get_progress() returns None for an unknown job_id
- get_progress() returns a dict for a known in-flight job_id
- Multiple submit calls produce unique job identifiers
- Concurrent submit_render_job() calls do not collide on job ids

CachePruningService coverage:
- prune_cache() returns a PruneResult with files_deleted count
- prune_cache() returns files_deleted=0 when the cache directory is empty
- prune_cache() deletes files whose mtime exceeds the retention window
- prune_cache() skips files that are still within the retention window
- prune_cache() on a non-existent directory returns zeroed PruneResult
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models.schemas import PruneResult
from src.services.cache_pruning_service import CachePruningService
from src.services.job_queue_service import JobQueueService, _live_progress, _progress_lock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_live_progress(job_id: int) -> None:
    """Remove a job_id entry from the module-level progress tracker."""
    with _progress_lock:
        _live_progress.pop(job_id, None)


def _make_mock_session_ctx(session: MagicMock) -> MagicMock:
    """Wrap a mock Session in a context-manager mock."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


# ---------------------------------------------------------------------------
# JobQueueService -- submit_render_job()
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_submit_render_job_registers_job_in_queued_state() -> None:
    """submit_render_job() must store job progress with status='queued' immediately."""
    service = JobQueueService()
    job_id = 9001

    mock_session = MagicMock()
    mock_render_repo = MagicMock()
    mock_session_ctx = _make_mock_session_ctx(mock_session)

    with (
        patch("src.services.job_queue_service.get_session", return_value=mock_session_ctx),
        patch("src.services.job_queue_service.RenderRepository", return_value=mock_render_repo),
        patch("src.services.job_queue_service._executor") as mock_executor,
    ):
        mock_executor.submit = MagicMock()

        service.submit_render_job(job_id=job_id, dry_run=True)

    try:
        with _progress_lock:
            progress = dict(_live_progress.get(job_id, {}))

        assert progress.get("status") == "queued"
        assert progress.get("job_id") == job_id
    finally:
        _clear_live_progress(job_id)


@pytest.mark.unit
def test_submit_render_job_dispatches_worker_to_executor() -> None:
    """submit_render_job() must schedule the render task on the thread executor."""
    service = JobQueueService()
    job_id = 9002

    mock_session = MagicMock()
    mock_render_repo = MagicMock()
    mock_session_ctx = _make_mock_session_ctx(mock_session)

    try:
        with (
            patch("src.services.job_queue_service.get_session", return_value=mock_session_ctx),
            patch("src.services.job_queue_service.RenderRepository", return_value=mock_render_repo),
            patch("src.services.job_queue_service._executor") as mock_executor,
        ):
            mock_executor.submit = MagicMock()

            service.submit_render_job(job_id=job_id, dry_run=True)

            mock_executor.submit.assert_called_once()
    finally:
        _clear_live_progress(job_id)


# ---------------------------------------------------------------------------
# JobQueueService -- submit_pipeline_job()
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_submit_pipeline_job_returns_integer_job_id() -> None:
    """submit_pipeline_job() must return the created integer job_id immediately."""
    service = JobQueueService()

    mock_job = MagicMock()
    mock_job.id = 42
    mock_job.status = "queued"

    mock_render_repo = MagicMock()
    mock_render_repo.create_job = MagicMock(return_value=mock_job)

    mock_session = MagicMock()
    mock_session_ctx = _make_mock_session_ctx(mock_session)

    mock_cost_repo = MagicMock()
    mock_cost_repo.get_total_spend = MagicMock(return_value=0.0)

    with (
        patch("src.services.job_queue_service.get_session", return_value=mock_session_ctx),
        patch("src.services.job_queue_service.RenderRepository", return_value=mock_render_repo),
        patch("src.services.job_queue_service.CostRepository", return_value=mock_cost_repo),
        patch("src.services.job_queue_service._executor") as mock_executor,
        patch.object(service, "_check_budget_limits", return_value=(True, None)),
    ):
        mock_executor.submit = MagicMock()

        job_id = service.submit_pipeline_job(dry_run=True)

    assert isinstance(job_id, int)
    _clear_live_progress(job_id)


@pytest.mark.unit
def test_submit_pipeline_job_initial_state_is_queued() -> None:
    """Job state stored by submit_pipeline_job() must have status='queued'."""
    service = JobQueueService()

    mock_job = MagicMock()
    mock_job.id = 77
    mock_job.status = "queued"

    mock_render_repo = MagicMock()
    mock_render_repo.create_job = MagicMock(return_value=mock_job)

    mock_session = MagicMock()
    mock_session_ctx = _make_mock_session_ctx(mock_session)

    mock_cost_repo = MagicMock()

    with (
        patch("src.services.job_queue_service.get_session", return_value=mock_session_ctx),
        patch("src.services.job_queue_service.RenderRepository", return_value=mock_render_repo),
        patch("src.services.job_queue_service.CostRepository", return_value=mock_cost_repo),
        patch("src.services.job_queue_service._executor") as mock_executor,
        patch.object(service, "_check_budget_limits", return_value=(True, None)),
    ):
        mock_executor.submit = MagicMock()

        job_id = service.submit_pipeline_job(dry_run=True)

    try:
        with _progress_lock:
            progress = dict(_live_progress.get(job_id, {}))

        assert progress.get("status") == "queued"
    finally:
        _clear_live_progress(job_id)


@pytest.mark.unit
def test_submit_pipeline_job_budget_exceeded_raises_value_error() -> None:
    """submit_pipeline_job() must raise ValueError when the budget check fails."""
    service = JobQueueService()

    with patch.object(
        service,
        "_check_budget_limits",
        return_value=(False, "Daily budget exceeded"),
    ):
        with pytest.raises(ValueError, match="Daily budget exceeded"):
            service.submit_pipeline_job()


# ---------------------------------------------------------------------------
# JobQueueService -- get_progress()
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_progress_returns_none_for_unknown_job_id() -> None:
    """get_progress() must return None when the job_id has no record anywhere."""
    unknown_id = 999999

    mock_render_repo = MagicMock()
    mock_render_repo.get_job_by_id = MagicMock(return_value=None)

    mock_session = MagicMock()
    mock_session_ctx = _make_mock_session_ctx(mock_session)

    with (
        patch("src.services.job_queue_service.get_session", return_value=mock_session_ctx),
        patch("src.services.job_queue_service.RenderRepository", return_value=mock_render_repo),
    ):
        result = JobQueueService.get_progress(unknown_id)

    assert result is None


@pytest.mark.unit
def test_get_progress_returns_dict_for_in_flight_job() -> None:
    """get_progress() must return a dict when the job_id exists in the live tracker."""
    job_id = 8001
    with _progress_lock:
        _live_progress[job_id] = {
            "job_id": job_id,
            "stage": "rendering",
            "percent": 50,
            "message": "halfway",
            "status": "running",
            "error": None,
            "output_video_path": None,
            "updated_at": "2026-01-01T00:00:00+00:00",
        }

    try:
        result = JobQueueService.get_progress(job_id)

        assert isinstance(result, dict)
        assert result["job_id"] == job_id
        assert result["status"] == "running"
    finally:
        _clear_live_progress(job_id)


@pytest.mark.unit
def test_get_progress_live_result_is_a_copy_not_a_reference() -> None:
    """get_progress() must return a snapshot copy, not a mutable reference."""
    job_id = 8002
    with _progress_lock:
        _live_progress[job_id] = {
            "job_id": job_id,
            "stage": "rendering",
            "percent": 20,
            "message": "going",
            "status": "running",
            "error": None,
            "output_video_path": None,
            "updated_at": "2026-01-01T00:00:00+00:00",
        }

    try:
        result = JobQueueService.get_progress(job_id)
        assert result is not None
        result["status"] = "MUTATED"

        with _progress_lock:
            assert _live_progress[job_id]["status"] == "running"
    finally:
        _clear_live_progress(job_id)


# ---------------------------------------------------------------------------
# JobQueueService -- unique IDs across multiple submissions
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_submit_pipeline_job_multiple_calls_produce_unique_ids() -> None:
    """Each call to submit_pipeline_job() must return a distinct job_id."""
    service = JobQueueService()
    collected_ids: list[int] = []

    for counter in range(3):
        fake_id = 100 + counter
        mock_job = MagicMock()
        mock_job.id = fake_id
        mock_job.status = "queued"

        mock_render_repo = MagicMock()
        mock_render_repo.create_job = MagicMock(return_value=mock_job)

        mock_session = MagicMock()
        mock_session_ctx = _make_mock_session_ctx(mock_session)

        mock_cost_repo = MagicMock()

        with (
            patch("src.services.job_queue_service.get_session", return_value=mock_session_ctx),
            patch("src.services.job_queue_service.RenderRepository", return_value=mock_render_repo),
            patch("src.services.job_queue_service.CostRepository", return_value=mock_cost_repo),
            patch("src.services.job_queue_service._executor") as mock_executor,
            patch.object(service, "_check_budget_limits", return_value=(True, None)),
        ):
            mock_executor.submit = MagicMock()
            job_id = service.submit_pipeline_job(dry_run=True)

        collected_ids.append(job_id)

    for jid in collected_ids:
        _clear_live_progress(jid)

    assert len(set(collected_ids)) == len(collected_ids), "Duplicate job ids detected"


# ---------------------------------------------------------------------------
# JobQueueService -- concurrency: no id collisions under parallel submit
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_submit_render_job_concurrent_calls_do_not_collide_on_ids() -> None:
    """Parallel submit_render_job() invocations must each register their own progress entry."""
    service = JobQueueService()
    job_ids = [7001, 7002, 7003]
    errors: list[str] = []

    def _submit(jid: int) -> None:
        mock_session = MagicMock()
        mock_render_repo = MagicMock()
        mock_session_ctx = _make_mock_session_ctx(mock_session)

        with (
            patch("src.services.job_queue_service.get_session", return_value=mock_session_ctx),
            patch("src.services.job_queue_service.RenderRepository", return_value=mock_render_repo),
            patch("src.services.job_queue_service._executor") as mock_executor,
        ):
            mock_executor.submit = MagicMock()
            service.submit_render_job(job_id=jid, dry_run=True)

        with _progress_lock:
            if jid not in _live_progress:
                errors.append(f"job_id {jid} missing from _live_progress")

    threads = [threading.Thread(target=_submit, args=(jid,)) for jid in job_ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for jid in job_ids:
        _clear_live_progress(jid)

    assert errors == [], f"Concurrency errors: {errors}"


# ---------------------------------------------------------------------------
# CachePruningService
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_prune_cache_returns_prune_result_schema(tmp_path: Path) -> None:
    """prune_cache() must return a PruneResult instance."""
    service = CachePruningService(asset_repo=None)

    result = service.prune_cache(retention_hours=0.0, target_dir=tmp_path)

    assert isinstance(result, PruneResult)


@pytest.mark.unit
def test_prune_cache_empty_directory_returns_zero_deleted(tmp_path: Path) -> None:
    """prune_cache() on an empty directory must report files_deleted=0."""
    service = CachePruningService(asset_repo=None)

    result = service.prune_cache(retention_hours=24.0, target_dir=tmp_path)

    assert result.files_deleted == 0
    assert result.files_scanned == 0


@pytest.mark.unit
def test_prune_cache_nonexistent_directory_returns_zeroed_result() -> None:
    """prune_cache() on a missing directory must return all-zero PruneResult without raising."""
    service = CachePruningService(asset_repo=None)
    missing_dir = Path("/tmp/this_path_does_not_exist_qa_test_xyz")

    result = service.prune_cache(retention_hours=1.0, target_dir=missing_dir)

    assert result.files_scanned == 0
    assert result.files_deleted == 0
    assert result.bytes_freed == 0


@pytest.mark.unit
def test_prune_cache_deletes_files_older_than_retention_window(tmp_path: Path) -> None:
    """prune_cache() must delete files whose mtime predates the retention cutoff."""
    service = CachePruningService(asset_repo=None)

    old_file = tmp_path / "old.mp4"
    old_file.write_bytes(b"stale data")

    # Force mtime to two days ago
    two_days_ago = time.time() - (2 * 24 * 3600)
    import os

    os.utime(old_file, (two_days_ago, two_days_ago))

    result = service.prune_cache(retention_hours=24.0, target_dir=tmp_path)

    assert result.files_deleted >= 1
    assert not old_file.exists()


@pytest.mark.unit
def test_prune_cache_does_not_delete_recent_files(tmp_path: Path) -> None:
    """prune_cache() must leave files within the retention window untouched."""
    service = CachePruningService(asset_repo=None)

    recent_file = tmp_path / "recent.mp4"
    recent_file.write_bytes(b"fresh data")

    result = service.prune_cache(retention_hours=24.0, target_dir=tmp_path)

    assert result.files_deleted == 0
    assert recent_file.exists()


@pytest.mark.unit
def test_prune_cache_dry_run_does_not_remove_files(tmp_path: Path) -> None:
    """dry_run=True must count files that would be deleted but leave them on disk."""
    service = CachePruningService(asset_repo=None)

    old_file = tmp_path / "stale.bin"
    old_file.write_bytes(b"content")

    import os

    old_time = time.time() - (48 * 3600)
    os.utime(old_file, (old_time, old_time))

    result = service.prune_cache(retention_hours=1.0, target_dir=tmp_path, dry_run=True)

    assert result.files_deleted >= 1
    assert old_file.exists(), "dry_run must not actually delete the file"


@pytest.mark.unit
def test_prune_cache_bytes_freed_reflects_deleted_file_sizes(tmp_path: Path) -> None:
    """bytes_freed in the PruneResult must equal the combined size of deleted files."""
    service = CachePruningService(asset_repo=None)

    payload = b"x" * 1024  # 1 KB
    old_file = tmp_path / "data.bin"
    old_file.write_bytes(payload)

    import os

    old_time = time.time() - (25 * 3600)
    os.utime(old_file, (old_time, old_time))

    result = service.prune_cache(retention_hours=24.0, target_dir=tmp_path)

    assert result.bytes_freed == len(payload)


@pytest.mark.unit
def test_prune_cache_protected_assets_are_not_deleted(tmp_path: Path) -> None:
    """Files tracked in the asset library must never be removed by prune_cache()."""
    old_file = tmp_path / "protected.mp4"
    old_file.write_bytes(b"library asset")

    import os

    old_time = time.time() - (48 * 3600)
    os.utime(old_file, (old_time, old_time))

    mock_asset = MagicMock()
    mock_asset.local_path = str(old_file)

    mock_asset_repo = MagicMock()
    mock_asset_repo.list_assets = MagicMock(return_value=[mock_asset])

    service = CachePruningService(asset_repo=mock_asset_repo)

    result = service.prune_cache(retention_hours=1.0, target_dir=tmp_path)

    assert old_file.exists(), "Protected library asset was incorrectly pruned"
    assert result.files_deleted == 0


@pytest.mark.unit
def test_prune_cache_temp_artifacts_always_deleted_regardless_of_age(tmp_path: Path) -> None:
    """Files ending in .tmp or .part must be removed even if they are brand-new."""
    service = CachePruningService(asset_repo=None)

    temp_file = tmp_path / "download.tmp"
    temp_file.write_bytes(b"incomplete chunk")

    result = service.prune_cache(retention_hours=9999.0, target_dir=tmp_path)

    assert result.files_deleted >= 1
    assert not temp_file.exists()
