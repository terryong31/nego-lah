"""scripts/revoke_all_sessions.py — the audit SEC-1 session rotation."""

from core.cache import redis_client
from scripts import revoke_all_sessions as script


def test_revokes_sessions_csrf_and_token_cache_but_keeps_the_admin_allowlist():
    for key in ("user:sess:a", "user:sess:b", "admin:sess:c", "ucsrf:a", "csrf:c", "token:t", "user:refreshlock:a"):
        redis_client.setex(key, 600, "x")
    redis_client.setex("admin:allow:u1", 600, "admin@example.com")
    redis_client.setex("item:1", 600, "{}")

    counts = script.revoke()

    assert counts["user:sess:*"] == 2
    assert counts["admin:sess:*"] == 1
    assert redis_client.keys("user:sess:*") == [] and redis_client.keys("csrf:*") == []
    assert redis_client.get("admin:allow:u1") == "admin@example.com"
    assert redis_client.get("item:1") == "{}"


def test_refuses_without_explicit_confirmation(capsys):
    redis_client.setex("user:sess:keep", 600, "x")
    assert script.main([]) == 2
    assert redis_client.get("user:sess:keep") == "x"
    assert "--yes" in capsys.readouterr().out


def test_prints_counts_never_keys(capsys):
    redis_client.setex("user:sess:SECRET-SID", 600, "x")
    assert script.main(["--yes"]) == 0
    out = capsys.readouterr().out
    assert "SECRET-SID" not in out
    assert "user:sess:*" in out
