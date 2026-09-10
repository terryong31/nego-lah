"""Offline evaluation of the seller agent (SPEC-059).

Deliberately outside the pytest suite. These scenarios call a real model, so
they cost money and take minutes — running them on every commit would make the
test suite something people skip. Run them by hand when the prompt, the tools or
the model changes:

    mise run eval:agent
    mise run eval:agent -- --model gemini-3.8-flash-lite

Ragas lives in the opt-in `eval` dependency group, so production images do not
ship it.
"""
