"""
SPEC-048 — why aren't purchase-receipt emails arriving?

Run against a real environment's secrets:

    infisical run --env=dev  --path=/Backend -- uv run python scripts/diagnose_resend.py
    infisical run --env=prod --path=/Backend -- uv run python scripts/diagnose_resend.py

It is read-only. It reports:
  1. Which sender / recipient env vars are set (values masked).
  2. Every domain registered in the Resend account and its verification status —
     the usual culprit is that `negolah.my` is not `verified`, so Resend accepts
     the send (HTTP 2xx) but never delivers, or the code falls back to
     `onboarding@resend.dev` which only delivers to the account owner.
  3. The most recent outbound emails Resend has on record, with their delivery
     status, so you can see whether receipts are being rejected, bounced, or
     never attempted.

Nothing here sends an email or changes any Resend state.
"""

import os
import sys

import httpx

RESEND_API = "https://api.resend.com"


def _mask(value: str | None) -> str:
    if not value:
        return "<unset>"
    if "@" in value and "<" not in value:
        name, _, domain = value.partition("@")
        return f"{name[:2]}***@{domain}"
    return value  # display names / "Name <addr>" forms are not secret


def main() -> int:
    api_key = os.environ.get("RESEND_API_KEY")
    print("=== env ===")
    for name in (
        "RESEND_API_KEY",
        "RESEND_FORWARD_FROM",
        "RESEND_FORWARD_TO",
        "RESEND_ALLOWED_RECIPIENTS",
        "FRONTEND_URL",
        "STRIPE_API_KEY",
    ):
        raw = os.environ.get(name)
        if name == "RESEND_API_KEY":
            print(f"  {name} = {'set (' + raw[:5] + '…)' if raw else '<unset>'}")
        elif name == "STRIPE_API_KEY":
            mode = "LIVE" if (raw or "").startswith("sk_live_") else "test" if raw else "<unset>"
            print(f"  {name} = {mode}")
        else:
            print(f"  {name} = {_mask(raw)}")

    if not api_key:
        print("\n❌ RESEND_API_KEY is not set — run me through `infisical run`.")
        return 1

    headers = {"Authorization": f"Bearer {api_key}"}

    print("\n=== domains (GET /domains) ===")
    try:
        r = httpx.get(f"{RESEND_API}/domains", headers=headers, timeout=15)
        r.raise_for_status()
        domains = r.json().get("data", [])
        if not domains:
            print("  (none) — every send falls back to onboarding@resend.dev,")
            print("  which ONLY delivers to the Resend account owner's address.")
        for d in domains:
            print(f"  • {d.get('name')}: status={d.get('status')!r} region={d.get('region')} id={d.get('id')}")
            for rec in d.get("records", []) or []:
                ok = rec.get("status")
                print(f"      {rec.get('record')} {rec.get('type')} → {ok}")
    except Exception as e:
        print(f"  ⚠️ could not list domains: {e}")

    print("\n=== recent emails (GET /emails) ===")
    try:
        r = httpx.get(f"{RESEND_API}/emails", headers=headers, timeout=15)
        if r.status_code == 404:
            print("  (endpoint not available on this account/plan — check the Resend dashboard's Logs tab)")
        else:
            r.raise_for_status()
            for e in r.json().get("data", [])[:20]:
                print(
                    f"  • {e.get('created_at')} to={e.get('to')} "
                    f"subject={e.get('subject')!r} status={e.get('last_event') or e.get('status')!r}"
                )
    except Exception as e:
        print(f"  ⚠️ could not list emails: {e}")

    print("\nDone. If a domain shows status != 'verified', that is almost")
    print("certainly why receipts aren't arriving — verify it in the Resend")
    print("dashboard and set RESEND_FORWARD_FROM to 'Nego-Lah <receipts@negolah.my>'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
