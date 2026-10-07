import asyncio
import contextlib

# Import configuration
import json
import os
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Domain routers (Modular Monolith, ADR-0002). Each domain exports its own
# public router; the cross-domain admin console is composed in `admin_api`.
from console.admin_api import router as admin_router
from core.defense_middleware import RequestDefenseMiddleware, SecurityHeadersMiddleware
from core.env import ASYNCIO_EXECUTOR_THREADS
from core.logger import logger
from core.rate_limit_middleware import IPRateLimitMiddleware
from core.telemetry import init_sentry
from domains.billing import billing_router as payment_router
from domains.billing import register_providers
from domains.catalog import catalog_router as items_router
from domains.identity import auth_router, user_router
from domains.negotiation import negotiation_router as chat_router
from domains.negotiation import register_subscribers
from domains.webhooks import webhooks_router

# In production we hide the interactive API docs (Swagger UI / ReDoc) and the
# OpenAPI schema so the full API surface isn't publicly browsable. Set
# ENV=production in the deployed environment; locally it defaults to dev so
# /docs stays available.
IS_PROD = os.environ.get("ENV", "development").lower() in ("production", "prod")

# Initialize Sentry for error tracking. In development Sentry is disabled;
# in production it is strictly enforced (raises RuntimeError if SENTRY_DSN is missing).
init_sentry(is_prod=IS_PROD)

# How long shutdown waits for in-flight agent turns. Must stay under the
# container's `stop_grace_period` in docker-compose.yml.
SHUTDOWN_TURN_GRACE_SECONDS = float(os.environ.get("SHUTDOWN_TURN_GRACE_SECONDS", "20"))

# How often the abandoned-payment cleanup runs (seconds). Default hourly.
CLEANUP_INTERVAL_SECONDS = int(os.environ.get("CLEANUP_INTERVAL_SECONDS", "3600"))


async def _payment_cleanup_loop():
    """
    Periodically release abandoned payment links: deactivate the Stripe link +
    archive the product once its 3-day TTL has passed. Runs in-process so no
    external cron is required. cleanup_expired_payments() is idempotent, so
    overlapping runs (e.g. multiple replicas) are harmless.
    """
    from core.cache import redis_client
    from domains.billing import cleanup_expired_payments

    def _claim_cleanup_slot() -> bool:
        # With multiple workers each runs this loop. A short Redis lock ensures
        # only ONE worker actually runs cleanup per cycle. If there's no shared
        # Redis (single process / in-memory), just run.
        try:
            return bool(redis_client.set("payment:cleanup:lock", "1", nx=True, ex=CLEANUP_INTERVAL_SECONDS))
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


async def _unread_digest_loop():
    """
    SPEC-052: sweep the buffered unread-message queues and send the digests that
    have come due.

    Unlike the payment cleanup above this needs no slot lock: `drain_digest` is
    a single MULTI/EXEC read-then-delete, so if every worker sweeps at once the
    first to reach a queue takes it and the rest find it empty. The lock would
    only be saving a handful of no-op scans.
    """
    from domains.negotiation import UNREAD_DIGEST_SWEEP_SECONDS, flush_due_digests

    # Same courtesy delay as the cleanup worker: don't compete with startup.
    await asyncio.sleep(30)
    while True:
        try:
            # Redis reads plus a synchronous Resend call — always off the loop.
            sent = await asyncio.to_thread(flush_due_digests)
            if sent:
                logger.info(f"📧 Sent {sent} unread-message digest(s)")
        except Exception as e:
            logger.error(f"❌ Unread digest loop error: {e}")
        await asyncio.sleep(UNREAD_DIGEST_SWEEP_SECONDS)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    # Serverless (Vercel) can't keep a background loop alive across invocations;
    # only start the worker on a long-running server. Opt out with
    # DISABLE_PAYMENT_CLEANUP=1 if you run cleanup via an external scheduler.
    task = None
    digest_task = None
    from core.notifications import notification_broker
    from domains.negotiation import drain_running_turns

    # Size the pool `asyncio.to_thread` runs on. Python's default is
    # min(32, cpu_count + 4) — five or six threads here — and every request
    # makes several blocking Redis/Supabase calls through it (audit REL-1).
    asyncio.get_running_loop().set_default_executor(
        ThreadPoolExecutor(max_workers=ASYNCIO_EXECUTOR_THREADS, thread_name_prefix="to_thread")
    )

    # One Redis pub/sub connection per worker, so a notification published by
    # any worker reaches the SSE streams held by all of them.
    await notification_broker.start()

    if not os.environ.get("VERCEL"):
        if os.environ.get("DISABLE_PAYMENT_CLEANUP") != "1":
            task = asyncio.create_task(_payment_cleanup_loop())
            logger.info("🧹 Payment cleanup worker started")
        if os.environ.get("DISABLE_UNREAD_DIGEST") != "1":
            digest_task = asyncio.create_task(_unread_digest_loop())
            logger.info("📧 Unread-message digest worker started")
    try:
        yield
    finally:
        unfinished = await drain_running_turns(SHUTDOWN_TURN_GRACE_SECONDS)
        if unfinished:
            logger.warning(f"Shutdown cut {unfinished} agent turn(s) short")
        await notification_broker.stop()
        for background in (task, digest_task):
            if background:
                background.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await background


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

