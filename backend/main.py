import asyncio
import contextlib

# Import configuration
import json
import os

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

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

# Initialize Sentry for error tracking. environment lets prod vs local errors
# be filtered/alerted on separately in the Sentry dashboard.
sentry_dsn = os.environ.get("SENTRY_DSN")
if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        environment="production" if IS_PROD else "development",
        # Sends request headers/cookies and the client IP with every event
        # (Sentry's default header scrubbing is off with this enabled).
        send_default_pii=True,
        # Forwards application logs (see logger.py) to Sentry as a
        # separate, searchable stream in addition to error events.
        enable_logs=True,
        traces_sample_rate=1.0,
        # Continuous profiling (replaces the old profiles_sample_rate):
        # profile for the lifetime of every trace.
        profile_session_sample_rate=1.0,
        profile_lifecycle="trace",
    )

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
    if not os.environ.get("VERCEL") and os.environ.get("DISABLE_PAYMENT_CLEANUP") != "1":
        task = asyncio.create_task(_payment_cleanup_loop())
        logger.info("🧹 Payment cleanup worker started")
    try:
        yield
    finally:
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


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

# CORS middleware
cors_origins_str = os.environ.get("CORS_ORIGINS")
if cors_origins_str:
    try:
        origins = json.loads(cors_origins_str)
    except Exception:
        origins = cors_origins_str.split(",")
else:
    # Default origins if not specified in environment
    origins = [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:8000",
        "https://negolah.my",
        "http://negolah.my",
        "https://www.negolah.my"
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
