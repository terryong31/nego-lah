from unittest.mock import MagicMock

import pytest

from cache import cache_token_user, redis_client
from conftest import make_supabase_result


@pytest.mark.asyncio
async def test_get_item_with_discounted_price(client, monkeypatch):
    # Mock item lookup
    fake_item = {
        "id": "item-discount-1",
        "name": "Mechanical Keyboard",
        "price": 200.0,
        "status": "available",
        "image_path": '{"img.png": "https://img.example/1.png"}',
    }
    fake_sb = MagicMock()
    fake_sb.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value = make_supabase_result([fake_item])
    monkeypatch.setattr("connector.user_supabase", fake_sb)

    # Set user token and negotiated price in Redis
    user_id = "user-nego-1"
    cache_token_user("tok-1", user_id)
    redis_client.setex(f"negotiated_price:{user_id}:item-discount-1", 3600, "150.0")

    # 1. Authenticated request sees discounted_price
    res = await client.get("/items/item-discount-1", headers={"Authorization": "Bearer tok-1"})
    assert res.status_code == 200
    data = res.json()
    assert data["price"] == 200.0
    assert data["discounted_price"] == 150.0

    # 2. Unauthenticated request does NOT see discounted_price
    res2 = await client.get("/items/item-discount-1")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["price"] == 200.0
    assert "discounted_price" not in data2


@pytest.mark.asyncio
async def test_get_all_items_with_discounted_price(client, monkeypatch):
    fake_items = [
        {
            "id": "item-list-1",
            "name": "Item 1",
            "price": 100.0,
            "status": "available",
            "image_path": '["https://img.example/1.png"]',
        }
    ]
    monkeypatch.setattr("routes.items.get_items", lambda kw: fake_items)

    user_id = "user-list-1"
    cache_token_user("tok-2", user_id)
    redis_client.setex(f"negotiated_price:{user_id}:item-list-1", 3600, "80.0")

    res = await client.get("/items", headers={"Authorization": "Bearer tok-2"})
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 1
    assert items[0]["price"] == 100.0
    assert items[0]["discounted_price"] == 80.0
