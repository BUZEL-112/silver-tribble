"""QA tests for HealthService diagnostic checks and run_health_check() aggregation.

Coverage:
- check_database() returns HealthComponentStatus with status='healthy' on successful query
- check_database() returns status='unhealthy' when the session raises
- check_storage() returns status='healthy' when directories are writable
- check_storage() returns status='unhealthy' when a directory write fails
- run_health_check() returns a HealthStatus with all expected component names
- HealthStatus schema carries database, storage keys and an overall status
- checks_passed and total_checks counts are consistent with component results
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models.schemas import HealthComponentStatus, HealthStatus
from src.services.health_service import HealthService

# ---------------------------------------------------------------------------
# check_database()
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_check_database_reachable_returns_healthy_status() -> None:
    """check_database() must return status='healthy' when the DB executes SELECT 1."""
    service = HealthService()

    mock_session = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_session)
    mock_ctx.__exit__ = MagicMock(return_value=False)

    with patch("src.services.health_service.get_session", return_value=mock_ctx):
        result = service.check_database()

    assert isinstance(result, HealthComponentStatus)
    assert result.status == "healthy"
    assert result.name == "database"


@pytest.mark.unit
def test_check_database_session_raises_returns_unhealthy_status() -> None:
    """check_database() must catch exceptions and return status='unhealthy'."""
    service = HealthService()

    with patch(
        "src.services.health_service.get_session", side_effect=RuntimeError("connection refused")
    ):
        result = service.check_database()

    assert result.status == "unhealthy"
    assert "connection refused" in result.details


@pytest.mark.unit
def test_check_database_result_is_health_component_status_instance() -> None:
    """check_database() must always return a HealthComponentStatus, not a raw dict."""
    service = HealthService()

    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=MagicMock())
    mock_ctx.__exit__ = MagicMock(return_value=False)

    with patch("src.services.health_service.get_session", return_value=mock_ctx):
        result = service.check_database()

    assert isinstance(result, HealthComponentStatus)


# ---------------------------------------------------------------------------
# check_storage()
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_check_storage_writable_directories_returns_healthy(tmp_path: Path) -> None:
    """check_storage() must return status='healthy' when all dirs are writable."""
    service = HealthService()

    mock_settings = MagicMock()
    mock_settings.storage_local_dir = tmp_path / "assets"
    mock_settings.media_cache_dir = tmp_path / "cache"
    mock_settings.remotion_output_dir = tmp_path / "output"

    with patch("src.services.health_service.settings", mock_settings):
        result = service.check_storage()

    assert result.status == "healthy"
    assert result.name == "storage"


@pytest.mark.unit
def test_check_storage_unwritable_directory_returns_unhealthy(tmp_path: Path) -> None:
    """check_storage() must return status='unhealthy' if any directory write fails."""
    service = HealthService()

    bad_dir = MagicMock(spec=Path)
    bad_dir.__truediv__ = MagicMock(return_value=bad_dir)
    bad_dir.mkdir = MagicMock(side_effect=PermissionError("read-only filesystem"))

    mock_settings = MagicMock()
    mock_settings.storage_local_dir = bad_dir
    mock_settings.media_cache_dir = tmp_path / "cache"
    mock_settings.remotion_output_dir = tmp_path / "output"

    with patch("src.services.health_service.settings", mock_settings):
        result = service.check_storage()

    assert result.status == "unhealthy"
    assert result.name == "storage"


@pytest.mark.unit
def test_check_storage_result_is_health_component_status_instance(tmp_path: Path) -> None:
    """check_storage() must always return a HealthComponentStatus."""
    service = HealthService()

    mock_settings = MagicMock()
    mock_settings.storage_local_dir = tmp_path / "s"
    mock_settings.media_cache_dir = tmp_path / "m"
    mock_settings.remotion_output_dir = tmp_path / "r"

    with patch("src.services.health_service.settings", mock_settings):
        result = service.check_storage()

    assert isinstance(result, HealthComponentStatus)


# ---------------------------------------------------------------------------
# run_health_check() aggregation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_health_check_returns_health_status_instance() -> None:
    """run_health_check() must return a HealthStatus schema object."""
    service = HealthService()

    healthy = HealthComponentStatus(name="x", status="healthy", details="ok")

    with (
        patch.object(service, "check_database", return_value=healthy),
        patch.object(service, "check_storage", return_value=healthy),
        patch.object(service, "check_ffmpeg", return_value=healthy),
        patch.object(service, "check_node_and_remotion", return_value=healthy),
        patch.object(service, "check_providers", return_value=healthy),
    ):
        result = service.run_health_check()

    assert isinstance(result, HealthStatus)


@pytest.mark.unit
def test_run_health_check_all_healthy_overall_status_is_healthy() -> None:
    """When every component is healthy, the overall status must be 'healthy'."""
    service = HealthService()

    healthy = HealthComponentStatus(name="x", status="healthy", details="ok")

    with (
        patch.object(service, "check_database", return_value=healthy),
        patch.object(service, "check_storage", return_value=healthy),
        patch.object(service, "check_ffmpeg", return_value=healthy),
        patch.object(service, "check_node_and_remotion", return_value=healthy),
        patch.object(service, "check_providers", return_value=healthy),
    ):
        result = service.run_health_check()

    assert result.status == "healthy"


@pytest.mark.unit
def test_run_health_check_one_unhealthy_overall_status_is_unhealthy() -> None:
    """Any unhealthy component must pull the overall status to 'unhealthy'."""
    service = HealthService()

    healthy = HealthComponentStatus(name="x", status="healthy", details="ok")
    unhealthy = HealthComponentStatus(name="database", status="unhealthy", details="down")

    with (
        patch.object(service, "check_database", return_value=unhealthy),
        patch.object(service, "check_storage", return_value=healthy),
        patch.object(service, "check_ffmpeg", return_value=healthy),
        patch.object(service, "check_node_and_remotion", return_value=healthy),
        patch.object(service, "check_providers", return_value=healthy),
    ):
        result = service.run_health_check()

    assert result.status == "unhealthy"


@pytest.mark.unit
def test_run_health_check_one_degraded_overall_status_is_degraded() -> None:
    """A degraded component with no unhealthy ones must yield overall status='degraded'."""
    service = HealthService()

    healthy = HealthComponentStatus(name="x", status="healthy", details="ok")
    degraded = HealthComponentStatus(name="remotion", status="degraded", details="slow")

    with (
        patch.object(service, "check_database", return_value=healthy),
        patch.object(service, "check_storage", return_value=healthy),
        patch.object(service, "check_ffmpeg", return_value=healthy),
        patch.object(service, "check_node_and_remotion", return_value=degraded),
        patch.object(service, "check_providers", return_value=healthy),
    ):
        result = service.run_health_check()

    assert result.status == "degraded"


@pytest.mark.unit
def test_run_health_check_response_contains_database_and_storage_components() -> None:
    """run_health_check() result must include components named 'database' and 'storage'."""
    service = HealthService()

    db_status = HealthComponentStatus(name="database", status="healthy", details="ok")
    storage_status = HealthComponentStatus(name="storage", status="healthy", details="ok")
    other = HealthComponentStatus(name="other", status="healthy", details="ok")

    with (
        patch.object(service, "check_database", return_value=db_status),
        patch.object(service, "check_storage", return_value=storage_status),
        patch.object(service, "check_ffmpeg", return_value=other),
        patch.object(service, "check_node_and_remotion", return_value=other),
        patch.object(service, "check_providers", return_value=other),
    ):
        result = service.run_health_check()

    component_names = {c.name for c in result.components}
    assert "database" in component_names
    assert "storage" in component_names


@pytest.mark.unit
def test_run_health_check_checks_passed_count_matches_healthy_components() -> None:
    """checks_passed must equal the number of components with status='healthy'."""
    service = HealthService()

    healthy = HealthComponentStatus(name="x", status="healthy", details="ok")
    unhealthy = HealthComponentStatus(name="y", status="unhealthy", details="down")

    with (
        patch.object(service, "check_database", return_value=healthy),
        patch.object(service, "check_storage", return_value=healthy),
        patch.object(service, "check_ffmpeg", return_value=unhealthy),
        patch.object(service, "check_node_and_remotion", return_value=healthy),
        patch.object(service, "check_providers", return_value=healthy),
    ):
        result = service.run_health_check()

    assert result.checks_passed == 4
    assert result.total_checks == 5


@pytest.mark.unit
def test_run_health_check_total_checks_equals_number_of_components() -> None:
    """total_checks must equal the length of the components list."""
    service = HealthService()

    healthy = HealthComponentStatus(name="x", status="healthy", details="ok")

    with (
        patch.object(service, "check_database", return_value=healthy),
        patch.object(service, "check_storage", return_value=healthy),
        patch.object(service, "check_ffmpeg", return_value=healthy),
        patch.object(service, "check_node_and_remotion", return_value=healthy),
        patch.object(service, "check_providers", return_value=healthy),
    ):
        result = service.run_health_check()

    assert result.total_checks == len(result.components)
