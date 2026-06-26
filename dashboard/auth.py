"""Xác thực dashboard — HTTP Basic + session token."""
from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Final

from config import DASHBOARD_AUTH_SALT, DASHBOARD_PASSWORD, DASHBOARD_USER

SESSION_COOKIE_NAME: Final = "dashboard_session"


def dashboard_auth_enabled() -> bool:
    return bool((DASHBOARD_PASSWORD or "").strip())


def session_token_for_password(password: str) -> str:
    """Token cookie — SHA256(salt:password), đồng bộ với Next.js middleware."""
    salt = DASHBOARD_AUTH_SALT or "cps-bot-dashboard"
    raw = f"{salt}:{password}"
    return hashlib.sha256(raw.encode()).hexdigest()


def verify_session_token(token: str) -> bool:
    if not dashboard_auth_enabled():
        return True
    expected = session_token_for_password(DASHBOARD_PASSWORD)
    return secrets.compare_digest(token or "", expected)


def verify_basic_auth(authorization: str | None) -> bool:
    if not dashboard_auth_enabled():
        return True
    if not authorization or not authorization.lower().startswith("basic "):
        return False
    try:
        raw = base64.b64decode(authorization.split(" ", 1)[1].strip()).decode("utf-8")
    except (ValueError, UnicodeDecodeError, IndexError):
        return False
    if ":" not in raw:
        return False
    user, password = raw.split(":", 1)
    user_ok = secrets.compare_digest(user, DASHBOARD_USER)
    pass_ok = secrets.compare_digest(password, DASHBOARD_PASSWORD)
    return user_ok and pass_ok


def verify_password(password: str) -> bool:
    if not dashboard_auth_enabled():
        return True
    return secrets.compare_digest(password, DASHBOARD_PASSWORD)
