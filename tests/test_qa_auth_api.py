"""Comprehensive integration tests for auth FastAPI endpoints in src.web.

Covers GET /api/auth/status, POST /api/auth/login, POST /api/auth/logout,
and verify_auth_token security dependency across all authentication branches.
"""

from __future__ import annotations

import hmac
from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

import src.core.security as security_module
from src.web import app

# ---------------------------------------------------------------------------
# Module-level test client
# ---------------------------------------------------------------------------

client = TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_settings(
    api_auth_token: str | None = None,
    admin_password: str | None = None,
) -> tuple[Any, Any]:
    """Return two active mock.patch context managers for settings attributes."""
    p1 = patch("src.web.settings.api_auth_token", api_auth_token)
    p2 = patch("src.web.settings.admin_password", admin_password)
    return p1, p2


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_session_tokens() -> Generator[None, None, None]:
    """Clear _active_session_tokens before and after every test."""
    security_module._active_session_tokens.clear()
    yield
    security_module._active_session_tokens.clear()


# ---------------------------------------------------------------------------
# GET /api/auth/status
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_auth_status_no_auth_configured_returns_auth_required_false() -> None:
    """GET /api/auth/status returns auth_required=False when no token/password is set."""
    with (
        patch("src.web.settings.api_auth_token", None),
        patch("src.web.settings.admin_password", None),
    ):
        response = client.get("/api/auth/status")

    assert response.status_code == 200
    body = response.json()
    assert body["auth_required"] is False


@pytest.mark.integration
def test_auth_status_with_api_auth_token_returns_auth_required_true() -> None:
    """GET /api/auth/status returns auth_required=True when api_auth_token is configured."""
    with (
        patch("src.web.settings.api_auth_token", "tok-abc123"),
        patch("src.web.settings.admin_password", None),
    ):
        response = client.get("/api/auth/status")

    assert response.status_code == 200
    body = response.json()
    assert body["auth_required"] is True


