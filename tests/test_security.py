"""Tests for security utilities: secret masking, session management, and auth validation."""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.core.config import settings
from src.core.security import (
    generate_session_token,
    invalidate_session_token,
    is_session_token_valid,
    mask_dict_secrets,
    mask_secret,
    verify_auth_token,
)


def test_mask_secret() -> None:
    """Verify secret masking behavior across different token lengths."""
    assert mask_secret(None) is None
    assert mask_secret("") == ""
    assert mask_secret("short") == "******"
    assert mask_secret("12345678") == "12******78"

    long_token = "AIzaSyD-847294829472_TestKey1234"
    masked = mask_secret(long_token)
    assert masked.startswith("AIz")
    assert masked.endswith("1234")
    assert "********" in masked
    assert long_token not in masked


def test_mask_dict_secrets() -> None:
    """Verify recursive masking of sensitive dictionary keys."""
    data = {
        "server": "https://api.example.com",
        "api_key": "secret_key_1234567890",
        "nested": {
            "token": "bearer_token_xyz_9876",
            "count": 42,
            "status": "active",
        },
        "items": [
            {"provider": "openai", "openai_api_key": "sk-123456789abcdef"},
            {"provider": "public", "name": "test"},
        ],
    }
    masked = mask_dict_secrets(data)

    assert masked["server"] == "https://api.example.com"
    assert "secret_key" not in masked["api_key"]
    assert "********" in masked["api_key"]
    assert "bearer_token" not in masked["nested"]["token"]
    assert masked["nested"]["count"] == 42
    assert "123456789" not in masked["items"][0]["openai_api_key"]
    assert masked["items"][1]["name"] == "test"


def test_session_lifecycle() -> None:
    """Verify session token creation, validation, and invalidation."""
    assert not is_session_token_valid(None)
    assert not is_session_token_valid("invalid_token")

    token = generate_session_token()
    assert is_session_token_valid(token)

    invalidate_session_token(token)
    assert not is_session_token_valid(token)


def test_verify_auth_token_bypass_when_unconfigured() -> None:
    """When api_auth_token and admin_password are None, authentication is bypassed."""
    orig_token = settings.api_auth_token
    orig_pass = settings.admin_password
    try:
        settings.api_auth_token = None
        settings.admin_password = None

        scope = {
            "type": "http",
            "headers": [],
        }
        req = Request(scope)
        assert verify_auth_token(req, credentials=None) is True
    finally:
        settings.api_auth_token = orig_token
        settings.admin_password = orig_pass


def test_verify_auth_token_with_valid_bearer() -> None:
    """Validate access with matching Bearer token."""
    from fastapi.security import HTTPAuthorizationCredentials

    orig_token = settings.api_auth_token
    try:
        settings.api_auth_token = "secure-test-token-123"

        scope = {"type": "http", "headers": []}
        req = Request(scope)
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="secure-test-token-123")

        assert verify_auth_token(req, credentials=creds) is True
    finally:
        settings.api_auth_token = orig_token


def test_verify_auth_token_with_invalid_bearer_raises_401() -> None:
    """Validate 401 Unauthorized is raised on mismatched token."""
    from fastapi.security import HTTPAuthorizationCredentials

    orig_token = settings.api_auth_token
    try:
        settings.api_auth_token = "secure-test-token-123"

        scope = {"type": "http", "headers": []}
        req = Request(scope)
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong-token")

        with pytest.raises(HTTPException) as exc_info:
            verify_auth_token(req, credentials=creds)
        assert exc_info.value.status_code == 401
    finally:
        settings.api_auth_token = orig_token
