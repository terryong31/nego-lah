"""
Operator script: sign every buyer and admin out, everywhere.

Usage:
    infisical run --env=prod --path=/Backend -- uv run python scripts/revoke_all_sessions.py --yes

Deletes the server-side session records (`user:sess:*`, `admin:sess:*`), the
CSRF tokens bound to them, the bearer-token cache and any in-flight refresh
locks. The cookies browsers hold then point at nothing, so the next request is
anonymous and the person signs in again. The admin allowlist (`admin:allow:*`)
is left alone: revoking a session is not revoking an admin.

Written for the 2026-10-06 audit (SEC-1): session ids had been sent to Sentry,
so every session alive before the fix is treated as disclosed. Prints counts
only — never a key, since a key IS the session id.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cache import redis_client  # noqa: E402

PATTERNS = (
    "user:sess:*",
    "admin:sess:*",
    "ucsrf:*",
    "csrf:*",
    "token:*",
    "user:refreshlock:*",
)
BATCH = 500


def revoke(client=redis_client) -> dict[str, int]:
    """Delete every key matching PATTERNS, in batches. Returns counts per pattern."""
    counts: dict[str, int] = {}
    for pattern in PATTERNS:
        deleted = 0
        batch: list[str] = []
        for key in client.scan_iter(match=pattern, count=BATCH):
            batch.append(key)
            if len(batch) >= BATCH:
                for k in batch:
                    client.delete(k)
                deleted += len(batch)
                batch = []
        for k in batch:
            client.delete(k)
        counts[pattern] = deleted + len(batch)
    return counts


def main(argv: list[str]) -> int:
    if "--yes" not in argv:
        print(__doc__)
        print("Refusing to run without --yes: this signs everyone out.")
        return 2
    for pattern, n in revoke().items():
        print(f"{pattern:<22} {n} deleted")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
