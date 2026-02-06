from supabase import Client, create_client

from env import ADMIN_SUPABASE_KEY, SUPABASE_URL, USER_SUPABASE_KEY


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
