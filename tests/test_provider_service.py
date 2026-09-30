"""Tests for ProviderService: provider listing, priority movement, removal, and custom provider lifecycle."""

import pytest
from src.core.config import settings
from src.models.schemas import CustomProviderConfig
from src.services.provider_service import ProviderService


@pytest.fixture(autouse=True)
def reset_provider_settings() -> None:
    """Snapshot and restore provider priority and custom providers around each test."""
    orig_priority = list(settings.provider_priority)
    orig_custom = [dict(c) for c in settings.custom_providers]
    yield
    settings.provider_priority = orig_priority
    settings.custom_providers = orig_custom


def test_list_providers() -> None:
    """Verify listing all built-in and custom providers with live priority and status."""
    svc = ProviderService()
    providers = svc.list_providers()
    assert len(providers) >= 4

    ids = [p.id for p in providers]
    assert "pexels" in ids
    assert "giphy" in ids
    assert "pixabay" in ids
    assert "asset_library" in ids

    # Enabled providers should come before disabled providers
    enabled_providers = [p for p in providers if p.is_enabled]
    disabled_providers = [p for p in providers if not p.is_enabled]
    assert len(enabled_providers) > 0

    for p in enabled_providers:
        assert p.priority_rank >= 1
    ranks = [p.priority_rank for p in enabled_providers]
    assert ranks == sorted(ranks)


def test_move_priority_up_and_down() -> None:
    """Verify shifting a provider's priority up or down in the cascade order."""
    svc = ProviderService()
    settings.provider_priority = ["pexels", "giphy", "pixabay", "asset_library"]

    # Moving the top element up should be a no-op
    unchanged = svc.move_priority("pexels", "up")
    assert unchanged[0] == "pexels"

    # Moving second element up swaps it with the first
    shifted = svc.move_priority("giphy", "up")
    assert shifted[0] == "giphy"
    assert shifted[1] == "pexels"

    # Moving first element down swaps it with the second
    down_shifted = svc.move_priority("giphy", "down")
    assert down_shifted[0] == "pexels"
    assert down_shifted[1] == "giphy"


def test_remove_from_cascade() -> None:
    """Verify removing a provider from active fallback cascade."""
    svc = ProviderService()
    settings.provider_priority = ["pexels", "giphy", "pixabay", "local"]

    new_order = svc.remove_from_cascade("giphy")
    assert "giphy" not in new_order
    assert "giphy" not in settings.provider_priority
    assert "pexels" in new_order


def test_add_and_delete_custom_provider() -> None:
    """Verify registering a new custom provider, finding it in catalog, and deleting it."""
    svc = ProviderService()
    custom_cfg = CustomProviderConfig(
        id="custom_stock_test",
        name="Custom Stock Test",
        media_type="image",
        mode="rest_query",
        endpoint_url="https://api.example.com/v1/search?q={query}",
        http_method="GET",
        auth_header_name="Authorization",
        auth_token="test_secret_token",
        query_param_name="query",
        response_url_path="results.0.url",
        enabled=True,
        priority=1,
    )

    registered = svc.add_custom_provider(custom_cfg)
    assert registered.id == "custom_stock_test"
    assert any(c.get("id") == "custom_stock_test" for c in settings.custom_providers)
    assert "custom_stock_test" in settings.provider_priority

    # Verify custom provider is present in list_providers
    providers = svc.list_providers()
    custom_entry = next((p for p in providers if p.id == "custom_stock_test"), None)
    assert custom_entry is not None
    assert custom_entry.is_custom is True
    assert custom_entry.name == "Custom Stock Test"

    # Now delete the custom provider
    deleted = svc.delete_custom_provider("custom_stock_test")
    assert deleted is True
    assert not any(c.get("id") == "custom_stock_test" for c in settings.custom_providers)
    assert "custom_stock_test" not in settings.provider_priority


def test_test_provider_local() -> None:
    """Verify testing local provider connection succeeds."""
    svc = ProviderService()
    res = svc.test_provider("local")
    assert res.provider_id == "local"
    assert res.status == "success"
    assert res.latency_ms >= 0


def test_test_all_providers() -> None:
    """Verify batch connectivity test across all registered providers."""
    svc = ProviderService()
    results = svc.test_all_providers()
    assert len(results) >= 4
    result_ids = [r.provider_id for r in results]
    assert "pexels" in result_ids
    assert "giphy" in result_ids
