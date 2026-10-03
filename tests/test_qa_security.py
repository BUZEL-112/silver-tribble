"""Comprehensive unit tests for src.core.security.

Covers secret masking (mask_secret, mask_dict_secrets), session token
lifecycle (generate_session_token, is_session_token_valid,
invalidate_session_token), and verify_auth_token authentication logic.
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

import src.core.security as security_module
from src.core.security import (
    generate_session_token,
    invalidate_session_token,
    is_session_token_valid,
    mask_dict_secrets,
    mask_secret,
    verify_auth_token,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    headers: list[tuple[bytes, bytes]] | None = None,
    cookies: dict[str, str] | None = None,
) -> Request:
    """Build a minimal Starlette Request with optional headers and cookies."""
    raw_headers: list[tuple[bytes, bytes]] = headers or []
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        raw_headers = list(raw_headers) + [(b"cookie", cookie_str.encode())]
    scope = {
        "type": "http",
        "headers": raw_headers,
    }
    return Request(scope)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_session_tokens() -> Generator[None, None, None]:
    """Clear _active_session_tokens before every test to prevent cross-test pollution."""
    security_module._active_session_tokens.clear()
    yield
    security_module._active_session_tokens.clear()


# ---------------------------------------------------------------------------
# mask_secret
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_mask_secret_none_returns_none() -> None:
    """mask_secret with None input returns None unchanged."""
    result = mask_secret(None)

    assert result is None


@pytest.mark.unit
def test_mask_secret_empty_string_returns_empty() -> None:
    """mask_secret with an empty string returns the empty string unchanged."""
    result = mask_secret("")

    assert result == ""


@pytest.mark.unit
def test_mask_secret_six_chars_returns_stars() -> None:
    """mask_secret with a value of exactly 6 characters returns '******'."""
    result = mask_secret("abcdef")

    assert result == "******"


@pytest.mark.unit
def test_mask_secret_one_char_returns_stars() -> None:
    """mask_secret with a single character returns '******'."""
    result = mask_secret("x")

    assert result == "******"


@pytest.mark.unit
def test_mask_secret_seven_chars_uses_short_mask() -> None:
    """mask_secret with 7 characters returns first2 + '******' + last2."""
    result = mask_secret("abcdefg")

    assert result == "ab******fg"


@pytest.mark.unit
def test_mask_secret_twelve_chars_uses_short_mask() -> None:
    """mask_secret with exactly 12 characters returns first2 + '******' + last2."""
    result = mask_secret("abcdefghijkl")

    assert result == "ab******kl"


@pytest.mark.unit
def test_mask_secret_thirteen_chars_uses_long_mask() -> None:
    """mask_secret with 13 characters returns first3 + '********' + last4."""
    result = mask_secret("abcdefghijklm")

    assert result == "abc********jklm"


@pytest.mark.unit
def test_mask_secret_long_value_uses_long_mask() -> None:
    """mask_secret with a long secret returns first3 + '********' + last4."""
    secret = "sk-1234567890abcdef"

    result = mask_secret(secret)

    assert result is not None
    assert result.startswith("sk-")
    assert result.endswith("cdef")
    assert "********" in result
    assert secret not in result


@pytest.mark.unit
def test_mask_secret_strips_leading_trailing_spaces_before_masking() -> None:
    """mask_secret strips whitespace before applying length checks."""
    padded = "  ab  "

    result = mask_secret(padded)

    # After stripping, "ab" has length 2 which is <= 6, so full masking applies
    assert result == "******"


@pytest.mark.unit
def test_mask_secret_strips_then_applies_long_mask() -> None:
    """mask_secret strips and then applies the long mask for a long padded value."""
    # 13 real chars, padded with spaces
    padded = "  abcdefghijklm  "

    result = mask_secret(padded)

    assert result is not None
    assert result.startswith("abc")
    assert result.endswith("jklm")
    assert "********" in result


# ---------------------------------------------------------------------------
# mask_dict_secrets
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_mask_dict_secrets_masks_api_key() -> None:
    """mask_dict_secrets replaces the value of 'api_key' with a masked string."""
    data = {"api_key": "sk-supersecretvalue1234"}

    result = mask_dict_secrets(data)

    assert result["api_key"] != "sk-supersecretvalue1234"
    assert "supersecret" not in result["api_key"]


@pytest.mark.unit
def test_mask_dict_secrets_masks_openai_api_key() -> None:
    """mask_dict_secrets masks the openai_api_key field."""
    data = {"openai_api_key": "sk-openaikey12345678"}

    result = mask_dict_secrets(data)

    assert "openaikey" not in result["openai_api_key"]


@pytest.mark.unit
def test_mask_dict_secrets_masks_admin_password() -> None:
    """mask_dict_secrets masks the admin_password field."""
    data = {"admin_password": "MySecurePass9876"}

    result = mask_dict_secrets(data)

    assert "SecurePass" not in result["admin_password"]


@pytest.mark.unit
def test_mask_dict_secrets_masks_token_field() -> None:
    """mask_dict_secrets masks any key containing 'token'."""
    data = {"token": "bearer_token_xyz_9876543210"}

    result = mask_dict_secrets(data)

    assert "bearer_token" not in result["token"]


@pytest.mark.unit
def test_mask_dict_secrets_masks_password_field() -> None:
    """mask_dict_secrets masks any key containing 'password'."""
    data = {"password": "hunter2isnotapassword"}

    result = mask_dict_secrets(data)

    assert "hunter2" not in result["password"]


@pytest.mark.unit
def test_mask_dict_secrets_does_not_mask_non_secret_keys() -> None:
    """mask_dict_secrets leaves non-secret keys completely unchanged."""
    data = {
        "server": "https://api.example.com",
        "count": 42,
        "status": "active",
        "provider": "pexels",
    }

    result = mask_dict_secrets(data)

    assert result["server"] == "https://api.example.com"
    assert result["count"] == 42
    assert result["status"] == "active"
    assert result["provider"] == "pexels"


@pytest.mark.unit
def test_mask_dict_secrets_recursively_masks_nested_dict() -> None:
    """mask_dict_secrets descends into nested dicts and masks secret keys there."""
    data = {
        "outer": "visible",
        "nested": {
            "token": "nested_secret_token_1234567890",
            "name": "keep_me",
        },
    }

    result = mask_dict_secrets(data)

    assert result["outer"] == "visible"
    assert "nested_secret" not in result["nested"]["token"]
    assert result["nested"]["name"] == "keep_me"


@pytest.mark.unit
def test_mask_dict_secrets_recursively_masks_items_in_lists() -> None:
    """mask_dict_secrets descends into list elements and masks secrets within them."""
    data = {
        "providers": [
            {"name": "openai", "openai_api_key": "sk-listkey12345678901"},
            {"name": "public", "url": "https://public.example.com"},
        ]
    }

    result = mask_dict_secrets(data)

    assert "listkey" not in result["providers"][0]["openai_api_key"]
    assert result["providers"][1]["url"] == "https://public.example.com"


@pytest.mark.unit
def test_mask_dict_secrets_non_string_secret_value_does_not_crash() -> None:
    """mask_dict_secrets with a non-string value for a secret key does not raise."""
    data = {"api_key": 12345, "token": None, "password": True}

    result = mask_dict_secrets(data)

    # Non-string secret values are left as-is (no masking, no crash)
    assert result["api_key"] == 12345
    assert result["token"] is None
    assert result["password"] is True


@pytest.mark.unit
def test_mask_dict_secrets_passthrough_for_non_dict_non_list() -> None:
    """mask_dict_secrets returns scalar values unchanged."""
    assert mask_dict_secrets("plainstring") == "plainstring"
    assert mask_dict_secrets(99) == 99
    assert mask_dict_secrets(None) is None


# ---------------------------------------------------------------------------
# generate_session_token
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_generate_session_token_returns_string() -> None:
    """generate_session_token returns a non-empty string."""
    token = generate_session_token()

    assert isinstance(token, str)
    assert len(token) > 0


@pytest.mark.unit
def test_generate_session_token_returns_unique_tokens() -> None:
    """generate_session_token produces distinct tokens on successive calls."""
    token1 = generate_session_token()
    token2 = generate_session_token()

    assert token1 != token2


@pytest.mark.unit
def test_generate_session_token_adds_token_to_active_set() -> None:
    """generate_session_token registers the new token in _active_session_tokens."""
    token = generate_session_token()

    assert token in security_module._active_session_tokens


# ---------------------------------------------------------------------------
# is_session_token_valid
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_is_session_token_valid_returns_true_for_generated_token() -> None:
    """is_session_token_valid returns True immediately after generate_session_token."""
    token = generate_session_token()

    assert is_session_token_valid(token) is True


@pytest.mark.unit
def test_is_session_token_valid_returns_false_for_unknown_token() -> None:
    """is_session_token_valid returns False for a token that was never generated."""
    result = is_session_token_valid("completely-unknown-token")

    assert result is False


@pytest.mark.unit
def test_is_session_token_valid_returns_false_for_none() -> None:
    """is_session_token_valid returns False when None is passed."""
    result = is_session_token_valid(None)

    assert result is False


@pytest.mark.unit
def test_is_session_token_valid_returns_false_for_empty_string() -> None:
    """is_session_token_valid returns False when an empty string is passed."""
    result = is_session_token_valid("")

    assert result is False


# ---------------------------------------------------------------------------
# invalidate_session_token
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_invalidate_session_token_removes_token() -> None:
    """invalidate_session_token causes is_session_token_valid to return False."""
    token = generate_session_token()
    assert is_session_token_valid(token) is True

    invalidate_session_token(token)

    assert is_session_token_valid(token) is False


@pytest.mark.unit
def test_invalidate_session_token_non_existent_does_not_raise() -> None:
    """invalidate_session_token on an unknown token completes without raising."""
    try:
        invalidate_session_token("ghost-token-that-never-existed")
    except Exception as exc:
        pytest.fail(f"invalidate_session_token raised unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# verify_auth_token
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_verify_auth_token_bypasses_when_no_auth_configured() -> None:
    """verify_auth_token returns True when neither api_auth_token nor admin_password is set."""
    with (
        patch("src.core.security.settings.api_auth_token", None),
        patch("src.core.security.settings.admin_password", None),
    ):
        request = _make_request()

        result = verify_auth_token(request, credentials=None)

    assert result is True


@pytest.mark.unit
def test_verify_auth_token_passes_with_valid_bearer_token() -> None:
    """verify_auth_token returns True when the Authorization Bearer token matches."""
    with (
        patch("src.core.security.settings.api_auth_token", "valid-api-token-xyz123"),
        patch("src.core.security.settings.admin_password", None),
    ):
        request = _make_request()
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid-api-token-xyz123")

        result = verify_auth_token(request, credentials=creds)

    assert result is True


@pytest.mark.unit
def test_verify_auth_token_passes_with_valid_x_api_key_header() -> None:
    """verify_auth_token returns True when the X-API-Key header matches the configured token."""
    with (
        patch("src.core.security.settings.api_auth_token", "header-api-token-abc987"),
        patch("src.core.security.settings.admin_password", None),
    ):
        request = _make_request(headers=[(b"x-api-key", b"header-api-token-abc987")])

        result = verify_auth_token(request, credentials=None)

    assert result is True


@pytest.mark.unit
def test_verify_auth_token_passes_with_valid_session_cookie() -> None:
    """verify_auth_token returns True when a valid session cookie is present."""
    with (
        patch("src.core.security.settings.api_auth_token", "some-configured-token"),
        patch("src.core.security.settings.admin_password", None),
    ):
        session_token = generate_session_token()
        request = _make_request(cookies={"ai_video_session": session_token})

        result = verify_auth_token(request, credentials=None)

    assert result is True


@pytest.mark.unit
def test_verify_auth_token_raises_401_with_invalid_bearer_token() -> None:
    """verify_auth_token raises HTTP 401 when the Bearer token does not match."""
    with (
        patch("src.core.security.settings.api_auth_token", "correct-token-777"),
        patch("src.core.security.settings.admin_password", None),
    ):
        request = _make_request()
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong-token-000")

        with pytest.raises(HTTPException) as exc_info:
            verify_auth_token(request, credentials=creds)

    assert exc_info.value.status_code == 401


@pytest.mark.unit
def test_verify_auth_token_raises_401_with_no_credentials_when_auth_configured() -> None:
    """verify_auth_token raises HTTP 401 when auth is required but nothing is supplied."""
    with (
        patch("src.core.security.settings.api_auth_token", "required-token-abc"),
        patch("src.core.security.settings.admin_password", None),
    ):
        request = _make_request()

        with pytest.raises(HTTPException) as exc_info:
            verify_auth_token(request, credentials=None)

    assert exc_info.value.status_code == 401


@pytest.mark.unit
def test_verify_auth_token_raises_401_with_invalid_session_cookie() -> None:
    """verify_auth_token raises HTTP 401 when cookie token is not in active sessions."""
    with (
        patch("src.core.security.settings.api_auth_token", "configured-token"),
        patch("src.core.security.settings.admin_password", None),
    ):
        request = _make_request(cookies={"ai_video_session": "invalid-session-token"})

        with pytest.raises(HTTPException) as exc_info:
            verify_auth_token(request, credentials=None)

    assert exc_info.value.status_code == 401
