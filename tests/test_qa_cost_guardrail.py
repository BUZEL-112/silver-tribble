"""Tests for CostGuardrailService in src/services/cost_guardrail_service.py.

Covers get_budget_status(), can_proceed(), send_alert() unit tests, and
budget enforcement integration tests. Uses mocker to isolate external
dependencies (get_session, httpx.Client.post, ActionLogRepository).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from src.models.schemas import CostLogCreate
from src.repositories.cost_repository import CostRepository
from src.services.cost_guardrail_service import CostGuardrailService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(cost_usd: float, stage: str = "script") -> CostLogCreate:
    """Build a minimal CostLogCreate for seeding spend totals."""
    return CostLogCreate(
        stage=stage,
        provider="openai",
        model="gpt-4o-mini",
        units=1000.0,
        unit_type="tokens",
        cost_usd=cost_usd,
    )


def _service_with_mocked_session(
    mocker: Any,
    total_spend: float,
    *,
    webhook_url: str | None = None,
) -> CostGuardrailService:
    """Return a CostGuardrailService whose get_session is replaced by a mock.

    The mock session always reports ``total_spend`` from CostRepository.get_total_spend.
    """
    mock_session = MagicMock()
    mock_cost_repo = MagicMock()
    mock_cost_repo.get_total_spend.return_value = total_spend

    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_session)
    mock_ctx.__exit__ = MagicMock(return_value=False)

    mocker.patch(
        "src.services.cost_guardrail_service.get_session",
        return_value=mock_ctx,
    )
    mocker.patch(
        "src.services.cost_guardrail_service.CostRepository",
        return_value=mock_cost_repo,
    )

    svc = CostGuardrailService(webhook_url=webhook_url)
    return svc


# ---------------------------------------------------------------------------
# get_budget_status() -- unit
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_budget_status_total_spend_rounded_to_4_decimal_places(mocker: Any) -> None:
    """get_budget_status() rounds total_spend_usd to exactly 4 decimal places."""
    svc = _service_with_mocked_session(mocker, total_spend=0.123456789)

    mocker.patch("src.services.cost_guardrail_service.settings")
    import src.services.cost_guardrail_service as svc_module

    svc_module.settings.cost_daily_budget_usd = None
    svc_module.settings.cost_monthly_budget_usd = None

    status = svc.get_budget_status()

    assert status["total_spend_usd"] == round(0.123456789, 4)


@pytest.mark.unit
def test_get_budget_status_daily_percent_zero_when_daily_cap_is_none(mocker: Any) -> None:
    """get_budget_status() returns daily_percent=0 when daily_cap is None."""
    import src.services.cost_guardrail_service as svc_module

    svc = _service_with_mocked_session(mocker, total_spend=5.0)
    mocker.patch.object(svc_module, "settings")
    svc_module.settings.cost_daily_budget_usd = None
    svc_module.settings.cost_monthly_budget_usd = None

    status = svc.get_budget_status()

    assert status["daily_percent"] == 0.0


@pytest.mark.unit
def test_get_budget_status_monthly_percent_zero_when_monthly_cap_is_none(mocker: Any) -> None:
    """get_budget_status() returns monthly_percent=0 when monthly_cap is None."""
    import src.services.cost_guardrail_service as svc_module

    svc = _service_with_mocked_session(mocker, total_spend=5.0)
    mocker.patch.object(svc_module, "settings")
    svc_module.settings.cost_daily_budget_usd = None
    svc_module.settings.cost_monthly_budget_usd = None

    status = svc.get_budget_status()

    assert status["monthly_percent"] == 0.0


@pytest.mark.unit
def test_get_budget_status_daily_percent_calculated_correctly(mocker: Any) -> None:
    """get_budget_status() computes correct daily_percent when daily_cap is set."""
    import src.services.cost_guardrail_service as svc_module

    svc = _service_with_mocked_session(mocker, total_spend=3.0)
    mocker.patch.object(svc_module, "settings")
    svc_module.settings.cost_daily_budget_usd = 10.0
    svc_module.settings.cost_monthly_budget_usd = None

    status = svc.get_budget_status()

    assert status["daily_percent"] == pytest.approx(30.0, rel=0.01)


@pytest.mark.unit
def test_get_budget_status_monthly_percent_calculated_correctly(mocker: Any) -> None:
    """get_budget_status() computes correct monthly_percent when monthly_cap is set."""
    import src.services.cost_guardrail_service as svc_module

    svc = _service_with_mocked_session(mocker, total_spend=25.0)
    mocker.patch.object(svc_module, "settings")
    svc_module.settings.cost_daily_budget_usd = None
    svc_module.settings.cost_monthly_budget_usd = 100.0

    status = svc.get_budget_status()

    assert status["monthly_percent"] == pytest.approx(25.0, rel=0.01)


@pytest.mark.unit
def test_get_budget_status_daily_exceeded_true_when_spend_equals_cap(mocker: Any) -> None:
    """get_budget_status() sets daily_exceeded=True when spend equals daily_cap."""
    import src.services.cost_guardrail_service as svc_module

    svc = _service_with_mocked_session(mocker, total_spend=10.0)
    mocker.patch.object(svc_module, "settings")
    svc_module.settings.cost_daily_budget_usd = 10.0
    svc_module.settings.cost_monthly_budget_usd = None

    status = svc.get_budget_status()

    assert status["daily_exceeded"] is True


@pytest.mark.unit
def test_get_budget_status_daily_exceeded_false_when_spend_below_cap(mocker: Any) -> None:
    """get_budget_status() sets daily_exceeded=False when spend is below daily_cap."""
    import src.services.cost_guardrail_service as svc_module

    svc = _service_with_mocked_session(mocker, total_spend=9.99)
    mocker.patch.object(svc_module, "settings")
    svc_module.settings.cost_daily_budget_usd = 10.0
    svc_module.settings.cost_monthly_budget_usd = None

    status = svc.get_budget_status()

    assert status["daily_exceeded"] is False


@pytest.mark.unit
def test_get_budget_status_monthly_exceeded_true_when_spend_equals_cap(mocker: Any) -> None:
    """get_budget_status() sets monthly_exceeded=True when spend equals monthly_cap."""
    import src.services.cost_guardrail_service as svc_module

    svc = _service_with_mocked_session(mocker, total_spend=50.0)
    mocker.patch.object(svc_module, "settings")
    svc_module.settings.cost_daily_budget_usd = None
    svc_module.settings.cost_monthly_budget_usd = 50.0

    status = svc.get_budget_status()

    assert status["monthly_exceeded"] is True


@pytest.mark.unit
def test_get_budget_status_monthly_exceeded_false_when_spend_below_cap(mocker: Any) -> None:
    """get_budget_status() sets monthly_exceeded=False when spend is below monthly_cap."""
    import src.services.cost_guardrail_service as svc_module

    svc = _service_with_mocked_session(mocker, total_spend=49.99)
    mocker.patch.object(svc_module, "settings")
    svc_module.settings.cost_daily_budget_usd = None
    svc_module.settings.cost_monthly_budget_usd = 50.0

    status = svc.get_budget_status()

    assert status["monthly_exceeded"] is False


@pytest.mark.unit
def test_get_budget_status_daily_exceeded_false_when_daily_cap_is_zero(mocker: Any) -> None:
    """get_budget_status() does not trigger daily_exceeded when daily_cap is 0 (no div-by-zero)."""
    import src.services.cost_guardrail_service as svc_module

    svc = _service_with_mocked_session(mocker, total_spend=5.0)
    mocker.patch.object(svc_module, "settings")
    svc_module.settings.cost_daily_budget_usd = 0.0
    svc_module.settings.cost_monthly_budget_usd = None

    status = svc.get_budget_status()

    assert status["daily_exceeded"] is False
    assert status["daily_percent"] == 0.0


# ---------------------------------------------------------------------------
# can_proceed() -- unit
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_can_proceed_returns_true_none_when_under_both_caps(mocker: Any) -> None:
    """can_proceed() returns (True, None) when spend is below both budget caps."""
    import src.services.cost_guardrail_service as svc_module

    svc = _service_with_mocked_session(mocker, total_spend=1.0)
    mocker.patch.object(svc_module, "settings")
    svc_module.settings.cost_daily_budget_usd = 10.0
    svc_module.settings.cost_monthly_budget_usd = 100.0

    ok, msg = svc.can_proceed()

    assert ok is True
    assert msg is None


@pytest.mark.unit
def test_can_proceed_returns_false_message_when_daily_cap_exceeded(mocker: Any) -> None:
    """can_proceed() returns (False, str) and calls send_alert when daily cap is hit."""
    import src.services.cost_guardrail_service as svc_module

    svc = _service_with_mocked_session(mocker, total_spend=10.0)
    mocker.patch.object(svc_module, "settings")
    svc_module.settings.cost_daily_budget_usd = 10.0
    svc_module.settings.cost_monthly_budget_usd = 100.0

    mock_alert = mocker.patch.object(svc, "send_alert", return_value=True)

    ok, msg = svc.can_proceed()

    assert ok is False
    assert msg is not None
    assert "Daily" in msg
    mock_alert.assert_called_once()
    call_kwargs = mock_alert.call_args
    assert call_kwargs.kwargs.get("level") == "warning" or call_kwargs.args[0] == "warning"


@pytest.mark.unit
def test_can_proceed_returns_false_message_when_monthly_cap_exceeded(mocker: Any) -> None:
    """can_proceed() returns (False, str) and calls send_alert when monthly cap is hit."""
    import src.services.cost_guardrail_service as svc_module

    svc = _service_with_mocked_session(mocker, total_spend=50.0)
    mocker.patch.object(svc_module, "settings")
    svc_module.settings.cost_daily_budget_usd = None
    svc_module.settings.cost_monthly_budget_usd = 50.0

    mock_alert = mocker.patch.object(svc, "send_alert", return_value=True)

    ok, msg = svc.can_proceed()

    assert ok is False
    assert msg is not None
    assert "Monthly" in msg
    mock_alert.assert_called_once()


@pytest.mark.unit
def test_can_proceed_short_circuits_on_daily_exceeded(mocker: Any) -> None:
    """can_proceed() does not check monthly limit when daily is already exceeded."""
    import src.services.cost_guardrail_service as svc_module

    # Daily=5.0 exceeded, monthly=10.0 also exceeded -- only daily alert fires.
    svc = _service_with_mocked_session(mocker, total_spend=5.0)
    mocker.patch.object(svc_module, "settings")
    svc_module.settings.cost_daily_budget_usd = 5.0
    svc_module.settings.cost_monthly_budget_usd = 5.0

    mock_alert = mocker.patch.object(svc, "send_alert", return_value=True)

    ok, msg = svc.can_proceed()

    assert ok is False
    # send_alert should be called exactly once (for daily), not twice.
    mock_alert.assert_called_once()
    call_kwargs = mock_alert.call_args
    # title argument should reference daily, not monthly.
    assert "Daily" in str(call_kwargs)


# ---------------------------------------------------------------------------
# send_alert() -- unit
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_send_alert_returns_false_when_no_webhook_url_configured(
    mocker: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """send_alert() returns False and logs info when webhook_url is not set."""
    import logging

    svc = CostGuardrailService(webhook_url=None)

    import src.services.cost_guardrail_service as svc_module

    mocker.patch.object(svc_module, "settings")
    svc_module.settings.webhook_url = None
    svc.webhook_url = None

    with caplog.at_level(logging.INFO, logger="src.services.cost_guardrail_service"):
        result = svc.send_alert(level="warning", title="Test Alert", message="No webhook")

    assert result is False


@pytest.mark.unit
def test_send_alert_posts_correct_json_payload_to_webhook(mocker: Any) -> None:
    """send_alert() posts a JSON payload with level, title, message, and details."""
    webhook_url = "https://hooks.example.com/test"
    svc = CostGuardrailService(webhook_url=webhook_url)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.post.return_value = mock_response
    mock_client_ctx = MagicMock()
    mock_client_ctx.__enter__ = MagicMock(return_value=mock_client)
    mock_client_ctx.__exit__ = MagicMock(return_value=False)

    mock_session = MagicMock()
    mock_action_repo = MagicMock()
    mock_session_ctx = MagicMock()
    mock_session_ctx.__enter__ = MagicMock(return_value=mock_session)
    mock_session_ctx.__exit__ = MagicMock(return_value=False)

    mocker.patch("src.services.cost_guardrail_service.httpx.Client", return_value=mock_client_ctx)
    mocker.patch("src.services.cost_guardrail_service.get_session", return_value=mock_session_ctx)
    mocker.patch(
        "src.services.cost_guardrail_service.ActionLogRepository",
        return_value=mock_action_repo,
    )

    result = svc.send_alert(
        level="critical",
        title="Budget Breach",
        message="Over limit",
        details={"extra": "data"},
    )

    assert result is True
    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    posted_url = call_args.args[0] if call_args.args else call_args.kwargs.get("url")
    posted_json = call_args.kwargs.get("json") or (
        call_args.args[1] if len(call_args.args) > 1 else None
    )

    assert posted_url == webhook_url
    assert posted_json is not None
    assert posted_json["level"] == "critical"
    assert posted_json["title"] == "Budget Breach"
    assert posted_json["message"] == "Over limit"
    assert posted_json["details"] == {"extra": "data"}


@pytest.mark.unit
def test_send_alert_returns_true_on_successful_http_post(mocker: Any) -> None:
    """send_alert() returns True when httpx.Client.post succeeds."""
    webhook_url = "https://hooks.example.com/ok"
    svc = CostGuardrailService(webhook_url=webhook_url)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.post.return_value = mock_response
    mock_client_ctx = MagicMock()
    mock_client_ctx.__enter__ = MagicMock(return_value=mock_client)
    mock_client_ctx.__exit__ = MagicMock(return_value=False)

    mock_session_ctx = MagicMock()
    mock_session_ctx.__enter__ = MagicMock(return_value=MagicMock())
    mock_session_ctx.__exit__ = MagicMock(return_value=False)
    mock_action_repo = MagicMock()

    mocker.patch("src.services.cost_guardrail_service.httpx.Client", return_value=mock_client_ctx)
    mocker.patch("src.services.cost_guardrail_service.get_session", return_value=mock_session_ctx)
    mocker.patch(
        "src.services.cost_guardrail_service.ActionLogRepository",
        return_value=mock_action_repo,
    )

    result = svc.send_alert(level="info", title="OK", message="All good")

    assert result is True


@pytest.mark.unit
def test_send_alert_returns_false_when_http_post_raises_exception(mocker: Any) -> None:
    """send_alert() returns False and logs error when httpx.Client.post raises."""
    import httpx

    webhook_url = "https://hooks.example.com/fail"
    svc = CostGuardrailService(webhook_url=webhook_url)

    mock_client = MagicMock()
    mock_client.post.side_effect = httpx.ConnectError("Connection refused")
    mock_client_ctx = MagicMock()
    mock_client_ctx.__enter__ = MagicMock(return_value=mock_client)
    mock_client_ctx.__exit__ = MagicMock(return_value=False)

    mocker.patch("src.services.cost_guardrail_service.httpx.Client", return_value=mock_client_ctx)

    result = svc.send_alert(level="warning", title="Failure Test", message="Will fail")

    assert result is False


@pytest.mark.unit
def test_send_alert_records_action_log_on_success(mocker: Any) -> None:
    """send_alert() calls ActionLogRepository.record_action when POST succeeds."""
    webhook_url = "https://hooks.example.com/log"
    svc = CostGuardrailService(webhook_url=webhook_url)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.post.return_value = mock_response
    mock_client_ctx = MagicMock()
    mock_client_ctx.__enter__ = MagicMock(return_value=mock_client)
    mock_client_ctx.__exit__ = MagicMock(return_value=False)

    mock_session_ctx = MagicMock()
    mock_session_ctx.__enter__ = MagicMock(return_value=MagicMock())
    mock_session_ctx.__exit__ = MagicMock(return_value=False)
    mock_action_repo = MagicMock()

    mocker.patch("src.services.cost_guardrail_service.httpx.Client", return_value=mock_client_ctx)
    mocker.patch("src.services.cost_guardrail_service.get_session", return_value=mock_session_ctx)
    mocker.patch(
        "src.services.cost_guardrail_service.ActionLogRepository",
        return_value=mock_action_repo,
    )

    svc.send_alert(level="warning", title="Logged Alert", message="Checking action log")

    mock_action_repo.record_action.assert_called_once()
    call_kwargs = mock_action_repo.record_action.call_args.kwargs
    assert call_kwargs.get("stage") == "system"
    assert call_kwargs.get("action") == "send_alert"
    assert call_kwargs.get("status") == "success"


# ---------------------------------------------------------------------------
# Budget enforcement integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_budget_enforcement_blocks_job_after_daily_cap_exceeded(
    db_session: Session,
    mocker: Any,
) -> None:
    """After daily cap is exceeded by accumulated spend, can_proceed() returns False."""
    import src.services.cost_guardrail_service as svc_module

    cost_repo = CostRepository(db_session)
    cost_repo.log_cost(_make_entry(cost_usd=5.00))
    cost_repo.log_cost(_make_entry(cost_usd=5.00))
    db_session.commit()

    total_spend = cost_repo.get_total_spend()

    mock_session_ctx = MagicMock()
    mock_session_ctx.__enter__ = MagicMock(return_value=db_session)
    mock_session_ctx.__exit__ = MagicMock(return_value=False)
    mock_cost_repo = MagicMock()
    mock_cost_repo.get_total_spend.return_value = total_spend

    mocker.patch("src.services.cost_guardrail_service.get_session", return_value=mock_session_ctx)
    mocker.patch("src.services.cost_guardrail_service.CostRepository", return_value=mock_cost_repo)
    mocker.patch.object(svc_module, "settings")
    svc_module.settings.cost_daily_budget_usd = 9.99
    svc_module.settings.cost_monthly_budget_usd = None

    svc = CostGuardrailService(webhook_url=None)
    ok, msg = svc.can_proceed()

    assert ok is False
    assert msg is not None


@pytest.mark.integration
def test_budget_enforcement_spend_exactly_at_daily_cap_triggers_exceeded(
    db_session: Session,
    mocker: Any,
) -> None:
    """Spending exactly equal to the daily cap triggers the exceeded flag."""
    import src.services.cost_guardrail_service as svc_module

    cost_repo = CostRepository(db_session)
    cost_repo.log_cost(_make_entry(cost_usd=10.0))
    db_session.commit()

    total_spend = cost_repo.get_total_spend()

    mock_session_ctx = MagicMock()
    mock_session_ctx.__enter__ = MagicMock(return_value=db_session)
    mock_session_ctx.__exit__ = MagicMock(return_value=False)
    mock_cost_repo = MagicMock()
    mock_cost_repo.get_total_spend.return_value = total_spend

    mocker.patch("src.services.cost_guardrail_service.get_session", return_value=mock_session_ctx)
    mocker.patch("src.services.cost_guardrail_service.CostRepository", return_value=mock_cost_repo)
    mocker.patch.object(svc_module, "settings")
    svc_module.settings.cost_daily_budget_usd = 10.0
    svc_module.settings.cost_monthly_budget_usd = None

    svc = CostGuardrailService(webhook_url=None)
    status = svc.get_budget_status()

    assert status["daily_exceeded"] is True


@pytest.mark.integration
def test_budget_enforcement_one_cent_below_daily_cap_does_not_trigger_exceeded(
    db_session: Session,
    mocker: Any,
) -> None:
    """Spending one cent below the daily cap does not trigger daily_exceeded."""
    import src.services.cost_guardrail_service as svc_module

    cost_repo = CostRepository(db_session)
    cost_repo.log_cost(_make_entry(cost_usd=9.99))
    db_session.commit()

    total_spend = cost_repo.get_total_spend()

    mock_session_ctx = MagicMock()
    mock_session_ctx.__enter__ = MagicMock(return_value=db_session)
    mock_session_ctx.__exit__ = MagicMock(return_value=False)
    mock_cost_repo = MagicMock()
    mock_cost_repo.get_total_spend.return_value = total_spend

    mocker.patch("src.services.cost_guardrail_service.get_session", return_value=mock_session_ctx)
    mocker.patch("src.services.cost_guardrail_service.CostRepository", return_value=mock_cost_repo)
    mocker.patch.object(svc_module, "settings")
    svc_module.settings.cost_daily_budget_usd = 10.0
    svc_module.settings.cost_monthly_budget_usd = None

    svc = CostGuardrailService(webhook_url=None)
    status = svc.get_budget_status()

    assert status["daily_exceeded"] is False
