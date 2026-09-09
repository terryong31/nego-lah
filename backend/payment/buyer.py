"""
Buyer identity helpers shared by the checkout and fulfilment paths.

The buyer's Nego-Lah **account** email (Supabase auth) is the address we can
always reach and the one that matches who they logged in as. The email typed on
the Stripe checkout page is a fallback — it can be blank, a typo, or a different
address entirely. Both SPEC-047 (pre-fill checkout) and SPEC-048 (deliver the
receipt) need the account email, resolved the same way.
"""

from logger import logger


def account_email(user_id: str | None) -> str | None:
    """The buyer's Supabase auth email, or None if it can't be resolved.

    Never raises — a failed lookup is logged at error level (a receipt that
    can't be addressed is worth seeing in monitoring, per SPEC-048) and returns
    None so the caller can fall back.
    """
    if not user_id:
        return None
    try:
        from connector import admin_supabase

        res = admin_supabase.auth.admin.get_user_by_id(user_id)
        if res and hasattr(res, "user") and res.user:
            return res.user.email
        if isinstance(res, dict):
            return res.get("email") or (res.get("user") or {}).get("email")
    except Exception as e:
        logger.error(f"❌ Could not resolve account email for buyer {user_id}: {e}")
    return None
