import asyncio
import contextlib

# Import configuration
import json
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from core.defense_middleware import RequestDefenseMiddleware, SecurityHeadersMiddleware
from core.telemetry import init_sentry
from limiter import limiter
from logger import logger
from routes.admin import router as admin_router
from routes.chat import router as chat_router
from routes.items import router as items_router
from routes.payment import router as payment_router

# Import routers
from routes.user import router as user_router
from routes.webhooks import router as webhooks_router

# In production we hide the interactive API docs (Swagger UI / ReDoc) and the
# OpenAPI schema so the full API surface isn't publicly browsable. Set
# ENV=production in the deployed environment; locally it defaults to dev so
# /docs stays available.
IS_PROD = os.environ.get("ENV", "development").lower() in ("production", "prod")

# Initialize Sentry for error tracking. In development Sentry is disabled;
# in production it is strictly enforced (raises RuntimeError if SENTRY_DSN is missing).
init_sentry(is_prod=IS_PROD)

# How often the abandoned-payment cleanup runs (seconds). Default hourly.
CLEANUP_INTERVAL_SECONDS = int(os.environ.get("CLEANUP_INTERVAL_SECONDS", "3600"))


async def _payment_cleanup_loop():
    """
    Periodically release abandoned payment links: deactivate the Stripe link +
    archive the product once its 3-day TTL has passed. Runs in-process so no
    external cron is required. cleanup_expired_payments() is idempotent, so
    overlapping runs (e.g. multiple replicas) are harmless.
    """
    from cache import redis_client
    from payment.payment_state import cleanup_expired_payments

    def _claim_cleanup_slot() -> bool:
        # With multiple workers each runs this loop. A short Redis lock ensures
        # only ONE worker actually runs cleanup per cycle. If there's no shared
        # Redis (single process / in-memory), just run.
        try:
            return bool(redis_client.set(
                "payment:cleanup:lock", "1", nx=True, ex=CLEANUP_INTERVAL_SECONDS
            ))
        except Exception:
            return True

    # Small initial delay so startup isn't competing with first requests.
    await asyncio.sleep(30)
    while True:
        try:
            if _claim_cleanup_slot():
                # Run the blocking Redis/Stripe work off the event loop.
                cleaned = await asyncio.to_thread(cleanup_expired_payments)
                if cleaned:
                    logger.info(f"🧹 Payment cleanup released {cleaned} abandoned link(s)")
        except Exception as e:
            logger.error(f"❌ Payment cleanup loop error: {e}")
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    # Serverless (Vercel) can't keep a background loop alive across invocations;
    # only start the worker on a long-running server. Opt out with
    # DISABLE_PAYMENT_CLEANUP=1 if you run cleanup via an external scheduler.
    task = None
    from notifications import notification_broker

    # One Redis pub/sub connection per worker, so a notification published by
    # any worker reaches the SSE streams held by all of them.
    await notification_broker.start()

    if not os.environ.get("VERCEL"):
        from core.database import close_db_pool, init_db_pool
        await init_db_pool()
        if os.environ.get("DISABLE_PAYMENT_CLEANUP") != "1":
            task = asyncio.create_task(_payment_cleanup_loop())
            logger.info("🧹 Payment cleanup worker started")
    try:
        yield
    finally:
        await notification_broker.stop()
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if not os.environ.get("VERCEL"):
            from core.database import close_db_pool
            await close_db_pool()


app = FastAPI(
    title="Second-Hand Store API",
    description="Fully autonomous second-hand store with AI negotiation",
    version="1.0.0",
    root_path="/api" if os.environ.get("VERCEL") else "",
    docs_url=None if IS_PROD else "/docs",
    redoc_url=None if IS_PROD else "/redoc",
    openapi_url=None if IS_PROD else "/openapi.json",
    lifespan=lifespan,
)

# Setup rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware — environment-aware origins.
# Production: only the real domain. Dev: localhost variants + prod (for testing).
# CORS_ORIGINS env var overrides everything (e.g. staging).
_PROD_ORIGINS = [
    "https://negolah.my",
    "https://www.negolah.my",
    "https://api.negolah.my",
]

_DEV_ORIGINS = [
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:8000",
    "http://127.0.0.1",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "http://127.0.0.1:8000",
]

_ORIGIN_REGEX = (
    r"^https://([a-zA-Z0-9_-]+\.)*nego-lah\.pages\.dev$|"
    r"^https://([a-zA-Z0-9_-]+\.)*negolah\.my$"
)

cors_origins_str = os.environ.get("CORS_ORIGINS")
if cors_origins_str:
    try:
        origins = json.loads(cors_origins_str)
    except (TypeError, ValueError):
        # CORS_ORIGINS is also accepted as a plain comma-separated list.
        origins = cors_origins_str.split(",")
else:
    origins = _PROD_ORIGINS if IS_PROD else _DEV_ORIGINS + _PROD_ORIGINS

# Defense middleware — OWASP security headers & request body / path guards.
# Registered before CORSMiddleware: Starlette wraps middleware in reverse
# registration order, so the last one added ends up outermost. CORSMiddleware
# must be outermost — RequestDefenseMiddleware short-circuits (returns a
# response directly, without calling call_next) on oversized/malformed
# requests, and a response that never reaches CORSMiddleware carries no
# Access-Control-* headers, which the browser reports as a CORS failure
# instead of the real 413/400 (see SPEC-042).
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestDefenseMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "X-CSRF-Token",
        "sentry-trace",
        "baggage",
        "X-Turnstile-Token",
        "cf-turnstile-response",
    ],
    expose_headers=["X-CSRF-Token", "sentry-trace", "baggage"],
)

# Include routers
app.include_router(user_router)
app.include_router(items_router)
app.include_router(chat_router)
app.include_router(payment_router)
app.include_router(admin_router)
app.include_router(webhooks_router)


@app.get("/")
def root():
    return {"message": "Second-Hand Store API", "status": "running"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}
