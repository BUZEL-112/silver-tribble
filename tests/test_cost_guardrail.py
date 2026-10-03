"""Tests for CostGuardrailService: spend checking, cap enforcement, and webhook alert dispatch."""

from unittest.mock import MagicMock, patch

import pytest

from src.core.config import settings
from src.services.cost_guardrail_service import CostGuardrailService


@pytest.fixture
def guardrail_service() -> CostGuardrailService:
    return CostGuardrailService(webhook_url="https://hooks.example.com/alerts")


def test_get_budget_status_unlimited() -> None:
    """Verify budget status when no spend limits are set."""
    orig_daily = settings.cost_daily_budget_usd
    orig_monthly = settings.cost_monthly_budget_usd
    try:
        settings.cost_daily_budget_usd = None
        settings.cost_monthly_budget_usd = None

        svc = CostGuardrailService()
        status = svc.get_budget_status()

        assert status["daily_budget_usd"] is None
        assert status["daily_exceeded"] is False
        assert status["monthly_exceeded"] is False
    finally:
        settings.cost_daily_budget_usd = orig_daily
        settings.cost_monthly_budget_usd = orig_monthly


def test_can_proceed_enforces_daily_cap(guardrail_service: CostGuardrailService) -> None:
    """Verify that exceeding daily spend cap halts execution and attempts alert."""
    orig_daily = settings.cost_daily_budget_usd
    try:
        settings.cost_daily_budget_usd = 5.0

        with patch(
            "src.repositories.cost_repository.CostRepository.get_total_spend",
            return_value=5.50,
        ):
            with patch.object(guardrail_service, "send_alert") as mock_alert:
                can_run, reason = guardrail_service.can_proceed()
                assert can_run is False
                assert reason is not None
                assert "Daily spend cap reached" in reason
                mock_alert.assert_called_once()
    finally:
        settings.cost_daily_budget_usd = orig_daily


def test_send_alert_success(guardrail_service: CostGuardrailService) -> None:
    """Verify alert payload dispatch to webhook endpoint."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        success = guardrail_service.send_alert(
            level="error",
            title="Render Failed",
            message="Remotion timeout on job 10",
        )
        assert success is True
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["level"] == "error"
        assert kwargs["json"]["title"] == "Render Failed"
