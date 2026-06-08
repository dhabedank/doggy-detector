"""Cookie authentication for the local dashboard."""

from __future__ import annotations

import hmac
from datetime import timedelta
from typing import Optional

from fastapi import Request
from fastapi.responses import Response
from fastapi_login import LoginManager

from src.config import SettingsStore, verify_password

AUTH_COOKIE = "dog_detector_session"
SESSION_EXPIRY = timedelta(days=30)


def create_login_manager(settings_store: SettingsStore) -> LoginManager:
    """Create the fastapi-login manager backed by SQLite settings."""
    manager = LoginManager(
        settings_store.ensure_session_secret(),
        token_url="/api/auth/login",
        use_cookie=True,
        use_header=False,
        cookie_name=AUTH_COOKIE,
        default_expiry=SESSION_EXPIRY,
    )

    @manager.user_loader()
    def load_user(username: str) -> Optional[dict[str, str]]:
        configured_username = settings_store.get_auth_username()
        if configured_username and hmac.compare_digest(username, configured_username):
            return {"username": configured_username}
        return None

    return manager


def authenticate_user(username: str, password: str, settings_store: SettingsStore) -> bool:
    """Check submitted credentials against the SQLite-stored password hash."""
    configured_username = settings_store.get_auth_username()
    password_hash = settings_store.get_auth_password_hash()
    if not configured_username or not password_hash:
        return False

    if not hmac.compare_digest(username, configured_username):
        return False

    return verify_password(password, password_hash)


async def request_is_authenticated(request: Request) -> bool:
    manager: LoginManager = request.app.state.auth_manager
    return await manager.optional(request) is not None


def set_auth_cookie(response: Response, manager: LoginManager, username: str) -> None:
    access_token = manager.create_access_token(data={"sub": username}, expires=SESSION_EXPIRY)
    manager.set_cookie(response, access_token)


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(AUTH_COOKIE, httponly=True, samesite="lax")
