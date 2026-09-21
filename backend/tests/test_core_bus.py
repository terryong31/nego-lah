"""
The in-process bus that keeps the domain graph acyclic (SPEC-097).

Billing does not know chat exists; identity does not know who else stores a
user's data; catalog does not know billing prices things. Each of those used to
be an import pointing up the stack. They are now an `emit` or an `ask`, and the
higher domain registers itself at startup.

The failure modes that matter are all about blast radius: a broken subscriber
must not take down the thing that emitted, and a missing provider must not turn
a page into a 500.
"""

import pytest

from core import bus


@pytest.fixture(autouse=True)
def _isolated_bus():
    """Each test gets an empty bus; the app's real wiring is restored after."""
    saved = bus.snapshot()
    bus.reset()
    yield
    bus.restore(saved)


class TestEvents:
    def test_a_subscriber_receives_the_payload(self):
        seen = []
        bus.on("thing.happened")(lambda **kw: seen.append(kw))
        bus.emit("thing.happened", user_id="u1", amount=12.5)
        assert seen == [{"user_id": "u1", "amount": 12.5}]

    def test_every_subscriber_runs(self):
        calls = []
        bus.on("thing.happened")(lambda **kw: calls.append("a"))
        bus.on("thing.happened")(lambda **kw: calls.append("b"))
        assert bus.emit("thing.happened") == 2
        assert sorted(calls) == ["a", "b"]

    def test_an_event_with_no_subscribers_is_not_an_error(self):
        """Emitting is a statement of fact. Whether anyone cares is their business."""
        assert bus.emit("nobody.listening", x=1) == 0

    def test_a_failing_subscriber_does_not_reach_the_emitter(self):
        """
        The one that matters. `purchase.fulfilled` is emitted from inside the
        Stripe webhook after the payment has settled — if a thank-you message
        failing could raise, a chat hiccup would fail the webhook and Stripe
        would redeliver a payment that was already fulfilled.
        """
        def boom(**kw):
            raise RuntimeError("chat is down")

        after = []
        bus.on("purchase.fulfilled")(boom)
        bus.on("purchase.fulfilled")(lambda **kw: after.append(kw))

        assert bus.emit("purchase.fulfilled", order_id="o1") == 2
        assert after == [{"order_id": "o1"}], "a failing subscriber blocked the next one"

    def test_the_same_handler_is_not_registered_twice(self):
        """Startup wiring that runs twice must not double-send every message."""
        calls = []
        handler = lambda **kw: calls.append(1)  # noqa: E731
        bus.on("thing.happened")(handler)
        bus.on("thing.happened")(handler)
        bus.emit("thing.happened")
        assert calls == [1]


class TestQueries:
    def test_a_provider_answers(self):
        bus.provides("billing.price")(lambda user_id, item_id: 42.0)
        assert bus.ask("billing.price", None, user_id="u1", item_id="i1") == 42.0

    def test_no_provider_returns_the_default(self):
        """
        A domain that has not been wired must degrade, not explode: the public
        items list renders at full price rather than 500ing.
        """
        assert bus.ask("billing.price", None, user_id="u1", item_id="i1") is None
        assert bus.ask("billing.price", 0.0, user_id="u1", item_id="i1") == 0.0

    def test_two_providers_for_one_query_is_rejected(self):
        """Ambiguity here is silent and load-bearing, so it is refused loudly."""
        bus.provides("billing.price")(lambda **kw: 1)
        with pytest.raises(ValueError, match="already has a provider"):
            bus.provides("billing.price")(lambda **kw: 2)

    def test_registering_the_identical_function_again_is_allowed(self):
        """Idempotent startup wiring, same as subscribers."""
        fn = lambda **kw: 1  # noqa: E731
        bus.provides("billing.price")(fn)
        bus.provides("billing.price")(fn)
        assert bus.ask("billing.price", None) == 1

    def test_a_provider_error_propagates(self):
        """
        Unlike an event, a query's caller is waiting on the answer — swallowing
        the failure would hand back a wrong price rather than no price.
        """
        bus.provides("billing.price")(lambda **kw: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            bus.ask("billing.price", None)


class TestWiring:
    def test_the_real_application_registers_its_subscribers(self):
        """
        The bus only works if someone imports the subscriber module. Domain
        `__init__` is lazy, so that has to be explicit — and a wiring call that
        silently registers nothing is the failure this catches.
        """
        bus.reset()
        from domains.negotiation import register_subscribers

        register_subscribers()
        for event in ("purchase.fulfilled", "shipment.recorded", "user.deleted"):
            assert bus.subscribers(event), f"nothing subscribed to {event}"

    def test_billing_provides_the_negotiated_price(self):
        bus.reset()
        from domains.billing import register_providers

        register_providers()
        assert bus.provider("billing.active_negotiated_price") is not None
