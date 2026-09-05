"""Field access that works across Stripe SDK object shapes.

stripe-python 15 dropped the dict methods from `StripeObject`: it is no longer
a `dict` subclass, so `session.get("metadata")` raises

    AttributeError: 'get' is a dict method, but a Session is not a dict.

Subscripting (`session["metadata"]`) still works and remains the accessor the
SDK supports, but it raises `KeyError` for absent fields — which Stripe
resources routinely have, since optional fields are simply omitted. Webhook
payloads also reach us as plain dicts in some paths (and in fixtures), so
reads need to handle both shapes.

`stripe_get` is that one accessor: `.get()` semantics over either shape.
"""

from collections.abc import Mapping
from typing import Any


def stripe_get(obj: Any, key: str, default: Any = None) -> Any:
    """Read `key` from a Stripe resource or a mapping, `default` if absent.

    Never raises for a missing key or a `None` object, so it is safe to chain
    over optional nested resources:

        stripe_get(stripe_get(session, "customer_details"), "email")
    """
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    try:
        return obj[key]
    except (KeyError, IndexError, TypeError, AttributeError):
        return default
