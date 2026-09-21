"""The half of the real chat path the harness never had (SPEC-090).

`run_scenario` builds each turn's context with `bot._build_messages`, which
reconstructs the conversation from `conversation_memory.get_history()`. The real
`chat()` path writes each turn back with `add_message`. The harness never did,
and `evals.fixtures._Client` answers every table except `items` with `[]` — so
`get_history` returned nothing, every turn of every scenario was turn one, and
the multi-turn scenarios were measuring something that does not exist.

That is not a small discrepancy. SPEC-087 reproduced the self-hosted model's
repetition 3/3 with empty history and 0/3 with history present: the harness was
running the exact condition under which the model looks worst, while production
runs the other one, and both reported confidently.

Storing to the real `messages` table instead would make an eval run write rows
to whatever database the developer happens to be pointed at, and the harness has
to work on a laptop with no Supabase reachable. So the transcript lives in
process for the length of one scenario.
"""

from contextlib import contextmanager

from domains.negotiation.memory import DEFAULT_HISTORY_LIMIT


class ScenarioMemory:
    """`ConversationMemory`'s interface, backed by a dict.

    Only the two methods `_build_messages` and `chat()` actually use are
    implemented. Rows are returned in the shape `ConversationMemory._to_public`
    produces — `role`, `content`, `source`, and `tool_calls` only when asked —
    because `_replay_ai_turn` reads them directly and a shape mismatch would
    quietly replay a flat transcript instead of a traced one.
    """

    def __init__(self):
        self._rows: dict[str, list[dict]] = {}

    def add_message(
        self,
        user_id: str,
        role: str,
        message: str,
        item_id: str = None,
        source: str = "ai",
        tool_calls: list[dict] | None = None,
    ):
        self._rows.setdefault(user_id, []).append(
            {
                "role": role,
                "content": message,
                "source": source,
                "tool_calls": tool_calls or None,
            }
        )

    def get_history(
        self,
        user_id: str,
        limit: int = DEFAULT_HISTORY_LIMIT,
        offset: int = 0,
        include_tool_calls: bool = False,
    ) -> list[dict]:
        rows = self._rows.get(user_id, [])
        # `offset` counts back from the newest message, as it does on the real
        # one; no eval path passes it, but a silent disagreement here would be
        # the kind of thing that only shows up as a confusing report.
        if offset:
            rows = rows[: len(rows) - offset]
        if limit:
            rows = rows[-limit:]

        history = []
        for row in rows:
            public = {"role": row["role"], "content": row["content"], "source": row["source"]}
            if include_tool_calls and row["tool_calls"]:
                public["tool_calls"] = row["tool_calls"]
            history.append(public)
        return history


@contextmanager
def scenario_memory():
    """Swap the agent's conversation memory for an in-process one.

    `agent.bot` holds `conversation_memory` as a module-level singleton, so the
    module attribute is the seam. Restored on the way out: a leaked patch would
    disable persistence for the rest of the process, which in a test run means
    every later test quietly sharing one transcript.
    """
    from domains.negotiation import bot

    original = bot.conversation_memory
    memory = ScenarioMemory()
    bot.conversation_memory = memory
    try:
        yield memory
    finally:
        bot.conversation_memory = original
