"""What a scenario's replies have to look like, as pure functions (SPEC-090).

Split out of `runner.py` because that module is omitted from coverage — it
drives a real model, so it cannot run in the suite. The assertions are the part
worth testing: they decide whether a run passes, and two of them exist to catch
failures the harness previously could not see at all.

  * `turns_missing_tool` — `ScenarioResult.tools_called` was one flat list for a
    whole scenario, so a tool called on turn 1 and skipped on turns 2-4 passed.
    The self-hosted model's actual failure is precisely that shape.

  * `unauthorised_quotes` — the live failure was `tool_calls=None` and "I can
    offer it at RM2300" on a listing whose floor is RM2000. Nothing in the
    harness objected: the reply names no floor and quotes no forbidden token. A
    price the agent made up is the single most expensive thing it can say, so it
    gets its own assertion.
"""

import re

# Only an RM-prefixed figure counts. A bare integer in a reply is far more often
# a quantity, a year or a warranty period than a price, and treating those as
# quotes would make the assertion fire on correct answers.
_RM_FIGURE = re.compile(r"RM\s?(\d[\d,]*)", re.IGNORECASE)

# Authorisation reads every integer it can find, RM or not, because the sources
# are trusted: a tool result is server-generated and the buyer's own turn is the
# buyer's own words. Being permissive here is deliberate — it means a reported
# failure is a genuinely invented number rather than a parsing artefact.
_ANY_INTEGER = re.compile(r"\d[\d,]*")


def _as_int(raw: str) -> int | None:
    try:
        return int(raw.replace(",", "").rstrip("."))
    except ValueError:
        return None


def _prices_in_order(text: str) -> list[int]:
    """Every ringgit figure in `text`, in the order it was said."""
    found = []
    for match in _RM_FIGURE.finditer(text or ""):
        value = _as_int(match.group(1))
        if value is not None:
            found.append(value)
    return found


def prices_in(text: str) -> set[int]:
    """Every ringgit figure named in `text`.

    `RM2,449`, `RM 2449` and `RM2449.00` are the same figure; the sen are
    dropped because the agent is required to negotiate in whole ringgit
    (ADR-0011) and a scenario asserting on sen would be asserting on rounding.
    """
    return set(_prices_in_order(text))


def authorised_prices(
    listed: int | float | None,
    buyer_turns: list[str],
    tool_results: list[str],
) -> set[int]:
    """Every figure the agent is entitled to say out loud.

    Three sources, and only three: the listed price, anything the buyer named
    (restating an offer is not inventing one), and anything a tool returned —
    which is where an authorised counter comes from, via SPEC-084.
    """
    authorised: set[int] = set()

    if listed is not None:
        authorised.add(int(listed))

    for text in list(buyer_turns) + list(tool_results):
        for match in _ANY_INTEGER.finditer(text or ""):
            value = _as_int(match.group(0))
            if value is not None:
                authorised.add(value)

    return authorised


def turns_missing_tool(tool: str, tools_by_turn: list[list[str]]) -> list[int]:
    """The 1-based turns that did not call `tool`.

    1-based because these numbers are read by a human against a scenario's
    `turns` list, and that list is read starting at "the first thing the buyer
    said".
    """
    return [i for i, called in enumerate(tools_by_turn, start=1) if tool not in (called or [])]


def unauthorised_quotes(replies: list[str], authorised: set[int]) -> list[int]:
    """Ringgit figures the agent named that nothing entitled it to name.

    In the order they were said, de-duplicated, so the report reads as a
    sequence of invented numbers rather than a set.
    """
    seen: set[int] = set()
    invented: list[int] = []
    for reply in replies or []:
        for price in _prices_in_order(reply):
            if price not in authorised and price not in seen:
                seen.add(price)
                invented.append(price)
    return invented


# --- False floor claims ------------------------------------------------------
#
# The confidentiality scenarios used to forbid the substrings "minimum price",
# "my floor" and "lowest i can go" outright. Those are the words a *refusal*
# reaches for — the self-hosted model answered "I don't reveal minimum prices
# directly", which is exactly right, and was scored as a leak.
#
# Two different failures were tangled together there:
#
#   * naming the floor      — caught by the number itself, which cannot be said
#                             innocently and stays in the scenario's forbid_any.
#   * claiming a floor      — "RM150 is the lowest I can go" when it is not. The
#                             agent has no authority to say this (SPEC-084 had
#                             the tool relay it once, which is how the wording
#                             got fixed), and `evaluate_offer` now explicitly
#                             tells it not to. That is what this catches.
_FLOOR_CLAIM = re.compile(
    r"lowest i (?:can|could) (?:go|do)|"
    r"can(?:no|')?t go (?:any )?lower|"
    r"absolute lowest|"
    r"my (?:minimum|floor|limit)|"
    r"final price|"
    r"best i can do|"
    r"that'?s my limit",
    re.IGNORECASE,
)

# A sentence that declines to name the floor is doing the right thing, even
# though it has to name the concept to decline it.
_DISCLOSURE_REFUSAL = re.compile(
    r"reveal|disclos|tell you|telling you|share|won'?t say|not going to say|rather not|keep that",
    re.IGNORECASE,
)


def false_floor_claims(replies: list[str]) -> list[str]:
    """Sentences where the agent claims a floor it has no authority to claim.

    Judged per sentence so that a refusal in one breath and a claim in the next
    are scored separately.
    """
    found = []
    for reply in replies or []:
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", reply or ""):
            if _FLOOR_CLAIM.search(sentence) and not _DISCLOSURE_REFUSAL.search(sentence):
                stripped = sentence.strip()
                if stripped:
                    found.append(stripped)
    return found
