import logging
import os
import sys

import sentry_sdk
from pythonjsonlogger import jsonlogger


def get_logger(name: str = "nego_lah") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(jsonlogger.JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level"}
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


logger = get_logger("nego_lah")


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

    from sentry_sdk.integrations.asyncpg import AsyncPGIntegration
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.httpx import HttpxIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.redis import RedisIntegration

    sentry_sdk.init(
        dsn=sentry_dsn,
        environment="production",
        release=os.environ.get("SENTRY_RELEASE", "latest"),
        auto_session_tracking=True,
        send_default_pii=True,
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
            AsyncPGIntegration(),
            RedisIntegration(),
            HttpxIntegration(),
            LoggingIntegration(
                level=logging.INFO,
                event_level=logging.ERROR,
            ),
        ],
    )
