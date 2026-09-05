import logging
import time

from postgrest._sync.request_builder import SyncQueryRequestBuilder
from postgrest.exceptions import APIError
from supabase import Client, create_client

from env import ADMIN_SUPABASE_KEY, SUPABASE_URL, USER_SUPABASE_KEY

logger = logging.getLogger(__name__)

# Resilient PostgREST execution:
# If transient clock drift occurs between the client/gateway and database server,
# PostgREST raises APIError: "JWT issued at future" (PGRST301). Retrying after a
# brief delay avoids unhandled 500 errors and Sentry spikes.
_orig_postgrest_execute = SyncQueryRequestBuilder.execute


def _resilient_postgrest_execute(self, *args, **kwargs):
    for attempt in range(2):
        try:
            return _orig_postgrest_execute(self, *args, **kwargs)
        except APIError as e:
            err_msg = str(getattr(e, "message", e)).lower()
            if "jwt issued at future" in err_msg and attempt == 0:
                logger.warning(
                    "Clock skew detected ('JWT issued at future'). Retrying PostgREST query after 500ms..."
                )
                time.sleep(0.5)
                continue
            raise


SyncQueryRequestBuilder.execute = _resilient_postgrest_execute


class _MissingSupabaseClient:
    def __init__(self, missing_env: list[str]):
        self.missing_env = missing_env

    def table(self, *_args, **_kwargs):
        raise RuntimeError(
            "Supabase is not configured. Missing environment variables: "
            + ", ".join(self.missing_env)
        )


def _create_supabase_client(supabase_key: str, key_name: str) -> Client:
    missing = []
    if not SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not supabase_key:
        missing.append(key_name)
    if missing:
        return _MissingSupabaseClient(missing)  # type: ignore[return-value]

    try:
        return create_client(supabase_url=SUPABASE_URL, supabase_key=supabase_key)
    except Exception:
        return _MissingSupabaseClient(["SUPABASE_URL", key_name])  # type: ignore[return-value]


user_supabase: Client = _create_supabase_client(USER_SUPABASE_KEY, "USER_SUPABASE_KEY")
admin_supabase: Client = _create_supabase_client(ADMIN_SUPABASE_KEY, "ADMIN_SUPABASE_KEY")
