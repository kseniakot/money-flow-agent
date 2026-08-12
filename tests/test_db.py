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


def test_find_product_returns_category():
    conn = make_conn()
    cat = db.create_category(conn, "ягоды")
    db.upsert_product(conn, "голубика", cat["id"])
    found = db.find_product(conn, "голубика")
    assert found["category_name"] == "ягоды"
    assert db.find_product(conn, "нет такого") is None


def test_create_category_idempotent():
    conn = make_conn()
    a = db.create_category(conn, "бакалея")
    b = db.create_category(conn, "бакалея")
    assert a["id"] == b["id"]
    assert len(db.list_categories(conn)) == 1
