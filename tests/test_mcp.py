from app import db
from app import mcp_server as m


def setup_db(tmp_path):
    m._db_path = str(tmp_path / "mcp_test.sqlite")
    m.init()


def test_agent_surface(tmp_path):
    setup_db(tmp_path)

    conn = db.get_conn(m._db_path)
    user = db.upsert_user(conn, tg_user_id=7, tg_username="quantik")

    assert m.categories_list() == []

    res = m.save_expenses(
        user_id=user["id"],
        items=[
            {
                "name": "молоко",
                "category": "молочная продукция",
                "qty": 1,
                "unit_price": 1.92,
                "price": 1.92,
                "currency": "BYN",
            },
            {
                "name": "голубика",
                "category": "ягоды",
                "qty": 1,
                "unit_price": 20.0,
                "price": 20.0,
                "currency": "BYN",
            },
        ],
        purchased_at="2026-08-13 10:00:00",
        source="text",
    )
    assert res["inserted"] == 2

    names = {c["name"] for c in m.categories_list()}
    assert names == {"молочная продукция", "ягоды"}

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
            {"name": "молоко", "category": "молочка", "qty": 1, "unit_price": 2.0, "price": 2.0, "currency": "BYN"},
            {"name": "наушники", "category": "электроника", "qty": 1, "unit_price": 30.0, "price": 30.0, "currency": "USD"},
        ],
        purchased_at="2026-08-13 10:00:00",
        source="receipt",
        place="Shop",
    )

    byn = db.get_or_create_wallet(conn, user["id"], "BYN", "spending")
    usd = db.get_or_create_wallet(conn, user["id"], "USD", "spending")
    assert db.wallet_balance(conn, byn["id"]) == -2.0
    assert db.wallet_balance(conn, usd["id"]) == -30.0


def test_save_expenses_reuses_existing_category(tmp_path):
    setup_db(tmp_path)
    conn = db.get_conn(m._db_path)
    user = db.upsert_user(conn, tg_user_id=1, tg_username="me")

    common = dict(purchased_at="2026-08-13 10:00:00", source="text")
    m.save_expenses(
        user_id=user["id"],
        items=[{"name": "молоко", "category": "молочка", "qty": 1, "unit_price": 1.9, "price": 1.9, "currency": "BYN"}],
        **common,
    )
    m.save_expenses(
        user_id=user["id"],
        items=[{"name": "масло", "category": "молочка", "qty": 1, "unit_price": 4.6, "price": 4.6, "currency": "BYN"}],
        **common,
    )
    assert len(m.categories_list()) == 1
