"""Webhook dispatch service for broadcasting pipeline lifecycle events."""

import hashlib
import hmac
import json
import time
from typing import Any

import httpx

from src.core.config import settings


class WebhookService:
    """Dispatches event payloads to an external HTTP webhook endpoint."""

    def __init__(
        self,
        webhook_url: str | None = None,
        webhook_secret: str | None = None,
    ) -> None:
        self.webhook_url = webhook_url or settings.webhook_url
        self.webhook_secret = webhook_secret or settings.webhook_secret

    def compute_signature(self, payload_bytes: bytes) -> str:
        """Compute HMAC-SHA256 signature over request body."""
        if not self.webhook_secret:
            return ""
        return hmac.new(
            self.webhook_secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()

    def dispatch_event(
        self,
        event_name: str,
        data: dict[str, Any],
        timeout_seconds: float = 5.0,
    ) -> bool:
        """Send JSON webhook event payload to configured endpoint."""
        if not self.webhook_url:
            return False

        payload = {
            "event": event_name,
            "timestamp": time.time(),
            "data": data,
        }
        body_bytes = json.dumps(payload, default=str).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "AINewsVideoPipeline/1.0",
        }
        if self.webhook_secret:
            signature = self.compute_signature(body_bytes)
            headers["X-Signature-SHA256"] = signature

        try:
            res = httpx.post(
                self.webhook_url,
                content=body_bytes,
                headers=headers,
                timeout=timeout_seconds,
            )
            return 200 <= res.status_code < 300
        except Exception:
            # Webhook dispatch failure must never break core pipeline operations
            return False
