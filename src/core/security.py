"""Security utilities, authentication dependencies, session management, and secret masking."""

import hmac
import secrets
from typing import Any

from fastapi import HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.core.config import settings

# HTTP Bearer scheme with auto_error=False to allow checking session cookies or open dev mode
bearer_scheme = HTTPBearer(auto_error=False)

SECRET_KEY_NAMES: set[str] = {
    "api_key",
    "openai_api_key",
    "deepseek_api_key",
    "gemini_api_key",
    "pexels_api_key",
    "giphy_api_key",
    "pixabay_api_key",
    "flux_api_key",
    "elevenlabs_api_key",
    "youtube_client_secret",
    "youtube_refresh_token",
    "r2_secret_access_key",
    "webhook_secret",
    "admin_password",
    "api_auth_token",
    "secret",
    "token",
    "password",
}

# In-memory storage for active web dashboard session tokens
_active_session_tokens: set[str] = set()


def mask_secret(value: str | None) -> str | None:
    """Mask a secret string preserving first few and last few characters for verification."""
    if not value or not isinstance(value, str):
        return value
    val_str = value.strip()
    if len(val_str) <= 6:
        return "******"
    if len(val_str) <= 12:
        return f"{val_str[:2]}******{val_str[-2:]}"
    return f"{val_str[:3]}********{val_str[-4:]}"


def mask_dict_secrets(data: Any) -> Any:
    """Recursively mask known sensitive keys within dictionaries and lists."""
    if isinstance(data, dict):
        masked: dict[str, Any] = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            is_secret = any(sec in k_lower for sec in SECRET_KEY_NAMES)
            if is_secret and isinstance(v, str):
                masked[k] = mask_secret(v)
            elif isinstance(v, (dict, list)):
                masked[k] = mask_dict_secrets(v)
            else:
                masked[k] = v
        return masked
    elif isinstance(data, list):
        return [mask_dict_secrets(item) for item in data]
    return data


def generate_session_token() -> str:
    """Generate a cryptographically secure random session token."""
    token = secrets.token_urlsafe(32)
    _active_session_tokens.add(token)
    return token


def invalidate_session_token(token: str) -> None:
    """Revoke an active session token."""
    _active_session_tokens.discard(token)


def is_session_token_valid(token: str | None) -> bool:
    """Validate whether a session token is active."""
    if not token or not isinstance(token, str):
        return False
    return token in _active_session_tokens


def verify_auth_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> bool:
    """Verify Bearer token or dashboard session cookie.

    If settings.api_auth_token is not configured, authentication is bypassed
    for development environments.
    """
    configured_token = settings.api_auth_token
    configured_password = settings.admin_password

    # Bypass if no authentication is configured
    if not configured_token and not configured_password:
        return True

    # 1. Check Bearer token in Authorization header
    if credentials and configured_token:
        if hmac.compare_digest(credentials.credentials, configured_token):
            return True

    # 2. Check X-API-Key header
    api_key_header = request.headers.get("X-API-Key")
    if api_key_header and configured_token:
        if hmac.compare_digest(api_key_header, configured_token):
            return True

    # 3. Check session cookie for web dashboard requests
    cookie_token = request.cookies.get("ai_video_session")
    if cookie_token and is_session_token_valid(cookie_token):
        return True

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized: Valid authentication token or session required",
        headers={"WWW-Authenticate": "Bearer"},
    )


SECRET_PATTERNS: list[tuple[str, str]] = [
    (r"AIzaSy[0-9A-Za-z\-_]{33}", "Google API Key"),
    (r"sk-proj-[0-9A-Za-z\-_]{32,}", "OpenAI Project Key"),
    (r"sk-[0-9A-Za-z]{32,}", "Generic Secret Key"),
    (r"ghp_[0-9A-Za-z]{36}", "GitHub Personal Access Token"),
    (r"xox[baprs]-[0-9A-Za-z\-]+", "Slack Token"),
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID"),
    (r"-----BEGIN (?:RSA|OPENSSH|EC|DSA) PRIVATE KEY-----", "Private Key"),
]

BLOCKED_FILES: set[str] = {
    ".env",
    ".env.local",
    "config.yaml",
    "id_rsa",
    "id_ed25519",
}


def audit_repository_security() -> list[str]:
    """Scan git status and unstaged diff for leaked secrets, keys, and blocked files."""
    import re
    import subprocess
    from pathlib import Path

    violations: list[str] = []

    # 1. Inspect git status
    res = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=False
    )
    if res.returncode == 0 and res.stdout.strip():
        for line in res.stdout.strip().split("\n"):
            if not line.strip():
                continue
            filepath = line[3:].strip()
            path_obj = Path(filepath)

            if path_obj.name in BLOCKED_FILES:
                violations.append(f"Blocked file detected: {filepath}")

            if path_obj.suffix in [".pem", ".key", ".p12", ".pfx", ".db", ".sqlite3"]:
                violations.append(f"Sensitive file extension: {filepath}")

    # 2. Inspect git diff
    diff_res = subprocess.run(["git", "diff", "HEAD"], capture_output=True, text=True, check=False)
    if diff_res.returncode != 0:
        diff_res = subprocess.run(["git", "diff"], capture_output=True, text=True, check=False)

    if diff_res.returncode == 0 and diff_res.stdout:
        for line in diff_res.stdout.split("\n"):
            if not line.startswith("+") or line.startswith("+++"):
                continue

            for pattern, label in SECRET_PATTERNS:
                if re.search(pattern, line):
                    if any(
                        term in line.lower()
                        for term in ["your_", "dummy", "placeholder", "example"]
                    ):
                        continue
                    violations.append(f"Potential {label} detected: {line[:50]}...")

    return violations
