"""Shared FastAPI dependencies (authentication)."""
from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db
from .models import User
from .security import decode_access_token

COOKIE_NAME = "netpulse_token"


async def _user_from_token(token: str, db: AsyncSession) -> User | None:
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        return None
    username = payload.get("sub")
    if not username:
        return None
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user and user.is_active:
        return user
    return None


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(COOKIE_NAME)


async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = await _user_from_token(token, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_user_ready(
    user: User = Depends(get_current_user),
) -> User:
    """Like get_current_user, but blocks access until a forced password change
    has been completed. Use this for every data endpoint."""
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password change required before using the application",
            headers={"X-Password-Change-Required": "1"},
        )
    return user


async def get_current_superuser(
    user: User = Depends(get_current_user_ready),
) -> User:
    if not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superuser privileges required",
        )
    return user


def require_role(*allowed: str):
    """Dependency factory: restrict an endpoint to the given roles.

    Roles are compared against ``user.role`` (falling back to superuser status
    for legacy rows). Superadmin is always allowed.
    """

    async def _dep(user: User = Depends(get_current_user_ready)) -> User:
        from .rbac import role_order

        rank = role_order(user.role)
        needed = max(role_order(r) for r in allowed)
        if rank < needed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return user

    return _dep


def require_device_write(user: User = Depends(get_current_user_ready)) -> User:
    """Gate device create/update/delete (admin+)."""
    from .rbac import can

    if not can(user.role, "devices", "write"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user


def require_user_manage(user: User = Depends(get_current_user_ready)) -> User:
    """Gate user management (super_admin only)."""
    from .rbac import can

    if not can(user.role, "users", "write"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user
