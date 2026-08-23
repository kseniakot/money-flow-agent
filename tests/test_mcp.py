from app import db
from app.mcp import server as m


def setup_db(tmp_path):
    m._db_path = str(tmp_path / "mcp_test.sqlite")
    m.init()


def item(name, category, price, currency, purchased_at, source, place=None, qty=1):
    return {
        "name": name,
        "category": category,
        "qty": qty,
        "unit_price": price,
        "price": price,
        "currency": currency,
        "purchased_at": purchased_at,
        "place": place,
        "source": source,
    }


def test_agent_surface(tmp_path):
    setup_db(tmp_path)
    conn = db.get_conn(m._db_path)
    user = db.upsert_user(conn, tg_user_id=7, tg_username="quantik")

    assert m.categories_list() == []

    res = m.save_expenses(
        user_id=user["id"],
        items=[
            item("молоко", "молочная продукция", 1.92, "BYN", "2026-08-13 10:00:00", "text"),
            item("голубика", "ягоды", 20.0, "BYN", "2026-08-13 10:00:00", "text"),
        ],
    )
    assert res["inserted"] == 2
    assert {c["name"] for c in m.categories_list()} == {"молочная продукция", "ягоды"}

    rows = db.query_expenses(conn, "2026-08-01", "2026-08-31", user["id"])
    assert len(rows) == 2
    assert rows[0]["unit_price"] is not None


def test_mixed_currencies_hit_separate_wallets(tmp_path):
    setup_db(tmp_path)
    conn = db.get_conn(m._db_path)
    user = db.upsert_user(conn, tg_user_id=1, tg_username="me")

    m.save_expenses(
        user_id=user["id"],
        items=[
            item("молоко", "молочка", 2.0, "BYN", "2026-08-13 10:00:00", "receipt", "Shop"),
            item("наушники", "электроника", 30.0, "USD", "2026-08-13 10:00:00", "receipt", "Shop"),
        ],
    )
    byn = db.get_or_create_wallet(conn, user["id"], "BYN", "spending")
    usd = db.get_or_create_wallet(conn, user["id"], "USD", "spending")
    assert db.wallet_balance(conn, byn["id"]) == -2.0
    assert db.wallet_balance(conn, usd["id"]) == -30.0


def test_bank_per_line_date_and_place(tmp_path):
    setup_db(tmp_path)
    conn = db.get_conn(m._db_path)
    user = db.upsert_user(conn, tg_user_id=1, tg_username="me")

    m.save_expenses(
        user_id=user["id"],
        items=[
            item("отвертки", "инструменты", 9.85, "BYN", "2026-08-13 20:37:00", "bank", "OMBSHOP"),
            item("мусорные пакеты", "хозтовары", 8.87, "BYN", "2026-08-13 20:36:00", "bank", "OZON"),
        ],
    )
    rows = db.query_expenses(conn, "2026-08-13", "2026-08-13", user["id"])
    places = {r["place"] for r in rows}
    assert places == {"OMBSHOP", "OZON"}
    assert all(r["source"] == "bank" for r in rows)


def test_save_expenses_reuses_existing_category(tmp_path):
    setup_db(tmp_path)
    conn = db.get_conn(m._db_path)
    user = db.upsert_user(conn, tg_user_id=1, tg_username="me")

    m.save_expenses(
        user_id=user["id"],
        items=[item("молоко", "молочка", 1.9, "BYN", "2026-08-13 10:00:00", "text")],
    )
    m.save_expenses(
        user_id=user["id"],
        items=[item("масло", "молочка", 4.6, "BYN", "2026-08-13 11:00:00", "text")],
    )
    assert len(m.categories_list()) == 1
