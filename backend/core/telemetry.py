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

    from sentry_sdk.integrations.logging import LoggingIntegration
    sentry_sdk.init(
        dsn=sentry_dsn,
        environment="production",
        release=os.environ.get("SENTRY_RELEASE", "731092f67e3a1eefb8716bc53dc145016e6c412f"),
        auto_session_tracking=True,
        send_default_pii=True,
        enable_logs=True,
        enable_metrics=True,
        traces_sample_rate=0.2,
        profile_session_sample_rate=0.1,
        profile_lifecycle="trace",
        integrations=[
            LoggingIntegration(
                level=logging.INFO,
                event_level=logging.ERROR,
            ),
        ],
    )
