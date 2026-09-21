"""
Composition root. Not a bounded context.

`domains/` holds five contexts layered `identity < catalog < billing <
negotiation`, and a domain may only call strictly below itself (SPEC-097). Some
screens legitimately need two of them at once — the admin console's user table
shows a negotiation setting next to an identity profile, and the listing
authoring screen drafts a catalogue item with the agent's vision tools.

Code like that is not a domain that happens to be large; it is composition, and
it lives here. This package may import every domain. **No domain may import it**,
which `tests/test_domain_boundaries.py` enforces — that one rule is the whole
difference between a composition root and a sixth domain.
"""
