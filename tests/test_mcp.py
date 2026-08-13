from app import db
from app import mcp_server as m


def setup_db(tmp_path):
    m._db_path = str(tmp_path / "mcp_test.sqlite")
    m.init()


def test_agent_surface_read_and_write(tmp_path):
    setup_db(tmp_path)

    conn = db.get_conn(m._db_path)
    user = db.upsert_user(conn, tg_user_id=7, tg_username="quantik")

    assert m.categories_list() == []

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

    rows = db.query_expenses(conn, "2026-08-01", "2026-08-31", user["id"])
    assert rows[0]["product_name"] == "молоко"
