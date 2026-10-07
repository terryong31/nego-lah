import logging
import os
import sys

import sentry_sdk
from pythonjsonlogger import jsonlogger

from core.env import (
    ADMIN_COOKIE_NAME,
    CSRF_COOKIE_NAME,
    USER_COOKIE_NAME,
    USER_CSRF_COOKIE_NAME,
    USER_PKCE_COOKIE_NAME,
)


def get_logger(name: str = "nego_lah") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            jsonlogger.JsonFormatter(
                fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
                rename_fields={"asctime": "timestamp", "levelname": "level"},
            )
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


logger = get_logger("nego_lah")

# Cookies that are credentials. `send_default_pii` makes the FastAPI integration
# attach `request.cookies` to every event, and Sentry's scrubber only redacts
# exact denylist names — none of ours — so a live `admin_sid` was readable by
# anyone with access to the Sentry project (audit SEC-1).
SENSITIVE_COOKIES = (
    ADMIN_COOKIE_NAME,
    USER_COOKIE_NAME,
    USER_PKCE_COOKIE_NAME,
    USER_CSRF_COOKIE_NAME,
    CSRF_COOKIE_NAME,
)


# Request-body fields that are credentials (SPEC-104). The FastAPI integration
# attaches JSON bodies to events, and Sentry's default denylist knows `password`
# and `token` but not `new_password`, the admin OTP `code`, its pre-auth
# `handle`, or the recovery `token_hash`.
SENSITIVE_BODY_FIELDS = ("password", "current_password", "new_password", "code", "handle", "token_hash", "otp")

SENSITIVE_HEADERS = ("cookie", "authorization", "x-csrf-token", "x-origin-auth")


def scrub_event(event, _hint=None):
    """`before_send`: drop cookies outright and filter credential headers and body fields."""
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("cookies", None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            for name in list(headers):
                if name.lower() in SENSITIVE_HEADERS:
                    headers[name] = "[Filtered]"
        data = request.get("data")
        if isinstance(data, dict):
            for name in list(data):
                if isinstance(name, str) and name.lower() in SENSITIVE_BODY_FIELDS:
                    data[name] = "[Filtered]"
    return event


def init_sentry(is_prod: bool = False):
    """
    Initialize Sentry telemetry according to environment:
    - In development (is_prod=False): Sentry is disabled to prevent quota exhaustion and dev noise.
    - In production (is_prod=True): Sentry is strictly enforced; raises RuntimeError if SENTRY_DSN is missing.
    """
    if not is_prod:
        logger.info("Sentry telemetry disabled in development mode.")
        return

    sentry_dsn = os.environ.get("SENTRY_DSN")
    if not sentry_dsn:
        raise RuntimeError("SENTRY_DSN environment variable is strictly required in production mode.")

    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.httpx import HttpxIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.redis import RedisIntegration
    from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber

    sentry_sdk.init(
        dsn=sentry_dsn,
        environment="production",
        release=os.environ.get("SENTRY_RELEASE", "latest"),
        auto_session_tracking=True,
        send_default_pii=True,
        before_send=scrub_event,
        before_send_transaction=scrub_event,
        event_scrubber=EventScrubber(
            denylist=DEFAULT_DENYLIST + list(SENSITIVE_COOKIES) + list(SENSITIVE_BODY_FIELDS) + ["x_origin_auth"]
        ),
        # 1. Logs (Pipes structured logs to Sentry Logs)
        enable_logs=True,
        # 2. Metrics (Custom & runtime metrics)
        enable_metrics=True,
        # 3. Traces (Distributed tracing)
        traces_sample_rate=0.2,
        trace_propagation_targets=[
            "https://api.negolah.my",
            "https://negolah.my",
            "https://www.negolah.my",
            "http://localhost:8000",
            "http://localhost:3000",
            "http://127.0.0.1:8000",
            "http://127.0.0.1:3000",
        ],
        # 4. Profiles (Continuous CPU profiling flame charts)
        profiles_sample_rate=0.2,
        profile_session_sample_rate=0.1,
        profile_lifecycle="trace",
        # 5. Integrations (Deep instrumentation)
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            RedisIntegration(),
            HttpxIntegration(),
            LoggingIntegration(
                level=logging.INFO,
                event_level=logging.ERROR,
            ),
        ],
    )
