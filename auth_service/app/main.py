import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse

from .analytics_db import analytics_engine
from .config import get_settings
from .database import Base, engine
from .models import User
from .routes import admin, auth, reactions, sources
from .security import hash_password

logger = logging.getLogger("auth_service")
settings = get_settings()

limiter = Limiter(key_func=get_remote_address, default_limits=[f"{settings.rate_limit_per_minute}/minute"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if settings.admin_bootstrap_email and settings.admin_bootstrap_password:
        from sqlalchemy import select
        from .database import async_session

        async with async_session() as session:
            result = await session.execute(select(User).where(User.email == settings.admin_bootstrap_email))
            if not result.scalar_one_or_none():
                admin_user = User(
                    email=settings.admin_bootstrap_email,
                    username="admin",
                    password_hash=hash_password(settings.admin_bootstrap_password),
                    role="admin",
                )
                session.add(admin_user)
                await session.commit()
                logger.info("Bootstrap admin user created: %s", settings.admin_bootstrap_email)

    yield
    await analytics_engine.dispose()
    await engine.dispose()


app = FastAPI(
    title="TG News Auth Service",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please slow down."},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
    expose_headers=["X-Request-Id"],
    max_age=600,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response


app.include_router(auth.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(reactions.router, prefix="/api")
app.include_router(sources.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "auth"}