# In production, only permit exact canonical domain origins via allow_origins.
# Preview subdomains (*.nego-lah.pages.dev) are strictly confined to non-production.
_ORIGIN_REGEX = None if IS_PROD else r"^https://([a-zA-Z0-9_-]+\.)*nego-lah\.pages\.dev$"

cors_origins_str = os.environ.get("CORS_ORIGINS")
if cors_origins_str:
    try:
        origins = json.loads(cors_origins_str)
    except (TypeError, ValueError):
        # CORS_ORIGINS is also accepted as a plain comma-separated list.
        origins = cors_origins_str.split(",")
else:
    origins = _PROD_ORIGINS if IS_PROD else _DEV_ORIGINS + _PROD_ORIGINS

# Defense middleware — OWASP security headers, pre-routing rate limits & request body / path guards.
# Registered before CORSMiddleware: Starlette wraps middleware in reverse
# registration order, so the last one added ends up outermost. CORSMiddleware
# must be outermost — RequestDefenseMiddleware and IPRateLimitMiddleware short-circuit
# (return a response directly, without calling call_next) on oversized/malformed
# or rate-limited requests, and a response that never reaches CORSMiddleware carries no
# Access-Control-* headers, which the browser reports as a CORS failure
# instead of the real 413/429/400 (see SPEC-042 and SPEC-077).
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(IPRateLimitMiddleware)
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
        # Not CF-Connecting-IP: the client IP is Cloudflare's to state, and Caddy
        # overwrites it anyway (SPEC-104).
    ],
    expose_headers=["X-CSRF-Token", "sentry-trace", "baggage", "Retry-After"],
)

# Bus wiring (SPEC-097). Domains are layered and may only call downward, so the
# upward paths — a settled payment producing a chat message, a deleted account
# purging conversations, a storefront showing a negotiated price — are announced
# on `core.bus` and answered by whoever subscribes here.
#
# Registered at import rather than in the lifespan because the test suite drives
# the app without running the lifespan, and wiring that only exists in production
# is wiring nobody tests.
register_subscribers()
register_providers()

# Include routers
app.include_router(auth_router)
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
    """Liveness: the process is up. Deliberately checks nothing else, so a
    Redis blip does not get a healthy container restarted."""
    return {"status": "healthy"}


@app.get("/ready")
async def readiness_check():
    """Readiness: can this worker actually serve a signed-in request?

    `/health` answers "healthy" through every Redis failure mode, so it cannot
    tell an uptime monitor anything useful (audit OBS-1). This pings Redis with
    a timeout and reports whether cross-worker notifications are flowing.
    """
    from fastapi.responses import JSONResponse

    from core.cache import redis_client
    from core.notifications import notification_broker

    try:
        await asyncio.wait_for(asyncio.to_thread(redis_client.ping), timeout=2)
        redis_ok = True
    except Exception as e:
        logger.warning(f"Readiness: Redis ping failed: {e}")
        redis_ok = False
    body = {
        "status": "ready" if redis_ok else "unavailable",
        "redis": redis_ok,
        "notifications_distributed": notification_broker.distributed,
    }
    return JSONResponse(body, status_code=200 if redis_ok else 503)
