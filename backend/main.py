from fastapi import FastAPI, Request
import os
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Import configuration
import json

# Import routers
from routes.auth import router as auth_router
from routes.items import router as items_router
from routes.chat import router as chat_router
from routes.payment import router as payment_router
from routes.admin import router as admin_router
import sentry_sdk

# Initialize Sentry for error tracking
sentry_dsn = os.environ.get("SENTRY_DSN")
if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
    )

app = FastAPI(
    title="Second-Hand Store API",
    description="Fully autonomous second-hand store with AI negotiation",
    version="1.0.0",
    root_path="/api" if os.environ.get("VERCEL") else ""
)

# Setup rate limiter
from limiter import limiter
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
        "http://localhost:5173",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:5173",
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
app.include_router(auth_router)
app.include_router(items_router)
app.include_router(chat_router)
app.include_router(payment_router)
app.include_router(admin_router)


@app.get("/")
def root():
    return {"message": "Second-Hand Store API", "status": "running"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}