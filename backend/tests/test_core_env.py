"""
One config module, loading the right file (SPEC-097).

`core/env.py` began life as `backend/env.py` and computed its dotenv path from
`dirname(__file__)`. SPEC-092 moved it into `core/` and did not adjust that, so
it spent its life loading `backend/core/.env` — a file that has never existed —
while its own comment claimed it loaded "the backend's OWN .env". 41 modules
import it. `core/config.py`, which resolved the path correctly, had one.

Production never noticed because Infisical injects the variables directly. Local
development without Infisical is exactly the case a `.env` exists for.
"""

from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def test_env_loads_the_backend_dotenv():
    from core.env import ENV_FILE

    assert ENV_FILE == BACKEND / ".env", (
        f"core/env.py loads {ENV_FILE}, not the backend's .env. "
        "This is the SPEC-092 move leaving dirname(__file__) pointing at core/."
    )


def test_the_dotenv_path_is_not_inside_core():
    from core.env import ENV_FILE

    assert ENV_FILE.parent.name != "core", "the .env is the backend's, not core/'s"


def test_there_is_exactly_one_config_module():
    """
    `core/config.py` duplicated 27 of these keys and resolved two of them
    differently. Two modules reading the same variable is two answers waiting to
    disagree.
    """
    assert not (BACKEND / "core" / "config.py").exists(), (
        "core/config.py is back — its keys belong in core/env.py"
    )


def test_importing_env_twice_is_idempotent():
    """Reloaded by several tests; it must not accumulate or re-resolve differently."""
    import importlib

    import core.env

    first = core.env.ENV_FILE
    reloaded = importlib.reload(core.env)
    assert reloaded.ENV_FILE == first


def test_the_user_key_never_falls_back_to_the_admin_key():
    """
    SPEC-051/SPEC-056 #8: an unset anon key must fail closed. Silently promoting
    client-facing reads to service-role privileges bypasses RLS on every table.
    """
    source = (BACKEND / "core" / "env.py").read_text()
    user_key_line = next(line for line in source.splitlines() if line.startswith("USER_SUPABASE_KEY"))
    assert "ADMIN_SUPABASE_KEY" not in user_key_line, user_key_line
