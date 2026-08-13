from app import mcp_server as m


def setup_db(tmp_path):
    m._db_path = str(tmp_path / "mcp_test.sqlite")
    m.init()


def test_read_and_write_flow(tmp_path):
    setup_db(tmp_path)

    user = m.upsert_user(tg_user_id=7, tg_username="quantik")
    assert user["default_currency"] == "BYN"

    cat = m.create_category("молочная продукция")
    prod = m.upsert_product("молоко", cat["id"])

    assert m.categories_list() == [{"id": cat["id"], "name": "молочная продукция"}]
    assert m.find_product("молоко")["category_name"] == "молочная продукция"
    assert m.find_product("нет") is None

    res = m.add_expenses(
        user["id"],
        [
            {
                "product_id": prod["id"],
                "qty": 1,
                "price": 1.92,
                "currency": "BYN",
                "purchased_at": "2026-08-13 10:00:00",
                "place": None,
                "source": "text",
            }
        ],
    )
    assert res["inserted"] == 1

    rows = m.query_expenses("2026-08-01", "2026-08-31", user["id"])
    assert rows[0]["product_name"] == "молоко"


def test_wallets_and_movements(tmp_path):
    setup_db(tmp_path)
    user = m.upsert_user(tg_user_id=1, tg_username="me")
    wallet = m.get_or_create_wallet(user["id"], "USD", "spending")
    m.add_movement(wallet["id"], "deposit", 100.0)

    balances = m.wallet_balances(user["id"])
    usd = next(w for w in balances if w["currency"] == "USD")
    assert usd["balance"] == 100.0


def test_subscriptions(tmp_path):
    setup_db(tmp_path)
    user = m.upsert_user(tg_user_id=1, tg_username="me")
    sub = m.create_subscription(user["id"], "Netflix", 12.99, "USD", 13)
    assert len(m.list_subscriptions(user["id"])) == 1

    m.deactivate_subscription(sub["id"])
    assert m.list_subscriptions(user["id"]) == []
    assert len(m.list_subscriptions(user["id"], active_only=False)) == 1
