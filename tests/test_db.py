from datetime import datetime

from app import db


def make_conn():
    conn = db.get_conn(":memory:")
    db.init_db(conn)
    return conn


def test_upsert_user_creates_and_updates():
    conn = make_conn()
    u1 = db.upsert_user(conn, tg_user_id=42, tg_username="quantik")
    assert u1["tg_user_id"] == 42
    assert u1["default_currency"] == "BYN"
    u2 = db.upsert_user(conn, tg_user_id=42, tg_username="quantik_new")
    assert u2["id"] == u1["id"]
    assert u2["tg_username"] == "quantik_new"


def test_new_user_gets_given_default_currency():
    conn = make_conn()
    u = db.upsert_user(conn, tg_user_id=9, tg_username="me", default_currency="USD")
    assert u["default_currency"] == "USD"


def test_set_default_currency_and_keep_on_reregister():
    conn = make_conn()
    u = db.upsert_user(conn, tg_user_id=9, tg_username="me", default_currency="BYN")
    db.set_default_currency(conn, u["id"], "EUR")
    u2 = db.upsert_user(conn, tg_user_id=9, tg_username="me2", default_currency="BYN")
    assert u2["default_currency"] == "EUR"
    assert u2["tg_username"] == "me2"


def test_insert_and_read_expense():
    conn = make_conn()
    user = db.upsert_user(conn, tg_user_id=1, tg_username="me")
    cat = db.create_category(conn, "молочная продукция")
    prod = db.upsert_product(conn, "молоко", cat["id"])

    res = db.add_expenses(
        conn,
        user_id=user["id"],
        items=[
            {
                "product_id": prod["id"],
                "qty": 1,
                "price": 1.92,
                "currency": "BYN",
                "purchased_at": "2026-08-12 16:40:00",
                "place": None,
                "source": "text",
            }
        ],
    )
    assert res["inserted"] == 1

    rows = db.query_expenses(conn, "2026-08-01", "2026-08-31", user["id"])
    assert len(rows) == 1
    r = rows[0]
    assert r["product_name"] == "молоко"
    assert r["category_name"] == "молочная продукция"
    assert r["qty"] == 1
    assert r["price"] == 1.92
    assert r["currency"] == "BYN"


def test_get_expense():
    conn = make_conn()
    user = db.upsert_user(conn, tg_user_id=1, tg_username="me")
    db.save_expenses(
        conn,
        user["id"],
        [
            {
                "name": "молоко",
                "category": "молочка",
                "qty": 1,
                "unit_price": 1.9,
                "price": 1.9,
                "currency": "BYN",
                "purchased_at": "2026-08-13 10:00:00",
                "place": None,
                "source": "text",
            }
        ],
    )
    rows = db.query_expenses(conn, "2026-08-01", "2026-08-31", user["id"])
    eid = rows[0]["id"]
    got = db.get_expense(conn, eid, user["id"])
    assert got["product_name"] == "молоко"
    assert got["category_name"] == "молочка"
    assert db.get_expense(conn, eid, 999) is None


