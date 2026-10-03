"""Cost guardrail service for budget enforcement and operational alert notifications."""

import logging
from typing import Any

import httpx

from src.core.config import settings
from src.core.database import get_session
from src.repositories.action_log_repository import ActionLogRepository
from src.repositories.cost_repository import CostRepository

logger = logging.getLogger(__name__)


class CostGuardrailService:
    """Monitors platform expenditures and dispatches webhook alerts on threshold breaches."""

    def __init__(self, webhook_url: str | None = None) -> None:
        self.webhook_url = webhook_url or settings.webhook_url

    def get_budget_status(self) -> dict[str, Any]:
        """Query total platform spend and compare against daily/monthly caps."""
        with get_session() as session:
            cost_repo = CostRepository(session)
            total_spend = cost_repo.get_total_spend()

        daily_cap = settings.cost_daily_budget_usd
        monthly_cap = settings.cost_monthly_budget_usd

        daily_percent = (total_spend / daily_cap * 100.0) if daily_cap and daily_cap > 0 else 0.0
        monthly_percent = (
            (total_spend / monthly_cap * 100.0) if monthly_cap and monthly_cap > 0 else 0.0
        )

        return {
            "total_spend_usd": round(total_spend, 4),
            "daily_budget_usd": daily_cap,
            "monthly_budget_usd": monthly_cap,
            "daily_percent": round(daily_percent, 1),
            "monthly_percent": round(monthly_percent, 1),
            "daily_exceeded": bool(daily_cap and total_spend >= daily_cap),
            "monthly_exceeded": bool(monthly_cap and total_spend >= monthly_cap),
        }

    def can_proceed(self) -> tuple[bool, str | None]:
        """Check whether current spending allows new pipeline jobs to proceed."""
        status = self.get_budget_status()
        if status["daily_exceeded"]:
            msg = (
                f"Daily spend cap reached: ${status['total_spend_usd']:.2f} "
                f">= ${status['daily_budget_usd']:.2f}"
            )
            self.send_alert(level="warning", title="Daily Budget Cap Exceeded", message=msg)
            return False, msg

        if status["monthly_exceeded"]:
            msg = (
                f"Monthly spend cap reached: ${status['total_spend_usd']:.2f} "
                f">= ${status['monthly_budget_usd']:.2f}"
            )
            self.send_alert(level="warning", title="Monthly Budget Cap Exceeded", message=msg)
            return False, msg

        return True, None

    def send_alert(
        self,
        level: str,
        title: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> bool:
        """Send notification payload to configured webhook endpoint."""
        target_url = self.webhook_url
        if not target_url:
            logger.info("No webhook URL configured; skipping alert: %s - %s", title, message)
            return False

        payload = {
            "level": level,
            "title": title,
            "message": message,
            "details": details or {},
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(target_url, json=payload)
                resp.raise_for_status()

            with get_session() as session:
                action_repo = ActionLogRepository(session)
                action_repo.record_action(
                    stage="system",
                    action="send_alert",
                    actor="cost_guardrail",
                    status="success",
                    message=f"Alert sent: {title}",
                    details=payload,
                )
            return True
        except Exception as exc:
            logger.error("Failed to dispatch alert webhook: %s", exc)
            return False