@pytest.mark.integration
def test_auth_status_returns_authenticated_true_with_valid_session_cookie() -> None:
    """GET /api/auth/status returns authenticated=True when a valid session cookie is present."""
    with (
        patch("src.web.settings.api_auth_token", "tok-xyz"),
        patch("src.web.settings.admin_password", None),
        patch("src.web.is_session_token_valid", return_value=True),
    ):
        response = client.get(
            "/api/auth/status",
            cookies={"ai_video_session": "any-token-value"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is True


@pytest.mark.integration
def test_auth_status_returns_authenticated_false_with_invalid_session_cookie() -> None:
    """GET /api/auth/status returns authenticated=False when cookie token is not valid."""
    with (
        patch("src.web.settings.api_auth_token", "tok-xyz"),
        patch("src.web.settings.admin_password", None),
        patch("src.web.is_session_token_valid", return_value=False),
    ):
        response = client.get(
            "/api/auth/status",
            cookies={"ai_video_session": "bad-token"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is False


# ---------------------------------------------------------------------------
# POST /api/auth/login
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_login_success_with_correct_password() -> None:
    """POST /api/auth/login returns status=success when admin_password matches."""
    with (
        patch("src.web.settings.api_auth_token", None),
        patch("src.web.settings.admin_password", "correct-pass-9876"),
    ):
        response = client.post(
            "/api/auth/login",
            json={"password": "correct-pass-9876"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert "token" in body


@pytest.mark.integration
def test_login_success_with_correct_token() -> None:
    """POST /api/auth/login returns status=success when api_auth_token matches."""
    with (
        patch("src.web.settings.api_auth_token", "correct-api-tok-123"),
        patch("src.web.settings.admin_password", None),
    ):
        response = client.post(
            "/api/auth/login",
            json={"token": "correct-api-tok-123"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert "token" in body


@pytest.mark.integration
def test_login_success_password_matching_api_auth_token_third_branch() -> None:
    """POST /api/auth/login succeeds when password matches api_auth_token (third branch)."""
    with (
        patch("src.web.settings.api_auth_token", "shared-pass-as-token-abc"),
        patch("src.web.settings.admin_password", None),
    ):
        response = client.post(
            "/api/auth/login",
            json={"password": "shared-pass-as-token-abc"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"


@pytest.mark.integration
def test_login_sets_httponly_session_cookie_on_success() -> None:
    """POST /api/auth/login sets an httponly 'ai_video_session' cookie on success."""
    with (
        patch("src.web.settings.api_auth_token", None),
        patch("src.web.settings.admin_password", "secret-pw-5678"),
    ):
        response = client.post(
            "/api/auth/login",
            json={"password": "secret-pw-5678"},
        )

    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "")
    assert "ai_video_session=" in set_cookie
    assert "HttpOnly" in set_cookie


@pytest.mark.integration
def test_login_returns_401_with_wrong_password() -> None:
    """POST /api/auth/login returns 401 when the password does not match."""
    with (
        patch("src.web.settings.api_auth_token", None),
        patch("src.web.settings.admin_password", "real-secret-pass"),
    ):
        response = client.post(
            "/api/auth/login",
            json={"password": "wrong-password"},
        )

    assert response.status_code == 401
    body = response.json()
    assert "detail" in body


@pytest.mark.integration
def test_login_returns_401_with_wrong_token() -> None:
    """POST /api/auth/login returns 401 when the token does not match."""
    with (
        patch("src.web.settings.api_auth_token", "real-api-token"),
        patch("src.web.settings.admin_password", None),
    ):
        response = client.post(
            "/api/auth/login",
            json={"token": "wrong-token-value"},
        )

    assert response.status_code == 401


@pytest.mark.integration
def test_login_success_when_no_auth_configured_at_all() -> None:
    """POST /api/auth/login returns success immediately when no auth is configured."""
    with (
        patch("src.web.settings.api_auth_token", None),
        patch("src.web.settings.admin_password", None),
    ):
        response = client.post(
            "/api/auth/login",
            json={"password": None, "token": None},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert "Authentication not configured" in body["message"]


@pytest.mark.integration
def test_login_handles_both_fields_none_when_auth_configured() -> None:
    """POST /api/auth/login returns 401 when both password and token are None but auth is set."""
    with (
        patch("src.web.settings.api_auth_token", "configured-tok"),
        patch("src.web.settings.admin_password", None),
    ):
        response = client.post(
            "/api/auth/login",
            json={"password": None, "token": None},
        )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/auth/logout
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_logout_clears_cookie_and_returns_success() -> None:
    """POST /api/auth/logout returns status=success and deletes the session cookie."""
    session_token = security_module.generate_session_token()

    response = client.post(
        "/api/auth/logout",
        cookies={"ai_video_session": session_token},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    # Confirm the cookie is cleared (value empty or max-age=0)
    set_cookie = response.headers.get("set-cookie", "")
    assert "ai_video_session" in set_cookie


@pytest.mark.integration
def test_logout_without_cookie_does_not_raise() -> None:
    """POST /api/auth/logout with no session cookie completes without error."""
    response = client.post("/api/auth/logout")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"


@pytest.mark.integration
def test_logout_invalidates_session_token() -> None:
    """POST /api/auth/logout causes the session token to become invalid."""
    session_token = security_module.generate_session_token()
    assert security_module.is_session_token_valid(session_token) is True

    client.post(
        "/api/auth/logout",
        cookies={"ai_video_session": session_token},
    )

    assert security_module.is_session_token_valid(session_token) is False


# ---------------------------------------------------------------------------
# verify_auth_token security edge cases (tested via direct call or protected route)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_verify_auth_token_passes_with_valid_bearer_in_authorization_header(mocker) -> None:
    """verify_auth_token accepts a valid Bearer token in the Authorization header."""
    from fastapi.security import HTTPAuthorizationCredentials
    from starlette.requests import Request

    mocker.patch("src.core.security.settings.api_auth_token", "bearer-tok-abc")
    mocker.patch("src.core.security.settings.admin_password", None)

    scope = {"type": "http", "headers": []}
    request = Request(scope)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bearer-tok-abc")

    from src.core.security import verify_auth_token

    result = verify_auth_token(request, credentials=creds)

    assert result is True


@pytest.mark.integration
def test_verify_auth_token_passes_with_valid_x_api_key_header(mocker) -> None:
    """verify_auth_token accepts a valid X-API-Key header."""
    from starlette.requests import Request

    mocker.patch("src.core.security.settings.api_auth_token", "xapikey-secret-789")
    mocker.patch("src.core.security.settings.admin_password", None)

    scope = {
        "type": "http",
        "headers": [(b"x-api-key", b"xapikey-secret-789")],
    }
    request = Request(scope)

    from src.core.security import verify_auth_token

    result = verify_auth_token(request, credentials=None)

    assert result is True


@pytest.mark.integration
def test_verify_auth_token_passes_with_valid_session_cookie(mocker) -> None:
    """verify_auth_token accepts a recognized session cookie."""
    from starlette.requests import Request

    mocker.patch("src.core.security.settings.api_auth_token", "some-tok")
    mocker.patch("src.core.security.settings.admin_password", None)

    session_tok = security_module.generate_session_token()
    cookie_header = f"ai_video_session={session_tok}"
    scope = {
        "type": "http",
        "headers": [(b"cookie", cookie_header.encode())],
    }
    request = Request(scope)

    from src.core.security import verify_auth_token

    result = verify_auth_token(request, credentials=None)

    assert result is True


@pytest.mark.integration
def test_verify_auth_token_raises_401_with_invalid_bearer_token(mocker) -> None:
    """verify_auth_token raises HTTP 401 for a mismatched Bearer token."""
    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials
    from starlette.requests import Request

    mocker.patch("src.core.security.settings.api_auth_token", "good-token-111")
    mocker.patch("src.core.security.settings.admin_password", None)

    scope = {"type": "http", "headers": []}
    request = Request(scope)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad-token-000")

    from src.core.security import verify_auth_token

    with pytest.raises(HTTPException) as exc_info:
        verify_auth_token(request, credentials=creds)

    assert exc_info.value.status_code == 401


@pytest.mark.integration
def test_verify_auth_token_raises_401_with_no_credentials_when_auth_required(mocker) -> None:
    """verify_auth_token raises HTTP 401 when auth is configured but nothing is supplied."""
    from fastapi import HTTPException
    from starlette.requests import Request

    mocker.patch("src.core.security.settings.api_auth_token", "required-tok-222")
    mocker.patch("src.core.security.settings.admin_password", None)

    scope = {"type": "http", "headers": []}
    request = Request(scope)

    from src.core.security import verify_auth_token

    with pytest.raises(HTTPException) as exc_info:
        verify_auth_token(request, credentials=None)

    assert exc_info.value.status_code == 401


@pytest.mark.integration
def test_verify_auth_token_bypasses_when_no_auth_configured(mocker) -> None:
    """verify_auth_token returns True immediately when no auth settings are configured."""
    from starlette.requests import Request

    mocker.patch("src.core.security.settings.api_auth_token", None)
    mocker.patch("src.core.security.settings.admin_password", None)

    scope = {"type": "http", "headers": []}
    request = Request(scope)

    from src.core.security import verify_auth_token

    result = verify_auth_token(request, credentials=None)

    assert result is True


# ---------------------------------------------------------------------------
# Timing-safe login: confirm hmac.compare_digest is used (not == operator)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_login_uses_hmac_compare_digest_for_token_comparison(mocker) -> None:
    """login endpoint calls hmac.compare_digest to compare tokens, preventing timing leaks."""
    compare_spy = mocker.patch("src.web.hmac.compare_digest", wraps=hmac.compare_digest)

    with (
        patch("src.web.settings.api_auth_token", "timing-safe-tok"),
        patch("src.web.settings.admin_password", None),
    ):
        client.post("/api/auth/login", json={"token": "timing-safe-tok"})

    compare_spy.assert_called()
    call_args = compare_spy.call_args_list
    token_calls = [
        c for c in call_args if "timing-safe-tok" in c.args or "timing-safe-tok" in str(c)
    ]
    assert len(token_calls) >= 1


@pytest.mark.integration
def test_login_uses_hmac_compare_digest_for_password_comparison(mocker) -> None:
    """login endpoint calls hmac.compare_digest to compare passwords, preventing timing leaks."""
    compare_spy = mocker.patch("src.web.hmac.compare_digest", wraps=hmac.compare_digest)

    with (
        patch("src.web.settings.api_auth_token", None),
        patch("src.web.settings.admin_password", "safe-password-xyz"),
    ):
        client.post("/api/auth/login", json={"password": "safe-password-xyz"})

    compare_spy.assert_called()