def test_migration_adds_missing_columns():
    conn = db.get_conn(":memory:")
    conn.execute(
        "CREATE TABLE subscriptions (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " user_id INTEGER, wallet_id INTEGER, name TEXT, amount NUMERIC,"
        " currency TEXT, day_of_month INTEGER, comment TEXT, active INTEGER DEFAULT 1,"
        " last_charged_ym TEXT, created_at TEXT DEFAULT (datetime('now','localtime')))"
    )
    conn.execute(
        "INSERT INTO subscriptions (user_id, wallet_id, name, amount, currency, day_of_month)"
        " VALUES (1, 1, 'Old', 5, 'USD', 13)"
    )
    conn.commit()
    db.init_db(conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(subscriptions)")]
    assert "start_date" in cols
    assert conn.execute("SELECT start_date FROM subscriptions").fetchone()[0] is not None


def test_create_category_idempotent():
    conn = make_conn()
    a = db.create_category(conn, "бакалея")
    b = db.create_category(conn, "бакалея")
    assert a["id"] == b["id"]
    assert len(db.list_categories(conn)) == 1


def seed_expense(conn, user_id, price, currency, source="text"):
    cat = db.create_category(conn, "прочее")
    prod = db.upsert_product(conn, f"товар_{price}_{currency}", cat["id"])
    db.add_expenses(
        conn,
        user_id=user_id,
        items=[
            {
                "product_id": prod["id"],
                "qty": 1,
                "price": price,
                "currency": currency,
                "purchased_at": "2026-08-13 10:00:00",
                "place": None,
                "source": source,
            }
        ],
    )


def test_wallet_balance_deposit_minus_expenses():
    conn = make_conn()
    user = db.upsert_user(conn, tg_user_id=1, tg_username="me")
    wallet = db.get_or_create_wallet(conn, user["id"], "BYN", "spending")
    db.add_movement(conn, wallet["id"], "deposit", 100.0)
    seed_expense(conn, user["id"], 30.0, "BYN")
    assert db.wallet_balance(conn, wallet["id"]) == 70.0


def test_wallet_can_go_negative():
    conn = make_conn()
    user = db.upsert_user(conn, tg_user_id=1, tg_username="me")
    wallet = db.get_or_create_wallet(conn, user["id"], "BYN", "spending")
    seed_expense(conn, user["id"], 50.0, "BYN")
    assert db.wallet_balance(conn, wallet["id"]) == -50.0


def test_savings_not_touched_by_expenses():
    conn = make_conn()
    user = db.upsert_user(conn, tg_user_id=1, tg_username="me")
    savings = db.get_or_create_wallet(conn, user["id"], "BYN", "savings")
    db.add_movement(conn, savings["id"], "deposit", 500.0)
    seed_expense(conn, user["id"], 40.0, "BYN")
    assert db.wallet_balance(conn, savings["id"]) == 500.0


def test_correction_movement():
    conn = make_conn()
    user = db.upsert_user(conn, tg_user_id=1, tg_username="me")
    wallet = db.get_or_create_wallet(conn, user["id"], "USD", "spending")
    db.add_movement(conn, wallet["id"], "deposit", 100.0)
    db.add_movement(conn, wallet["id"], "correction", -10.0, comment="ошибка")
    assert db.wallet_balance(conn, wallet["id"]) == 90.0


def test_exchange_moves_between_wallets():
    conn = make_conn()
    user = db.upsert_user(conn, tg_user_id=1, tg_username="me")
    usd = db.get_or_create_wallet(conn, user["id"], "USD", "spending")
    db.add_movement(conn, usd["id"], "deposit", 100.0)
    r = db.exchange(conn, user["id"], "USD", "BYN", 40.0, 3.2)
    assert r["received"] == 128.0
    assert r["from_balance"] == 60.0
    assert r["to_balance"] == 128.0


def test_list_exchanges_returns_both_legs():
    conn = make_conn()
    user = db.upsert_user(conn, tg_user_id=1, tg_username="me")
    db.exchange(conn, user["id"], "USD", "BYN", 40.0, 3.2)
    rows = db.list_exchanges(conn, user["id"])
    assert len(rows) == 2
    assert {r["currency"] for r in rows} == {"USD", "BYN"}
    assert any(r["amount"] == -40.0 and r["currency"] == "USD" for r in rows)
    assert any(r["amount"] == 128.0 and r["currency"] == "BYN" for r in rows)


def test_subscription_charge():
    conn = make_conn()
    user = db.upsert_user(conn, tg_user_id=1, tg_username="me")
    sub = db.create_subscription(
        conn, user["id"], "Netflix", 12.99, "USD", "2026-08-13", comment="кино"
    )
    assert sub["day_of_month"] == 13
    due = db.due_subscriptions(conn, datetime(2026, 8, 13, 9, 0, 0))
    assert len(due) == 1

    db.charge_subscription(conn, sub, "2026-08-13 09:00:00")
    assert db.due_subscriptions(conn, datetime(2026, 8, 13, 9, 0, 0)) == []

    wallet = db.get_or_create_wallet(conn, user["id"], "USD", "spending")
    assert db.wallet_balance(conn, wallet["id"]) == -12.99

    rows = db.query_expenses(conn, "2026-08-01", "2026-08-31", user["id"])
    assert rows[0]["source"] == "subscription"
    assert rows[0]["category_name"] == "подписки"
