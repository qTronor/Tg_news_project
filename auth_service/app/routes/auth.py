from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..dependencies import get_client_ip, get_current_user
from ..models import RefreshSession, User
from ..schemas import (
    PasswordChange,
    RefreshRequest,
    TokenPair,
    UserLogin,
    UserProfile,
    UserRegister,
    UserUpdate,
)
from ..security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from ..config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(
    body: UserRegister,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(User).where(or_(User.email == body.email, User.username == body.username))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email or username already taken")

    user = User(
        email=body.email,
        username=body.username,
        password_hash=hash_password(body.password),
        role="user",
    )
    db.add(user)
    await db.flush()

    return await _issue_tokens(user, request, db)


@router.post("/login", response_model=TokenPair)
async def login(
    body: UserLogin,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(or_(User.email == body.login, User.username == body.login))
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account deactivated")

    return await _issue_tokens(user, request, db)


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    body: RefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    token_hash = hash_refresh_token(body.refresh_token)
    result = await db.execute(
        select(RefreshSession).where(RefreshSession.refresh_token_hash == token_hash)
    )
    session = result.scalar_one_or_none()

    if not session or session.expires_at < datetime.now(timezone.utc):
        if session:
            await db.delete(session)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    user_result = await db.execute(select(User).where(User.id == session.user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        await db.delete(session)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or deactivated")

    await db.delete(session)
    return await _issue_tokens(user, request, db)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    token_hash = hash_refresh_token(body.refresh_token)
    result = await db.execute(
        select(RefreshSession).where(RefreshSession.refresh_token_hash == token_hash)
    )
    session = result.scalar_one_or_none()
    if session:
        await db.delete(session)


@router.get("/me", response_model=UserProfile)
async def get_me(user: User = Depends(get_current_user)):
    return user


@router.put("/me", response_model=UserProfile)
async def update_me(
    body: UserUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.username:
        existing = await db.execute(
            select(User).where(User.username == body.username, User.id != user.id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")
        user.username = body.username

    if body.email:
        existing = await db.execute(
            select(User).where(User.email == body.email, User.id != user.id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already taken")
        user.email = body.email

    return user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChange,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    user.password_hash = hash_password(body.new_password)


async def _issue_tokens(user: User, request: Request, db: AsyncSession) -> TokenPair:
    access = create_access_token(str(user.id), user.role)
    refresh = create_refresh_token()

    session = RefreshSession(
        user_id=user.id,
        refresh_token_hash=hash_refresh_token(refresh),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
        user_agent=request.headers.get("User-Agent", ""),
        ip_address=get_client_ip(request),
    )
    db.add(session)

    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_expire_minutes * 60,
    )
