"""Authentication endpoints (JWT in an HttpOnly cookie)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..deps import COOKIE_NAME, get_current_user_ready, get_current_user, require_user_manage
from ..models import User, UserRole, utcnow
from ..audit import record
from ..schemas import (
    LoginRequest,
    MessageOut,
    PasswordChange,
    Token,
    UserCreate,
    UserOut,
    UserUpdate,
)
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _client_ip(request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )


@router.post("/login", response_model=Token)
async def login(
    payload: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.username == payload.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        await record(db, action="login_failed", username=payload.username,
                     ip_address=_client_ip(request), detail="invalid credentials")
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")

    token = create_access_token(user.username)
    _set_auth_cookie(response, token)
    await record(db, action="login", username=user.username, user_id=user.id,
                 ip_address=_client_ip(request))
    await db.commit()
    return Token(access_token=token)


@router.post("/logout", response_model=MessageOut)
async def logout(
    request: Request, response: Response, user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    response.delete_cookie(COOKIE_NAME, path="/")
    await record(db, action="logout", username=user.username, user_id=user.id,
                 ip_address=_client_ip(request))
    await db.commit()
    return MessageOut(detail="Logged out")


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


@router.post("/change-password", response_model=MessageOut)
async def change_password(
    payload: PasswordChange,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="New password must be different")
    user.hashed_password = hash_password(payload.new_password)
    user.must_change_password = False
    user.password_changed_at = utcnow()
    await db.commit()
    return MessageOut(detail="Password updated")


@router.get("/users", response_model=list[UserOut])
async def list_users(
    _: User = Depends(require_user_manage), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).order_by(User.id))
    return result.scalars().all()


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    payload: UserCreate,
    request: Request,
    _: User = Depends(require_user_manage),
    db: AsyncSession = Depends(get_db),
):
    exists = await db.execute(
        select(User).where(
            (User.username == payload.username) | (User.email == payload.email)
        )
    )
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Username or email already exists")
    user = User(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        is_superuser=payload.is_superuser,
        role=payload.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await record(db, action="user_created", username=user.username, user_id=user.id,
                 entity_type="user", entity_id=user.id,
                 detail=f"created user {user.username} role={user.role.value}",
                 ip_address=_client_ip(request))
    await db.commit()
    return user


async def _count_active_superusers(db: AsyncSession, exclude_id: int | None = None) -> int:
    stmt = select(func.count()).select_from(User).where(
        User.is_superuser.is_(True), User.is_active.is_(True)
    )
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    return await db.scalar(stmt) or 0


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    _: User = Depends(require_user_manage),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    data = payload.model_dump(exclude_unset=True)

    # never let the last active superuser be demoted or disabled
    if user.is_superuser and (data.get("is_superuser") is False or data.get("is_active") is False):
        remaining = await _count_active_superusers(db, exclude_id=user.id)
        if remaining == 0:
            raise HTTPException(
                status_code=400,
                detail="Cannot disable or demote the last active superuser",
            )

    new_password = data.pop("password", None)
    if new_password:
        user.hashed_password = hash_password(new_password)
        user.must_change_password = False
        user.password_changed_at = utcnow()

    for key, value in data.items():
        setattr(user, key, value)

    await db.commit()
    await db.refresh(user)
    await record(db, action="user_updated", username=user.username, user_id=user.id,
                 entity_type="user", entity_id=user.id,
                 detail=f"updated user {user.username}",
                 ip_address=_client_ip(request))
    await db.commit()
    return user


@router.delete("/users/{user_id}", response_model=MessageOut)
async def delete_user(
    user_id: int,
    request: Request,
    current: User = Depends(require_user_manage),
    db: AsyncSession = Depends(get_db),
):
    if user_id == current.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_superuser:
        remaining = await _count_active_superusers(db, exclude_id=user.id)
        if remaining == 0:
            raise HTTPException(status_code=400, detail="Cannot delete the last active superuser")
    await db.delete(user)
    await db.commit()
    await record(db, action="user_deleted", username=current.username, user_id=current.id,
                 entity_type="user", entity_id=user_id,
                 detail=f"deleted user {user.username}",
                 ip_address=_client_ip(request))
    await db.commit()
    return MessageOut(detail="User deleted")


async def ensure_first_admin(db: AsyncSession) -> None:
    """Create the first admin account when the database is empty.

    If no password is configured, a random one is generated and logged once so
    that a weak default password can never be used in production.
    """
    count = await db.scalar(select(func.count()).select_from(User))
    if count and count > 0:
        return

    import logging
    import secrets

    log = logging.getLogger("netpulse.auth")
    password = settings.first_admin_password
    generated = False
    if not password:
        password = secrets.token_urlsafe(12)
        generated = True

    admin = User(
        username=settings.first_admin_username,
        email=settings.first_admin_email,
        hashed_password=hash_password(password),
        is_superuser=True,
        role=UserRole.super_admin,
        # force the operator to replace the generated password on first login
        must_change_password=True,
    )
    db.add(admin)
    await db.commit()

    if generated:
        log.warning(
            "=" * 68 + "\n  FIRST ADMIN CREATED - username: %s\n  GENERATED PASSWORD: %s\n"
            "  You MUST change this password on first login.\n"
            "  (Set FIRST_ADMIN_PASSWORD in .env to control it.)\n" + "=" * 68,
            settings.first_admin_username,
            password,
        )
