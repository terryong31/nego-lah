"""One source of shipment wording (SPEC-057).

The buyer hears about a shipment three ways — an email, a live chat bubble, and
whatever the agent says when asked later. Three call sites composing their own
sentences is three chances to disagree about what was actually shipped, and the
buyer is the one who notices. They all read from here.
"""

from services.shipping_notice import shipment_chat_message, shipment_summary


def _order(**overrides):
    order = {
        "id": "order-1",
        "item_name": "Casio VX-4",
        "courier": "J&T Express",
        "tracking_number": "630123456789",
        "tracking_url": "https://www.jtexpress.my/tracking?billcode=630123456789",
    }
    order.update(overrides)
    return order


def test_the_summary_carries_everything_a_buyer_needs_to_act():
    s = shipment_summary(_order())
    assert s["item_name"] == "Casio VX-4"
    assert s["courier"] == "J&T Express"
    assert s["tracking_number"] == "630123456789"
    assert s["tracking_url"].startswith("https://")


def test_the_summary_derives_a_missing_tracking_url():
    """The console may store only courier + number; the link is computable."""
    s = shipment_summary(_order(tracking_url=None))
    assert "630123456789" in s["tracking_url"]


def test_the_summary_survives_an_unknown_courier():
    s = shipment_summary(_order(courier="Some Local Bike Guy", tracking_url=None))
    assert s["courier"] == "Some Local Bike Guy"
    assert s["tracking_url"] is None


def test_the_chat_message_states_the_courier_and_number():
    msg = shipment_chat_message(_order())
    assert "J&T Express" in msg
    assert "630123456789" in msg
    assert "Casio VX-4" in msg


def test_the_chat_message_includes_the_link_when_there_is_one():
    assert "https://www.jtexpress.my" in shipment_chat_message(_order())


def test_the_chat_message_reads_naturally_without_a_link():
    msg = shipment_chat_message(_order(courier="Some Local Bike Guy", tracking_url=None))
    assert "http" not in msg
    assert "Some Local Bike Guy" in msg
    assert msg.strip() == msg


def test_the_chat_message_never_looks_like_a_payment_link():
    """SPEC-056 #4: a markdown link in an assistant bubble is parsed for a
    PayCard. A tracking link must not arrive wearing a Stripe badge."""
    from_message = shipment_chat_message(_order())
    assert "](" not in from_message


def test_a_delivered_notice_is_worded_as_delivered():
    msg = shipment_chat_message(_order(), delivered=True)
    assert "delivered" in msg.lower()
    assert "Casio VX-4" in msg


def test_a_courier_without_a_tracking_number_is_still_worth_saying():
    """The seller may know who took it but not the code yet."""
    msg = shipment_chat_message(
        {**_order(), "tracking_number": None, "tracking_url": None}
    )
    assert "Shipped with J&T Express" in msg
    assert "None" not in msg


def test_a_tracking_number_without_a_courier_is_still_worth_saying():
    msg = shipment_chat_message(
        {**_order(), "courier": None, "tracking_url": None}
    )
    assert "630123456789" in msg
    assert "None" not in msg


def test_a_delivery_notice_carries_the_tracking_number_it_arrived_under():
    msg = shipment_chat_message(_order(), delivered=True)
    assert "630123456789" in msg


def test_a_delivery_notice_without_tracking_still_reads_as_a_sentence():
    msg = shipment_chat_message(
        {**_order(), "tracking_number": None, "tracking_url": None}, delivered=True
    )
    assert "delivered" in msg.lower()
    assert "None" not in msg
    assert "Tracking:" not in msg
