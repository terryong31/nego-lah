"""Give a scenario its listing without touching the database (SPEC-083).

`evals/scenarios.py` carries a full item — price, min_price, condition,
description — and says so in its own docstring: "everything below negotiates
over this so that a difference in the report is a difference in the agent, not
in the item". None of it ever reached the agent. `run_scenario` passed
`scenario.item["id"]` down as an item id, and that id ("eval-item-casio") is not
a UUID, so every lookup raised `invalid input syntax for type uuid` and
`evaluate_offer` answered "Cannot evaluate - item not found."

Every negotiation and confidentiality number the harness could produce was
therefore scored against an agent with no listing and a dead tool. Seeding a row
into the real `items` table instead would make the eval depend on live inventory
(and on the `min_price` column privileges SPEC-036 revoked), so the two data
seams are stubbed for the duration of a scenario instead. The eval is
single-item by design, so the stub ignores the id it is asked for.
"""

from contextlib import contextmanager
from unittest.mock import patch


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """The fluent part of the Supabase client, as far as the agent uses it.

    Every builder method is a chainable no-op — `select`, `eq`, `order`,
    `limit`, whatever a caller reaches for — because the eval serves one fixed
    row and filtering it would only ever return that row or nothing. Spelling
    them out individually meant `ConversationMemory.get_history` (which calls
    `.order`) raised inside the stub and logged an error on every single turn.
    """

    def __init__(self, rows):
        self._rows = rows

    def __getattr__(self, _name):
        def chain(*_args, **_kwargs):
            return self

        return chain

    def execute(self):
        return _Result(self._rows)


class _Client:
    """Answers `items` with the scenario's listing, every other table with nothing.

    `agent/tools/negotiation.py` does `from connector import admin_supabase`
    inside the function, so there is no module attribute to patch — the seam is
    `connector.admin_supabase` itself, which every tool shares. Scoping by table
    name keeps an orders or checkout scenario from being handed a pocket
    computer where it asked for an order.
    """

    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        return _Query(self._rows if name == "items" else [])


def item_row(item: dict) -> dict:
    """The scenario's item in the shape the `items` table returns."""
    return {
        "id": item["id"],
        "name": item["name"],
        "price": item["price"],
        "min_price": item["min_price"],
        "condition": item.get("condition", ""),
        "description": item.get("description", ""),
        "image_path": None,
        "status": "available",
    }


@contextmanager
def scenario_item(item: dict):
    """Serve `item` to both the prompt context and the negotiation tool.

    Two seams, because the listing reaches the agent by two routes: the
    knowledge card built in `bot._build_messages`, and the row `evaluate_offer`
    reads to find the floor.
    """
    row = item_row(item)
    client = _Client([row])
    with (
        # Function-local `from connector import ...` resolves at call time, so
        # patching the module attribute catches negotiation.py, payment.py and
        # items.py.
        patch("connector.admin_supabase", client),
        patch("connector.user_supabase", client),
        # orders.py binds `admin_supabase` at MODULE level, so it holds its own
        # reference and patching `connector` does not reach it.
        patch("agent.tools.orders.admin_supabase", client),
        patch("agent.bot.get_item_details_for_context", lambda _item_id: row),
    ):
        yield row
